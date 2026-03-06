from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pinecone import AwsRegion, CloudProvider, IndexEmbed, Metric, Pinecone

from app.config import settings
from app.utils.extract_keywords import extract_keywords

logger = logging.getLogger(__name__)


class PineconeService:
    """
    Singleton service for Pinecone operations.

    - Desktop/default: vector upsert/query path.
    - Production (flagged): integrated embeddings + batched upsert_records queue.
    """

    _instance: Optional["PineconeService"] = None
    _initialized: bool = False

    NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
    INTEGRATED_BATCH_SIZE = 96
    INTEGRATED_FLUSH_INTERVAL_S = 1.5
    INTEGRATED_QUEUE_MAX = 5000

    def __new__(cls) -> "PineconeService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if PineconeService._initialized:
            return
        self._setup_client()
        self._setup_index()

        self._integrated_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self.INTEGRATED_QUEUE_MAX)
        self._integrated_stop = threading.Event()
        self._integrated_worker: Optional[threading.Thread] = None

        if self._use_integrated_embeddings():
            self._start_integrated_worker()

        PineconeService._initialized = True

    def _setup_client(self):
        self.client = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name
        self.namespace = settings.pinecone_metadata_namespace

    def _setup_index(self):
        if not self.client.has_index(self.index_name):
            logger.info("No Pinecone index named %s found. Creating one...", self.index_name)
            self.client.create_index_for_model(
                name=self.index_name,
                cloud=CloudProvider.AWS,
                region=AwsRegion.US_EAST_1,
                embed=IndexEmbed(
                    model="llama-text-embed-v2",
                    metric=Metric.COSINE,
                    field_map={"text": "text"},
                ),
            )
            logger.info("Waiting for Pinecone index provisioning...")
            time.sleep(10)
        else:
            logger.info("✅ Pinecone index is available: %s", self.index_name)

        self.index = self.client.Index(self.index_name)

    def _use_integrated_embeddings(self) -> bool:
        return bool(
            settings.environment == "PRODUCTION"
            and getattr(settings, "pinecone_integrated_embeddings_prod", True)
        )

    def _start_integrated_worker(self) -> None:
        if self._integrated_worker and self._integrated_worker.is_alive():
            return
        self._integrated_stop.clear()
        self._integrated_worker = threading.Thread(
            target=self._integrated_flush_loop,
            daemon=True,
            name="pinecone-integrated-writer",
        )
        self._integrated_worker.start()
        logger.info("🚚 Pinecone integrated upsert worker started")

    def shutdown(self) -> None:
        self._integrated_stop.set()
        worker = self._integrated_worker
        if worker and worker.is_alive():
            worker.join(timeout=3.0)
        self._flush_integrated_batch(force=True)

    @staticmethod
    def generate_stable_id(user_id: str, query: str) -> str:
        content = f"{user_id}:{query}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def get_embedding(self, text: str) -> List[float]:
        response = self.client.inference.embed(
            model="llama-text-embed-v2",
            inputs=[text],
            parameters={"input_type": "passage"},
        )
        return response.data[0].values

    def _enqueue_integrated_record(self, record: dict[str, Any]) -> None:
        try:
            self._integrated_queue.put_nowait(record)
        except queue.Full:
            logger.warning("Pinecone integrated queue full; forcing flush and retry")
            self._flush_integrated_batch(force=True)
            try:
                self._integrated_queue.put_nowait(record)
            except queue.Full:
                logger.error("Pinecone integrated queue still full; dropping record _id=%s", record.get("_id"))

    def _integrated_flush_loop(self) -> None:
        while not self._integrated_stop.is_set():
            self._flush_integrated_batch(force=False)
            self._integrated_stop.wait(self.INTEGRATED_FLUSH_INTERVAL_S)
        self._flush_integrated_batch(force=True)

    def _flush_integrated_batch(self, force: bool) -> None:
        if not self._use_integrated_embeddings():
            return

        batch: list[dict[str, Any]] = []
        target = self.INTEGRATED_BATCH_SIZE
        if force:
            target = max(1, min(self.INTEGRATED_BATCH_SIZE, self._integrated_queue.qsize()))

        while len(batch) < target:
            try:
                item = self._integrated_queue.get_nowait()
                batch.append(item)
            except queue.Empty:
                break

        if not batch:
            return

        max_retries = 4
        for attempt in range(max_retries):
            try:
                self.index.upsert_records(namespace=self.namespace, records=batch)
                logger.debug("✅ Pinecone integrated upsert batch flushed (%d records)", len(batch))
                return
            except Exception as exc:
                text = str(exc).lower()
                retryable = "429" in text or "too_many_requests" in text or "resource_exhausted" in text
                if retryable and attempt < (max_retries - 1):
                    backoff = min(4.0, 0.5 * (2**attempt))
                    time.sleep(backoff)
                    continue
                logger.warning(
                    "Pinecone integrated batch upsert failed (attempt %d/%d): %s. Falling back to vector upsert.",
                    attempt + 1,
                    max_retries,
                    exc,
                )
                self._fallback_vector_upsert_batch(batch)
                return

    def _fallback_vector_upsert_batch(self, batch: list[dict[str, Any]]) -> None:
        vectors = []
        for record in batch:
            query = str(record.get("query") or record.get("text") or record.get("chunk_text") or "").strip()
            user_id = str(record.get("user_id") or "").strip()
            if not query or not user_id:
                continue
            record_id = str(record.get("_id") or self.generate_stable_id(user_id, query))
            try:
                embedding = self.get_embedding(query)
            except Exception:
                continue
            vectors.append(
                {
                    "id": record_id,
                    "values": embedding,
                    "metadata": {
                        "user_id": user_id,
                        "query": query,
                        "timestamp": record.get("timestamp") or datetime.now(self.NEPAL_TZ).isoformat(),
                    },
                }
            )
        if vectors:
            self.index.upsert(vectors=vectors, namespace=self.namespace)

    def upsert_query(self, user_id: str, query: str) -> None:
        record_id = self.generate_stable_id(user_id, query)
        timestamp = datetime.now(self.NEPAL_TZ).isoformat()

        if self._use_integrated_embeddings():
            record = {
                "_id": record_id,
                "text": query,
                "chunk_text": query,
                "query": query,
                "user_id": user_id,
                "timestamp": timestamp,
            }
            self._enqueue_integrated_record(record)
            return

        try:
            embedding = self.get_embedding(query)
            self.index.upsert(
                vectors=[
                    {
                        "id": record_id,
                        "values": embedding,
                        "metadata": {
                            "user_id": user_id,
                            "query": query,
                            "timestamp": timestamp,
                        },
                    }
                ],
                namespace=self.namespace,
            )
        except Exception as e:
            logger.warning("[pinecone] Vector upsert failed: %s", e)

    def _integrated_search(
        self,
        *,
        user_id: str,
        search_text: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        def _pick(source: Any, *keys: str, default: Any = None) -> Any:
            for key in keys:
                if isinstance(source, dict):
                    if key in source and source.get(key) is not None:
                        return source.get(key)
                else:
                    value = getattr(source, key, None)
                    if value is not None:
                        return value
            return default

        def _as_dict(value: Any) -> dict[str, Any]:
            if isinstance(value, dict):
                return value
            to_dict = getattr(value, "to_dict", None)
            if callable(to_dict):
                try:
                    dumped = to_dict()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass
            model_dump = getattr(value, "model_dump", None)
            if callable(model_dump):
                try:
                    dumped = model_dump()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass
            if hasattr(value, "items"):
                try:
                    return {str(k): v for k, v in value.items()}  # type: ignore[call-arg]
                except Exception:
                    return {}
            return {}

        def _search_hits(apply_user_filter: bool) -> list[Any]:
            query_payload: dict[str, Any] = {
                "top_k": max(1, min(int(top_k), 20)),
                "inputs": {"text": search_text},
            }
            if apply_user_filter:
                query_payload["filter"] = {"user_id": {"$eq": user_id}}

            response = self.index.search_records(
                namespace=self.namespace,
                query=query_payload,
                fields=["query", "text", "chunk_text", "user_id", "timestamp"],
            )
            result = _pick(response, "result", default={})
            result_obj = _as_dict(result) if isinstance(result, dict) else result
            hits = _pick(result_obj, "hits", default=[])
            return hits if isinstance(hits, list) else []

        hits = _search_hits(apply_user_filter=True)
        # Some index configs ignore metadata filters; fallback to client-side filtering.
        if not hits:
            try:
                hits = _search_hits(apply_user_filter=False)
            except Exception:
                hits = []

        parsed: list[dict[str, Any]] = []
        for hit in hits:
            fields = _as_dict(_pick(hit, "fields", default={}))
            record_user_id = str(fields.get("user_id") or _pick(hit, "user_id", default="") or "")
            if record_user_id and record_user_id != user_id:
                continue

            raw_score = _pick(hit, "_score", "score", default=0.0)
            try:
                score = float(raw_score or 0.0)
            except (TypeError, ValueError):
                score = 0.0

            parsed.append(
                {
                    "id": str(_pick(hit, "_id", "id", default="") or ""),
                    "score": score,
                    "query": str(fields.get("query") or fields.get("text") or fields.get("chunk_text") or ""),
                    "user_id": record_user_id or user_id,
                    "timestamp": fields.get("timestamp") or _pick(hit, "timestamp", default="") or "",
                }
            )
        return parsed

    def search_user_queries(self, user_id: str, search_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            cleaned_text = extract_keywords(search_text)
            if self._use_integrated_embeddings():
                return self._integrated_search(
                    user_id=user_id,
                    search_text=cleaned_text,
                    top_k=top_k,
                )

            embedding = self.get_embedding(cleaned_text)
            results = self.index.query(
                vector=embedding,
                top_k=max(1, min(int(top_k), 20)),
                namespace=self.namespace,
                filter={"user_id": user_id},
                include_metadata=True,
                include_values=False,
            )
            matches = getattr(results, "matches", [])
            return [
                {
                    "id": match.id,
                    "score": match.score,
                    "query": match.metadata.get("query", "") if match.metadata else "",
                    "user_id": match.metadata.get("user_id", "") if match.metadata else "",
                    "timestamp": match.metadata.get("timestamp", 0) if match.metadata else 0,
                }
                for match in matches
            ]
        except Exception as e:
            logger.warning("Pinecone search failed: %s", e)
            return []

    def get_user_all_queries(self, user_id: str, top_k: int = 10) -> List[Dict[str, str]]:
        try:
            if self._use_integrated_embeddings():
                return self._integrated_search(
                    user_id=user_id,
                    search_text="all queries",
                    top_k=top_k,
                )

            embedding = self.get_embedding("all queries")
            results = self.index.query(
                vector=embedding,
                top_k=max(1, min(int(top_k), 20)),
                namespace=self.namespace,
                filter={"user_id": user_id},
                include_metadata=True,
                include_values=False,
            )
            matches = getattr(results, "matches", [])
            extracted_data = []
            for match in matches:
                if not match.metadata:
                    continue
                extracted_data.append(
                    {
                        "query": match.metadata.get("query", ""),
                        "timestamp": match.metadata.get("timestamp", 0),
                        "user_id": match.metadata.get("user_id", ""),
                        "score": match.score if hasattr(match, "score") else 0.0,
                        "id": match.id if hasattr(match, "id") else "",
                    }
                )
            return extracted_data
        except Exception as e:
            logger.warning("Failed to get user queries from Pinecone: %s", e)
            return []

    def delete_user_query(self, user_id: str, query: str) -> bool:
        try:
            record_id = self.generate_stable_id(user_id, query)
            self.index.delete(ids=[record_id], namespace=self.namespace)
            return True
        except Exception as e:
            logger.warning("Pinecone delete query failed: %s", e)
            return False

    def delete_user_all_queries(self, user_id: str) -> bool:
        try:
            self.index.delete(filter={"user_id": user_id}, namespace=self.namespace)
            return True
        except Exception as e:
            logger.warning("Pinecone delete all failed: %s", e)
            return False

    def get_index_stats(self) -> Dict[str, Any]:
        try:
            return self.index.describe_index_stats()  # type: ignore[return-value]
        except Exception as e:
            logger.warning("Pinecone stats fetch failed: %s", e)
            return {}

    def start_import_backfill(
        self,
        uri: str,
        integration_id: Optional[str] = None,
        error_mode: str = "CONTINUE",
    ) -> Optional[str]:
        """
        Optional large-scale backfill path (preferred over per-record upsert at scale).
        """
        try:
            resp = self.index.start_import(
                uri=uri,
                integration_id=integration_id,
                error_mode=error_mode,
            )
            import_id = getattr(resp, "id", None)
            return str(import_id) if import_id else None
        except Exception as e:
            logger.warning("Pinecone start_import failed: %s", e)
            return None


def get_pinecone_service() -> PineconeService:
    return PineconeService()


pinecone_service = get_pinecone_service()

upsert_query = pinecone_service.upsert_query
search_user_queries = pinecone_service.search_user_queries
get_user_all_queries = pinecone_service.get_user_all_queries
delete_user_query = pinecone_service.delete_user_query
delete_user_all_queries = pinecone_service.delete_user_all_queries
get_index_stats = pinecone_service.get_index_stats
start_import_backfill = pinecone_service.start_import_backfill
