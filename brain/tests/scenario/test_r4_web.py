"""R4 web tools (TESTING.md §4.13): web_search through SearXNG, web_fetch (private addresses
blocked, only the passages about the question), weather from Open-Meteo. No real network: every
host is a FakeHttp handler. # proves §22.2"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from app.db.models import JobStep
from app.integrations import web
from app.tools.spec import ToolError
from tests.conftest import Brain
from tests.fakes.device import FakeDevice
from tests.fakes.llm import Turn
from tests.scenario.test_r2_agent import delegate, rows, spoken, tool, updates

pytestmark = pytest.mark.scenario

FOUND = {
    "answers": [],
    "results": [
        {
            "url": "https://news.example/floods",
            "title": "Floods  in Gorkha",
            "content": "Over 100 trekkers   stranded.",
            "publishedDate": "2026-10-12T08:00:00",
        },
        {"url": "https://news.example/floods", "title": "Same link again", "content": "dup"},
        {
            "url": "https://other.example/rescue",
            "title": "Rescue goes on",
            "content": "Hundreds out.",
        },
    ],
}
GEO = {
    "results": [
        {"name": "Pokhara", "latitude": 28.2, "longitude": 83.9, "country": "Nepal"},
    ]
}
FORECAST = {
    "current": {
        "time": "2026-10-12T22:15",
        "temperature_2m": 19.4,
        "apparent_temperature": 19.0,
        "relative_humidity_2m": 80,
        "weather_code": 61,
        "wind_speed_10m": 3.2,
    },
    "daily": {
        "time": ["2026-10-12", "2026-10-13", "2026-10-14"],
        "weather_code": [61, 2, 0],
        "temperature_2m_min": [16.1, 15.8, 15.0],
        "temperature_2m_max": [24.0, 25.1, 26.3],
        "precipitation_probability_max": [70, 20, None],
    },
}


@pytest.fixture
async def laptop(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Laptop"))
    await d.connect()
    await d.hello(capabilities=["apps", "files"])
    yield d
    await d.close()


@pytest.fixture
def public(monkeypatch: pytest.MonkeyPatch) -> None:
    """news.example resolves to a public address; IP literals and localhost resolve for real."""
    real = web._addresses
    monkeypatch.setattr(
        web, "_addresses", lambda h: ["93.184.216.34"] if h.endswith(".example") else real(h)
    )


def call(brain: Brain) -> Any:
    return SimpleNamespace(rt=brain.rt, user_id=None, job_id=None)


def host(brain: Brain, name: str, answer: Callable[[httpx.Request], httpx.Response]) -> list[Any]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request)

    brain.fake_http.hosts[name] = handle
    return seen


def searxng(brain: Brain, answer: Callable[[httpx.Request], httpx.Response]) -> list[Any]:
    return host(brain, urlsplit(brain.rt.settings.searxng_url).hostname or "", answer)


async def test_w1_news_search_lists_each_link_once(brain: Brain) -> None:
    seen = searxng(brain, lambda _: httpx.Response(200, json=FOUND))
    out = await web.web_search(
        call(brain), {"query": "Nepal floods", "news": True, "recent": "day"}
    )
    params = seen[0].url.params
    assert (params["q"], params["format"], params["categories"], params["time_range"]) == (
        "Nepal floods",
        "json",
        "news",
        "day",
    )
    assert out.count("https://news.example/floods") == 1
    assert "1. Floods in Gorkha (2026-10-12)" in out and "Over 100 trekkers stranded." in out
    assert "2. Rescue goes on" in out


async def test_w2_search_down_or_empty_never_invents(brain: Brain) -> None:
    """PHASES R4: empty tool output → the model is told nothing was found, never to make it up."""
    searxng(brain, lambda _: httpx.Response(502))
    with pytest.raises(ToolError, match="isn't reachable"):
        await web.web_search(call(brain), {"query": "anything"})
    searxng(brain, lambda _: httpx.Response(200, json={"results": []}))
    out = await web.web_search(call(brain), {"query": "anything"})
    assert out.startswith("No results") and "never make results up" in out


@pytest.mark.usefixtures("public")
async def test_w3_fetch_never_reaches_private_addresses(brain: Brain) -> None:
    """The brain shares a network with Postgres, Redis, and the user's LAN: a link (or a prompt
    injection) can't make it fetch them, directly or through a redirect."""
    for url in (
        "http://127.0.0.1:8888/",
        "http://localhost:5432/",
        "http://10.0.0.5/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
    ):
        with pytest.raises(ToolError):
            await web.web_fetch(call(brain), {"url": url, "question": "x"})
    hops = host(
        brain,
        "news.example",
        lambda _: httpx.Response(302, headers={"location": "http://169.254.169.254/"}),
    )
    with pytest.raises(ToolError, match="private network"):
        await web.web_fetch(call(brain), {"url": "https://news.example/a", "question": "x"})
    assert len(hops) == 1  # FakeHttp would have failed on any call to the private address


