import logging
import time
import asyncio
import inspect
import lancedb
import pyarrow as pa
import numpy as np
from typing import Optional, List, Any, Dict
from collections import OrderedDict
import uuid

from app.config import settings
from app.ml.config import MODELS_CONFIG

logger = logging.getLogger(__name__)

_CHAT_CACHE_MAX_USERS = 50  # max users kept in the in-process result cache


# ──────────────────────────────────────────────────────────────────────────────
# Schema helpers
# ──────────────────────────────────────────────────────────────────────────────

def _embedding_dim() -> int:
    try:
        return int(MODELS_CONFIG.get("embedding", {}).get("dimension", 1024))
    except Exception:
        return 1024


def _table_vector_dim(table: Any) -> Optional[int]:
    """Read the FixedSizeList dimension from the table's Arrow schema."""
    try:
        field = table.schema.field("vector")
        vtype = field.type
        return int(vtype.list_size) if hasattr(vtype, "list_size") else None
    except Exception:
        return None


def _make_schema() -> pa.Schema:
    return pa.schema([
        pa.field("id",        pa.string()),
        pa.field("user_id",   pa.string()),
        pa.field("role",      pa.string()),
        pa.field("content",   pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("vector",    pa.list_(pa.float32(), _embedding_dim())),
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Manager
# ──────────────────────────────────────────────────────────────────────────────

class LanceDBManager:
    """
    LanceDB backend for desktop vector search.

    One persistent table handle is kept open for the lifetime of the process;
    all blocking Arrow/pandas operations are dispatched to a thread pool via
    asyncio.to_thread so the event loop is never blocked.
    """

    _instance: Optional["LanceDBManager"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LanceDBManager._initialized:
            return
        LanceDBManager._initialized = True

        from app.utils.path_manager import PathManager
        db_path = PathManager().get_user_data_dir() / "db" / "lanceData"
        db_path.mkdir(parents=True, exist_ok=True)

        self._db = lancedb.connect(str(db_path))
        self._table = self._open_or_create_table()
        self._index_ready = False
        self._try_create_index()

        # In-process LRU: {user_id: [message_dicts]}
        self._chat_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()

        logger.info("LanceDB initialised at %s", db_path)

    # ──────────────────────────────────────────────
    # Table lifecycle
    # ──────────────────────────────────────────────

    def _open_or_create_table(self):
        """Open the 'user_queries' table, recreating it when the vector dimension changed."""
        expected_dim = _embedding_dim()

        if "user_queries" not in self._db.table_names():
            self._db.create_table("user_queries", schema=_make_schema())
            logger.info("Created 'user_queries' table (dim=%d)", expected_dim)

        table = self._db.open_table("user_queries")

        existing_dim = _table_vector_dim(table)
        if existing_dim is not None and existing_dim != expected_dim:
            logger.warning(
                "Vector dimension mismatch (table=%d, expected=%d) — recreating table",
                existing_dim, expected_dim,
            )
            self._db.create_table("user_queries", schema=_make_schema(), mode="overwrite")
            table = self._db.open_table("user_queries")

        return table

    def _try_create_index(self) -> None:
        """
        Attempt to create an ANN vector index for faster search.
        Skipped gracefully on empty tables or mismatched LanceDB API versions.
        """
        if self._index_ready:
            return

        def _create() -> None:
            try:
                if int(self._table.count_rows()) == 0:
                    logger.debug("Index deferred: table is empty")
                    return
            except Exception:
                pass  # count_rows may not exist on older versions

            # Introspect the signature so we don't pass args that don't exist
            params = set(inspect.signature(self._table.create_index).parameters)
            kwargs: Dict[str, Any] = {}
            if "vector_column_name" in params:
                kwargs["vector_column_name"] = "vector"
            if "metric" in params:
                kwargs["metric"] = "cosine"
            elif "distance_type" in params:
                kwargs["distance_type"] = "cosine"
            if "index_type" in params:
                kwargs["index_type"] = "IVF_FLAT"  # no PQ training needed for small datasets

            try:
                self._table.create_index(**kwargs)
            except TypeError:
                kwargs.pop("replace", None)
                self._table.create_index(**kwargs)
            except Exception as exc:
                if "already exists" not in str(exc).lower():
                    raise

        try:
            _create()
            self._index_ready = True
            logger.info("LanceDB vector index ready")
        except Exception as exc:
            logger.warning("LanceDB index skipped: %s", exc)

    # ──────────────────────────────────────────────
    # In-process cache helpers
    # ──────────────────────────────────────────────

    def _cache_get(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
        if user_id in self._chat_cache:
            self._chat_cache.move_to_end(user_id)
            return self._chat_cache[user_id]
        return None

    def _cache_set(self, user_id: str, messages: List[Dict[str, Any]]) -> None:
        self._chat_cache[user_id] = messages
        self._chat_cache.move_to_end(user_id)
        while len(self._chat_cache) > _CHAT_CACHE_MAX_USERS:
            self._chat_cache.popitem(last=False)

    def _cache_invalidate(self, user_id: str) -> None:
        self._chat_cache.pop(user_id, None)

    # ──────────────────────────────────────────────
    # Normalisation helper
    # ──────────────────────────────────────────────

    @staticmethod
    def _l2_normalize(vec: List[float]) -> List[float]:
        """Unit-normalise to float32. Required for dot-product == cosine similarity."""
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return (arr / norm).tolist() if norm > 0 else vec

    # ──────────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────────

    async def add_chat_message(
        self,
        user_id: str,
        role: str,
        content: str,
        vector: List[float],
        timestamp: str,
    ) -> bool:
        """Insert one message row. Vectors are unit-normalised before storage."""
        try:
            row = [{
                "id":        f"{user_id}_{int(time.time() * 1_000_000)}_{uuid.uuid4().hex[:8]}",
                "user_id":   user_id,
                "role":      role,
                "content":   content,
                "timestamp": timestamp,
                "vector":    self._l2_normalize(vector),
            }]
            await asyncio.to_thread(self._table.add, row)

            # Try to build index on first insert if it was deferred
            if not self._index_ready:
                self._try_create_index()

            self._cache_invalidate(user_id)
            logger.debug("LanceDB row added [%s] %.60s", role, content)
            return True
        except Exception as exc:
            logger.error("LanceDB add_chat_message failed: %s", exc, exc_info=True)
            return False

    # ──────────────────────────────────────────────
    # Read – chat history (no vectors)
    # ──────────────────────────────────────────────

    async def get_chat_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the `limit` most recent messages in chronological order."""
        # In-process cache
        cached = self._cache_get(user_id)
        if cached is not None:
            return cached[-limit:] if len(cached) > limit else cached

        def _fetch() -> List[Dict[str, Any]]:
            df = (
                self._table.search()
                .where(f"user_id = '{user_id}'")
                .select(["id", "role", "content", "timestamp"])
                .limit(limit * 5)   # over-fetch to allow dedup
                .to_pandas()
            )
            if df.empty:
                return []
            # Deduplicate by (content, timestamp) — LanceDB append-only means dupes can exist
            seen: Dict[str, Dict] = {}
            for _, row in df.iterrows():
                k = f"{row['content']}_{row['timestamp']}"
                if k not in seen:
                    seen[k] = {"id": row["id"], "role": row["role"],
                                "content": row["content"], "timestamp": row["timestamp"]}
            history = sorted(seen.values(), key=lambda x: x["timestamp"])
            return history[-limit:]

        try:
            result = await asyncio.to_thread(_fetch)
            if result:
                self._cache_set(user_id, result)
            return result
        except Exception as exc:
            logger.error("LanceDB get_chat_history failed: %s", exc, exc_info=True)
            return []

    # ──────────────────────────────────────────────
    # Read – semantic search
    # ──────────────────────────────────────────────

    async def search_chat_messages(
        self,
        user_id: str,
        query_vector: List[float],
        limit: int = 10,
        threshold: float = 0.5,
        candidate_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Cosine-similarity search via dot product on unit-normalised vectors.

        `candidate_limit` controls how many ANN candidates LanceDB fetches before
        we re-rank and apply the threshold filter.  More candidates → better recall
        at the cost of slightly more pandas work.
        """
        query_norm = np.array(self._l2_normalize(query_vector), dtype=np.float32)

        default_candidates = int(getattr(settings, "STREAM_CONTEXT_CANDIDATE_LIMIT", 48))
        n_candidates = max(limit, min(256, candidate_limit or default_candidates))

        def _run() -> List[Dict[str, Any]]:
            df = (
                self._table.search(query_norm.tolist())
                .where(f"user_id = '{user_id}'")
                .limit(n_candidates)
                .to_pandas()
            )
            if df.empty:
                return []

            results: List[Dict[str, Any]] = []
            seen: set = set()

            for _, row in df.iterrows():
                content   = str(row.get("content", ""))
                timestamp = str(row.get("timestamp", ""))
                dedup_key = f"{content}_{timestamp}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Recompute exact cosine from stored (already normalised) vector
                stored = row.get("vector")
                if stored is not None:
                    try:
                        sv = np.asarray(stored, dtype=np.float32)
                        sv_norm = np.linalg.norm(sv)
                        if sv_norm > 0:
                            sv = sv / sv_norm
                        cosine = float(np.clip(np.dot(query_norm, sv), 0.0, 1.0))
                    except Exception:
                        # Fall back to distance-derived approximation
                        dist = float(row.get("_distance", 2.0))
                        cosine = max(0.0, 1.0 - (dist ** 2) / 2.0)
                else:
                    dist = float(row.get("_distance", 2.0))
                    cosine = max(0.0, 1.0 - (dist ** 2) / 2.0)

                if cosine < threshold:
                    continue

                score = round(cosine, 4)
                results.append({
                    "id":               str(row.get("id", "")),
                    "role":             str(row.get("role", "user")),
                    "content":          content,
                    "timestamp":        timestamp,
                    "score":            score,
                    "_similarity_score": score,
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]

        try:
            results = await asyncio.to_thread(_run)
            logger.info(
                "LanceDB search: found=%d threshold=%.2f top_score=%.4f",
                len(results), threshold, results[0]["score"] if results else 0.0,
            )
            return results
        except Exception as exc:
            logger.error("LanceDB search_chat_messages failed: %s", exc, exc_info=True)
            return []

    # ──────────────────────────────────────────────
    # Housekeeping
    # ──────────────────────────────────────────────

    async def clear_user_data(self, user_id: str) -> bool:
        """Delete all rows for a user and evict the in-process cache."""
        try:
            await asyncio.to_thread(self._table.delete, f"user_id = '{user_id}'")
            self._cache_invalidate(user_id)
            logger.info("LanceDB: cleared data for user %s", user_id)
            return True
        except Exception as exc:
            logger.error("LanceDB clear_user_data failed: %s", exc, exc_info=True)
            return False

    async def compact_and_optimize(self) -> bool:
        """Compact append-only fragments. Run periodically (e.g. on app close)."""
        try:
            await asyncio.to_thread(self._table.compact_files)
            logger.info("LanceDB table compacted")
            return True
        except Exception as exc:
            logger.error("LanceDB compact failed: %s", exc)
            return False

    async def get_table_stats(self) -> Dict[str, Any]:
        """Simple row-count stats for diagnostics."""
        try:
            def _stats():
                df = self._table.to_pandas()
                return {
                    "total_messages": len(df),
                    "unique_users": int(df["user_id"].nunique()) if not df.empty else 0,
                }
            return await asyncio.to_thread(_stats)
        except Exception as exc:
            logger.error("LanceDB get_table_stats failed: %s", exc)
            return {}

    async def ping(self) -> bool:
        return True