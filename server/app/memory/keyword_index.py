"""
Keyword Memory Index — TRUE zero-latency past recall.

Instead of embedding + vector search (80-200ms), this maintains a
pre-built keyword → messages index that resolves in <2ms.

How it works:
1. Every message stored gets its keywords extracted and indexed
2. On query, extract keywords → instant hash lookup → return matching messages
3. No embedding model needed, no vector math, pure dict lookup

This runs IN ADDITION to RAG (not replacing it). RAG handles semantic
similarity ("things that mean the same"). This handles exact recall
("did I mention X?", "what did I say about Y?").
"""

import logging
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

# Stop words to skip during indexing
_STOP_WORDS = frozenset({
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "this", "that", "is", "am", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall",
    "can", "a", "an", "the", "and", "but", "or", "if", "then",
    "so", "no", "not", "of", "in", "on", "at", "to", "for", "with",
    "from", "by", "about", "as", "into", "through", "during", "before",
    "after", "above", "below", "up", "down", "out", "off", "over",
    "under", "again", "further", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "than", "too", "very",
    "just", "also", "now", "well", "like", "what", "which", "who",
    "whom", "its", "let", "say", "said", "something", "thing",
    "want", "need", "going", "go", "get", "got", "make", "know",
    "think", "see", "come", "take", "give", "tell", "ask", "use",
    "find", "put", "try", "leave", "call", "keep", "still", "even",
    "back", "only", "way", "new", "one", "two", "much", "many",
    "sir", "okay", "ok", "yes", "yeah", "hey", "hi", "hello",
    "thanks", "thank", "please", "right", "good", "great", "sure",
    "spark", "hmm", "um", "uh", "oh",
})

_WORD_RE = re.compile(r"[a-zA-Z0-9]+", re.UNICODE)

# Max messages to keep in index per user
_MAX_INDEXED_MESSAGES = 500


class KeywordMemoryIndex:
    """
    In-memory keyword index for instant message recall.

    Structure:
        _index[user_id][keyword] = [(message_content, timestamp, role), ...]
        _messages[user_id] = [(content, timestamp, role), ...]  # ordered

    Lookup is O(1) dict access — effectively 0ms.
    """

    _instance: Optional["KeywordMemoryIndex"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._index: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
            cls._instance._messages: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
            cls._instance._loaded_users: Set[str] = set()
        return cls._instance

    # ── Index a message (called on every add_message) ────────────────────

    def index_message(self, user_id: str, role: str, content: str, timestamp: str = "") -> None:
        """Index a single message. Call this whenever a message is stored."""
        if not content or not content.strip():
            return

        if not timestamp:
            timestamp = datetime.now(NEPAL_TZ).isoformat()

        entry = (content, timestamp, role)
        self._messages[user_id].append(entry)

        # Trim if too many
        if len(self._messages[user_id]) > _MAX_INDEXED_MESSAGES:
            removed = self._messages[user_id][:-_MAX_INDEXED_MESSAGES]
            self._messages[user_id] = self._messages[user_id][-_MAX_INDEXED_MESSAGES:]
            # Remove old entries from keyword index
            removed_set = set(removed)
            for keyword, entries in self._index[user_id].items():
                self._index[user_id][keyword] = [e for e in entries if e not in removed_set]

        # Extract and index keywords
        keywords = self._extract_keywords(content)
        for kw in keywords:
            self._index[user_id][kw].append(entry)

    # ── Search (the fast path — <2ms) ────────────────────────────────────

    def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Instant keyword search. Returns matching messages sorted by relevance.
        This is the 0ms path — no embedding, no vector math.
        """
        if user_id not in self._index:
            return []

        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            return []

        # Score messages by keyword overlap
        scores: Dict[int, Tuple[float, Tuple[str, str, str]]] = {}
        user_index = self._index[user_id]

        for kw in query_keywords:
            if kw in user_index:
                for entry in user_index[kw]:
                    entry_id = id(entry)
                    if entry_id in scores:
                        old_score, _ = scores[entry_id]
                        scores[entry_id] = (old_score + 1.0, entry)
                    else:
                        scores[entry_id] = (1.0, entry)

        if not scores:
            return []

        # Sort by score (most keyword matches first), then recency
        ranked = sorted(scores.values(), key=lambda x: x[0], reverse=True)

        results = []
        for score, (content, timestamp, role) in ranked[:limit]:
            results.append({
                "content": content,
                "timestamp": timestamp,
                "role": role,
                "score": round(score / len(query_keywords), 4),
                "_source": "keyword_index",
            })

        return results

    # ── Bulk load from existing messages (on first access) ───────────────

    async def ensure_loaded(self, user_id: str) -> None:
        """Load existing messages into the index if not already done."""
        if user_id in self._loaded_users:
            return

        try:
            from app.cache import get_last_n_messages
            messages = await get_last_n_messages(user_id, n=_MAX_INDEXED_MESSAGES)
            for msg in messages:
                content = str(msg.get("content", "")).strip()
                role = str(msg.get("role", "user"))
                timestamp = str(msg.get("timestamp", ""))
                if content:
                    self.index_message(user_id, role, content, timestamp)
            self._loaded_users.add(user_id)
            logger.info("📇 Keyword index loaded %d messages for %s", len(messages), user_id)
        except Exception as e:
            logger.debug("Keyword index load failed: %s", e)

    # ── Keyword extraction ───────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> Set[str]:
        """Extract meaningful keywords from text."""
        words = _WORD_RE.findall(text.lower())
        return {w for w in words if w not in _STOP_WORDS and len(w) >= 3}

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self, user_id: str) -> Dict[str, int]:
        return {
            "indexed_messages": len(self._messages.get(user_id, [])),
            "unique_keywords": len(self._index.get(user_id, {})),
        }


def get_keyword_index() -> KeywordMemoryIndex:
    return KeywordMemoryIndex()
