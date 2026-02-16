# app/tools/web/search.py
"""
Web Search Tool

Matches tool_registry.json:
{
  "tool_name": "web_search",
  "params_schema": {
    "query": {"type": "string", "required": true},
    "max_results": {"type": "integer", "required": false, "default": 10}
  },
  "output_schema": {
    "success": {"type": "boolean"},
    "data": {
      "query": {"type": "string"},
      "results": {
        "type": "array",
        "items": {
          "title":            {"type": "string"},
          "url":              {"type": "string"},
          "snippet":          {"type": "string"},
          "favicon": {
            "google":     {"type": "string", "description": "32px favicon via Google CDN"},
            "duckduckgo": {"type": "string", "description": "16px favicon via DDG CDN"}
          },
          "_relevance_score": {"type": "number", "description": "Internal ranking score"}
        }
      },
      "total_results": {"type": "integer"},
      "search_time_ms": {"type": "number"}
    }
  }
}
"""

import asyncio
import re
from typing import Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse

from app.agent.shared.tools.base import BaseTool, ToolOutput
from ddgs import DDGS


# ── Domain lists ──────────────────────────────────────────────────────────────

BLOCKED_DOMAINS = {
    # Chinese platforms
    "baidu.com", "zhihu.com", "weibo.com", "csdn.net",
    # Generic spam / content farms
    "answers.com", "ehow.com", "livestrong.com", "reference.com",
    "ask.com", "blurtit.com", "quora.com",        # too noisy for factual queries
    "pinterest.com", "tumblr.com",                 # image boards, rarely useful
    "slideshare.net",                              # presentations, low snippet quality
}

# Domains whose results get a score bonus — ordered by tier
TRUSTED_DOMAINS: Dict[str, float] = {
    # Tier 1 — authoritative / primary sources
    "gov": 2.0,          # any .gov TLD
    "edu": 1.8,          # any .edu TLD
    "wikipedia.org": 1.6,
    "reuters.com": 1.6,
    "apnews.com": 1.6,
    "bbc.com": 1.5,
    "bbc.co.uk": 1.5,
    "theguardian.com": 1.4,
    "nytimes.com": 1.4,
    "wsj.com": 1.4,
    "bloomberg.com": 1.4,
    "ft.com": 1.4,
    # Tier 2 — reputable specialty
    "techcrunch.com": 1.3,
    "wired.com": 1.3,
    "arstechnica.com": 1.3,
    "nature.com": 1.5,
    "sciencedirect.com": 1.5,
    "pubmed.ncbi.nlm.nih.gov": 1.8,
    "who.int": 1.8,
    "cdc.gov": 1.8,
    # Tier 3 — generally reliable
    "stackoverflow.com": 1.2,
    "github.com": 1.2,
    "medium.com": 0.9,   # slight penalty — mixed quality
}