@pytest.mark.usefixtures("public")
async def test_w4_fetch_returns_only_passages_about_the_question(brain: Brain) -> None:
    filler = "".join(
        f"<p>Paragraph {i} talks about mountain tourism, local food, and festival dates.</p>"
        for i in range(150)
    )
    page = (
        "<html><head><title>Floods in Gorkha</title><script>var trekkers = 'stranded';</script>"
        "</head><body><nav>Home News Sport Weather Login Subscribe Today Menu</nav>"
        f"{filler}<p>Officials said 112 trekkers are stranded near the Budhi Gandaki river.</p>"
        f"{filler}<footer>Copyright footer text with many words in it here</footer></body></html>"
    )
    host(
        brain,
        "news.example",
        lambda _: httpx.Response(200, headers={"content-type": "text/html"}, text=page),
    )
    out = await web.web_fetch(
        call(brain), {"url": "https://news.example/a", "question": "how many trekkers stranded"}
    )
    assert out.startswith("Floods in Gorkha\nhttps://news.example/a")
    assert "112 trekkers are stranded" in out
    assert "var trekkers" not in out and "Subscribe" not in out and "Copyright" not in out
    assert len(out) < len(page) // 4
    host(
        brain,
        "news.example",
        lambda _: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"),
    )
    with pytest.raises(ToolError, match="application/pdf"):
        await web.web_fetch(call(brain), {"url": "https://news.example/a.pdf", "question": "x"})


async def test_w5_weather_asked_by_voice_is_answered_from_the_forecast(
    brain: Brain, laptop: FakeDevice
) -> None:
    """The owner's R3 try: "what's the weather" got "I can't". Now the job fetches Open-Meteo and
    the reply comes from what it returned."""
    geo = host(brain, "geocoding-api.open-meteo.com", lambda _: httpx.Response(200, json=GEO))
    host(brain, "api.open-meteo.com", lambda _: httpx.Response(200, json=FORECAST))
    assert brain.groq is not None
    brain.groq.queue(delegate("What's the weather in Pokhara today?"))
    brain.groq.queue(
        Turn(tool_calls=[tool("weather", place="Pokhara")]),
        Turn(text=["Light rain in Pokhara, 19 degrees, 70% chance of rain today."]),
        model="agent",
    )
    sid, _ = await laptop.say("what's the weather in pokhara")
    await laptop.reply(sid)
    await updates(laptop)
    assert spoken(await laptop.reply(sid)) == [
        "Light rain in Pokhara, 19 degrees, 70% chance of rain today."
    ]
    assert geo[0].url.params["name"] == "Pokhara"
    [step] = await rows(brain, JobStep)
    assert (step.tool, step.status) == ("weather", "ok")
    sent = json.dumps(brain.groq.for_model("agent")[-1]["messages"])
    assert "Pokhara, Nepal, now (2026-10-12 22:15 local): light rain, 19.4" in sent
    assert "70% chance of rain" in sent and "2026-10-14: clear, 15.0 to 26.3" in sent
