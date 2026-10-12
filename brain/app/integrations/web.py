"""Web tools (REDESIGN §22.2, R4): web_search through SearXNG, web_fetch with our own fetcher
(only the passages about the question come back, never whole pages), weather from Open-Meteo.
Free, no keys. What pages say is data for the model, never instructions (the agent prompt)."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.tools.spec import Risk, ToolError, ToolSpec

RESULTS = 8
PAGE_BYTES = 2_000_000  # read no further into a page
PAGE_CHARS = 3000  # web_fetch's answer: Groq's free tier is 8K tokens a minute (§21)
PASSAGE_CHARS = 500
EMBED = 40  # passages the local model ranks (~35 ms each on this laptop); words pick them
# honest: Wikipedia 403s a browser UA from a non-browser client
UA = "Spark/2.0 (+https://github.com/chromoverse/spark.ai)"
GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebSearch(_In):
    query: str = Field(max_length=300, description="What to look up, the way you'd type it")
    news: bool = Field(default=False, description="News articles instead of web pages")
    recent: Literal["day", "week", "month", "year"] | None = Field(
        default=None, description="Only results from the last day, week, month, or year"
    )


class WebFetch(_In):
    url: str = Field(max_length=2000, description="An http(s) link from web_search or the user")
    question: str = Field(
        max_length=300, description="What you want from the page: only passages about it return"
    )


class Weather(_In):
    place: str = Field(
        max_length=100, description="A city or town, e.g. 'Pokhara' or 'Springfield, Illinois'"
    )


async def web_search(call: Any, inp: dict[str, Any]) -> str:
    params = {
        "q": inp["query"],
        "format": "json",
        "categories": "news" if inp.get("news") else "general",
    }
    if inp.get("recent"):
        params["time_range"] = inp["recent"]
    try:
        r = await call.rt.http.get(
            f"{call.rt.settings.searxng_url}/search", params=params, timeout=8
        )
        r.raise_for_status()
        found = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolError("unavailable", "Web search isn't reachable right now. Say so.") from exc
    lines = [f"Answer: {a}" for a in found.get("answers", [])[:2] if isinstance(a, str)]
    seen: set[str] = set()
    for x in found.get("results", []):
        url = x.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        date = (x.get("publishedDate") or "")[:10]
        title = " ".join((x.get("title") or "").split()) + (f" ({date})" if date else "")
        lines.append(
            f"{len(seen)}. {title}\n   {url}\n   {' '.join(x.get('content', '').split())[:300]}"
        )
        if len(seen) == RESULTS:
            break
    return "\n".join(lines) or "No results. Say nothing was found; never make results up."


def _addresses(host: str) -> list[str]:
    return [str(a[4][0]) for a in socket.getaddrinfo(host, None)]


def _check_public(host: str) -> None:
    """The brain sits next to Postgres, Redis, and the user's network: a link from a page (or a
    prompt injection) must not reach them."""
    try:
        addrs = _addresses(host)
    except OSError as exc:
        raise ToolError("not_found", f"Couldn't find {host}.") from exc
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ToolError(
                "blocked", "That's a private network address; I only read public pages."
            )


async def _download(http: httpx.AsyncClient, url: str) -> tuple[str, str, bool]:
    """(final url, text, is html). Redirects are followed by hand so each hop is checked."""
    # ponytail: checks DNS, then httpx resolves again (DNS rebinding can slip between the two);
    # pin the checked IP in a custom transport if the brain ever runs where that matters
    for _ in range(5):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ToolError("bad_url", "Only http(s) links.")
        await asyncio.to_thread(_check_public, parts.hostname)
        try:
            async with http.stream(
                "GET", url, headers={"User-Agent": UA}, timeout=10, follow_redirects=False
            ) as r:
                if r.is_redirect and "location" in r.headers:
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise ToolError("http", f"The page answered {r.status_code}.")
                kind = r.headers.get("content-type", "")
                if "html" not in kind and "text/plain" not in kind:
                    raise ToolError("not_text", f"That link is {kind or 'not a page'}.")
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > PAGE_BYTES:
                        break
                text = body.decode(r.charset_encoding or "utf-8", errors="replace")
                return url, text, "html" in kind
        except httpx.HTTPError as exc:
            raise ToolError("unreachable", "Couldn't load that page.") from exc
    raise ToolError("redirects", "That link redirects too many times.")


class _Text(HTMLParser):
    """Readable text, one block per line; scripts, menus, headers, and footers dropped."""

    SKIP = frozenset(
        "script style noscript nav header footer aside form svg button select template "
        "iframe".split()
    )
    BLOCK = frozenset(
        "p div li h1 h2 h3 h4 h5 h6 br tr td th section article pre blockquote dd dt".split()
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def _passages(text: str) -> list[str]:
    """Lines of 6+ words (menus and buttons are shorter), packed into ~PASSAGE_CHARS chunks."""
    out: list[str] = []
    cur = ""
    for line in text.split("\n"):
        line = " ".join(line.split())
        if len(line.split()) < 6:
            continue
        if cur and len(cur) + len(line) > PASSAGE_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur} {line}".strip()[: PASSAGE_CHARS * 2]
    return [*out, cur] if cur else out


async def _rank(rt: Any, question: str, passages: list[str]) -> list[int]:
    """Passage indexes, best first: shared words pick EMBED candidates (earlier ones win ties),
    then the local model orders those; words alone while it's off."""
    words = set(re.findall(r"\w{3,}", question.lower()))
    shared = [len(words & set(re.findall(r"\w{3,}", p.lower()))) for p in passages]
    by_words = sorted(range(len(passages)), key=lambda i: -shared[i])
    top = by_words[:EMBED]
    q = await rt.embedder.embed([question], query=True)
    ps = await rt.embedder.embed([passages[i] for i in top], query=False) if q else None
    if not (q and ps):
        return by_words
    scores = np.asarray(ps) @ np.asarray(q[0])  # unit vectors: dot = cosine
    return [top[i] for i in np.argsort(-scores, kind="stable")]