# Patterns that indicate low-quality / fake content
SPAM_PATTERNS = re.compile(
    r"(click here|buy now|limited offer|100% free|make money|earn \$|"
    r"you won't believe|shocking|celebrit(?:y|ies)|lose weight fast|"
    r"sign up now|subscribe to|sponsored|advertisement)",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _domain_trust_score(url: str) -> float:
    """Return a trust multiplier for the domain. 1.0 = neutral."""
    domain = _domain_of(url)
    # Check exact match first
    if domain in TRUSTED_DOMAINS:
        return TRUSTED_DOMAINS[domain]
    # Check TLD (.gov / .edu)
    for tld, score in TRUSTED_DOMAINS.items():
        if domain.endswith(f".{tld}"):
            return score
    # Check if any trusted domain is a suffix (e.g. subdomain)
    for trusted, score in TRUSTED_DOMAINS.items():
        if domain == trusted or domain.endswith(f".{trusted}"):
            return score
    return 1.0


def _relevance_score(query: str, title: str, snippet: str, url: str) -> float:
    """
    Score a result 0.0–∞ based on how relevant it looks.

    Components
    ----------
    * keyword overlap   — how many query words appear in title + snippet
    * title weight      — title matches count more than snippet matches
    * snippet length    — longer, richer snippets are more trustworthy
    * domain trust      — bonus for authoritative domains
    * spam penalty      — deduct for clickbait patterns
    """
    query_words = set(re.findall(r"\w+", query.lower()))
    title_words  = set(re.findall(r"\w+", title.lower()))
    snippet_text = snippet.lower()

    # 1. Keyword hits in title (weighted 2×) and snippet
    title_hits   = len(query_words & title_words)
    snippet_hits = sum(1 for w in query_words if w in snippet_text)
    keyword_score = title_hits * 2.0 + snippet_hits * 1.0

    # Normalise by number of query words (avoid rewarding long queries unfairly)
    if query_words:
        keyword_score /= len(query_words)

    # 2. Snippet richness: reward length up to ~300 chars
    snippet_length_score = min(len(snippet), 300) / 300.0

    # 3. Domain trust multiplier
    trust = _domain_trust_score(url)

    # 4. Spam penalty
    spam_penalty = 0.5 if SPAM_PATTERNS.search(title + " " + snippet) else 0.0

    score = (keyword_score + snippet_length_score) * trust - spam_penalty
    return max(score, 0.0)


def _is_english(text: str) -> bool:
    """Reject text that contains CJK or Arabic/Hebrew script."""
    return not re.search(r"[\u0600-\u06FF\u4e00-\u9fff\u3040-\u30ff]", text)


def _is_quality_snippet(snippet: str, min_length: int = 40) -> bool:
    """A snippet must be long enough and not pure punctuation/numbers."""
    if len(snippet.strip()) < min_length:
        return False
    # Must contain at least a few real words
    words = re.findall(r"[a-zA-Z]{3,}", snippet)
    return len(words) >= 5


def _favicon_urls(url: str) -> Dict[str, str]:
    """
    Return favicon URLs for a given page URL — zero extra HTTP calls.

    We expose two CDN sources so the caller can fall back if one fails:

    • google  — https://www.google.com/s2/favicons?domain=<domain>&sz=<size>
                 Reliable, supports ?sz= for 16/32/64 px.  Requires internet
                 access to Google (fine for server-side use).

    • duckduckgo — https://icons.duckduckgo.com/ip3/<domain>.ico
                   Cached by DDG, always 16 px.  Good privacy-friendly fallback.

    Both are constructed purely from the domain — no async/await needed.
    """
    domain = _domain_of(url)
    if not domain:
        return {"google": "", "duckduckgo": ""}

    return {
        # 32 px is a nice default for UI cards; change sz= to 16 or 64 as needed
        "google":     f"https://www.google.com/s2/favicons?domain={domain}&sz=32",
        "duckduckgo": f"https://icons.duckduckgo.com/ip3/{domain}.ico",
    }


# ── Main Tool ─────────────────────────────────────────────────────────────────

class WebSearchTool(BaseTool):
    """
    Web search tool backed by DuckDuckGo with relevance scoring.

    Improvements over v1
    --------------------
    * Multi-pass candidate fetching  — fetch 5× limit, score, keep best
    * Relevance scoring              — keyword overlap + snippet richness + domain trust
    * Spam / clickbait detection     — regex-based penalty
    * Snippet quality gate           — minimum length + word count
    * Domain blocklist / trustlist   — expanded and tiered
    * Deduplication                  — no two results from the same domain
    * Retry on empty                 — broadens query if first pass returns nothing
    """

    def get_tool_name(self) -> str:
        return "web_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = inputs.get("query", "").strip()
        max_results = int(inputs.get("max_results", 10))

        print("inputs: inside search.py", inputs)

        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")

        self.logger.info(f"Searching: '{query}' (max: {max_results})")

        t0 = datetime.now()
        results = await self._fetch_and_rank(query, max_results)

        # Retry with a broader query if we got very few results
        if len(results) < max(1, max_results // 2):
            broad_query = self._broaden_query(query)
            if broad_query != query:
                self.logger.info(f"Too few results; retrying with: '{broad_query}'")
                extra = await self._fetch_and_rank(broad_query, max_results)
                # Merge, deduplicate by URL
                seen_urls = {r["url"] for r in results}
                for r in extra:
                    if r["url"] not in seen_urls:
                        results.append(r)
                        seen_urls.add(r["url"])
                results = results[:max_results]

        search_time_ms = (datetime.now() - t0).total_seconds() * 1000

        return ToolOutput(
            success=True,
            data={
                "query": query,
                "results": results,
                "total_results": len(results),
                "search_time_ms": search_time_ms,
            },
            error=None,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_and_rank(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Fetch candidates from DDGS, filter, score, and return top `limit`."""
        candidates = await asyncio.get_event_loop().run_in_executor(
            None, self._ddgs_search, query, limit * 5   # over-fetch for filtering
        )

        scored: List[tuple[float, Dict]] = []
        seen_domains: set[str] = set()

        for item in candidates:
            title   = item.get("title", "")
            snippet = item.get("snippet", "")
            url     = item.get("url", "")
            domain  = _domain_of(url)

            # ── Hard filters ──────────────────────────────────────
            if not url.startswith("http"):
                continue
            if any(blocked in domain for blocked in BLOCKED_DOMAINS):
                continue
            if not _is_english(title + snippet):
                continue
            if not _is_quality_snippet(snippet):
                continue

            # ── One result per domain (avoids 5 results from one site) ──
            if domain in seen_domains:
                continue
            seen_domains.add(domain)

            # ── Score ─────────────────────────────────────────────
            score = _relevance_score(query, title, snippet, url)
            scored.append((score, item))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        # Attach score metadata + favicon and return top results
        results = []
        for score, item in scored[:limit]:
            item["_relevance_score"] = round(score, 3)  # debug / logging only
            item["favicon"] = _favicon_urls(item.get("url", ""))
            results.append(item)

        return results

    def _ddgs_search(self, query: str, fetch_limit: int) -> List[Dict[str, Any]]:
        """Synchronous DuckDuckGo fetch (runs in executor thread)."""
        raw: List[Dict[str, Any]] = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(
                    query,
                    max_results=fetch_limit,
                    region="us-en",
                    safesearch="moderate",  # was "low" — raised to cut spam
                ):
                    raw.append({
                        "title":   r.get("title", ""),
                        "url":     r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
        except Exception as exc:
            self.logger.warning(f"DDGS error: {exc}")
        return raw

    @staticmethod
    def _broaden_query(query: str) -> str:
        """
        Simple heuristic: remove the last word to broaden scope.
        E.g. "python async event loop tutorial 2024" → "python async event loop tutorial"
        """
        words = query.split()
        return " ".join(words[:-1]) if len(words) > 2 else query

    # ── Legacy helpers (kept for compatibility) ───────────────────────────────

    def _looks_english(self, text: str) -> bool:
        return _is_english(text)

    def _format_results(self, query: str, results: list) -> str:
        lines = [f"Search Results for: '{query}'", "=" * 60, ""]
        for i, result in enumerate(results, 1):
            lines.append(f"{i}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            lines.append(f"   {result['snippet']}")
            if "price" in result:
                lines.append(f"   Price: {result['price']}")
            lines.append("")
        lines.append(f"Total results: {len(results)}")
        lines.append(f"Searched at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)