async def web_fetch(call: Any, inp: dict[str, Any]) -> str:
    url, raw, is_html = await _download(call.rt.http, inp["url"])
    title = ""
    if is_html:
        parser = _Text()
        parser.feed(raw)
        title, raw = " ".join(parser.title.split()), "".join(parser.out)
    passages = _passages(raw)
    if not passages:
        return f"{url}: no readable text (it may need a browser). Don't guess what it says."
    keep: list[int] = []
    size = 0
    for i in await _rank(call.rt, inp["question"], passages):
        if size + len(passages[i]) > PAGE_CHARS:
            break
        keep.append(i)
        size += len(passages[i])
    body = "\n…\n".join(passages[i] for i in sorted(keep))  # page order reads better
    return f"{title}\n{url}\n\n{body}".strip()


_SKY = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle",
    57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorms", 96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}  # fmt: skip


async def weather(call: Any, inp: dict[str, Any]) -> str:
    # ponytail: Open-Meteo is free for non-commercial use; production needs its plan or met.no
    name, _, region = (s.strip() for s in inp["place"].partition(","))
    http = call.rt.http
    try:
        g = await http.get(GEO, params={"name": name, "count": 5}, timeout=6)
        g.raise_for_status()
        hits = g.json().get("results") or []
        if not hits:
            raise ToolError("not_found", f"No place called {inp['place']}. Ask which one.")
        region = region.lower()
        p = next(
            (
                h
                for h in hits
                if region and region in f"{h.get('admin1')} {h.get('country')}".lower()
            ),
            hits[0],
        )
        f = await http.get(
            FORECAST,
            params={
                "latitude": p["latitude"],
                "longitude": p["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 3,
            },
            timeout=6,
        )
        f.raise_for_status()
        w = f.json()
        c, d = w["current"], w["daily"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise ToolError("unavailable", "The weather service isn't reachable right now.") from exc
    place = ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country")) if x)
    lines = [
        f"{place}, now ({c['time'].replace('T', ' ')} local): "
        f"{_SKY.get(c['weather_code'], 'unknown sky')}, {c['temperature_2m']}°C "
        f"(feels like {c['apparent_temperature']}°C), humidity {c['relative_humidity_2m']}%, "
        f"wind {c['wind_speed_10m']} km/h."
    ]
    for i, day in enumerate(d["time"]):
        rain = d["precipitation_probability_max"][i]
        lines.append(
            f"{day}: {_SKY.get(d['weather_code'][i], 'unknown sky')}, "
            f"{d['temperature_2m_min'][i]} to {d['temperature_2m_max'][i]}°C"
            + (f", {rain}% chance of rain." if rain is not None else ".")
        )
    return "\n".join(lines)


WEB_SEARCH = ToolSpec(
    "web_search",
    "Searches the web (news=true for news). Returns titles, links, and snippets; web_fetch a link "
    "when the snippet isn't enough.",
    WebSearch,
    "brain",
    Risk.READ,
    timeout_s=10.0,
    keywords="web internet online google search look up latest news current today price score "
    "who won results",
    handler=web_search,
)
WEB_FETCH = ToolSpec(
    "web_fetch",
    "Reads a web page and returns the passages about your question.",
    WebFetch,
    "brain",
    Risk.READ,
    timeout_s=15.0,
    keywords="web page link url website article read",
    handler=web_fetch,
)
WEATHER = ToolSpec(
    "weather",
    "Current weather and a 3-day forecast for a place. If the user didn't say where, use where "
    "they live if you know it; ask only if you don't.",
    Weather,
    "brain",
    Risk.READ,
    timeout_s=10.0,
    keywords="weather forecast temperature rain sunny cold hot umbrella",
    handler=weather,
)
WEB_TOOLS = (WEB_SEARCH, WEB_FETCH, WEATHER)
