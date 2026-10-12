"""R3 memory over the real gateway (TESTING.md §4.12, PHASES R3 acceptance).
# proves §8, §21 (memory, prompt layout)"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Memory
from app.llm.chains import CHAINS, Entry
from app.memory import extract, store
from tests.conftest import TEST_DB, Brain
from tests.fakes.device import FakeDevice
from tests.fakes.embed import FakeEmbedder
from tests.fakes.llm import Turn

pytestmark = pytest.mark.scenario

DAY = 86400.0


class Laptop(FakeDevice):
    user_id: uuid.UUID


@pytest.fixture
async def laptop(brain: Brain, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Laptop]:
    monkeypatch.setitem(CHAINS, "memory", [Entry("groq", "memory")])
    tokens = await brain.sign_in("asha@example.com", "Laptop")
    d = Laptop(brain.url, tokens)
    d.user_id = uuid.UUID(tokens["user"]["id"])
    await d.connect()
    await d.hello(capabilities=["apps", "volume", "media", "brightness", "files"])
    yield d
    await d.close()


def learned(*memories: dict[str, Any]) -> Turn:
    return Turn(text=[json.dumps({"memories": list(memories)})])


def tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"name": name, "arguments": arguments}


async def saved(brain: Brain, count: int | None = None) -> list[Memory]:
    """Memory rows, oldest first; with `count`, waits for that many (extraction runs after the
    turn)."""
    rows: list[Memory] = []
    for _ in range(300):
        async with brain.rt.db() as db:
            rows = list((await db.scalars(select(Memory).order_by(Memory.created_at))).all())
        if count is None or len(rows) >= count:
            return rows
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} memories, have {len(rows)}")


async def turn(dev: FakeDevice, text: str) -> list[str]:
    sid, _ = await dev.say(text)
    return [d["text"] for d in await dev.reply(sid) if d["speak"]]


def prompt(brain: Brain, i: int) -> list[dict[str, Any]]:
    assert brain.groq is not None
    msgs: list[dict[str, Any]] = brain.groq.for_model("fast")[i]["messages"]
    return msgs


async def test_m1_sister_is_asha_then_call_my_sister_the_next_day(
    brain: Brain, laptop: Laptop
) -> None:
    """PHASES R3: "My sister is Asha" → the next day "call my sister" resolves Asha."""
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Nice, Asha it is."]), model="fast")
    brain.groq.queue(
        learned({"kind": "person", "text": "The user's sister is Asha.", "importance": 0.9}),
        model="memory",
    )
    assert await turn(laptop, "My sister is Asha") == ["Nice, Asha it is."]
    [m] = await saved(brain, 1)
    assert (m.kind, m.text, m.confirmed) == ("person", "The user's sister is Asha.", True)
    assert m.importance == pytest.approx(0.9) and m.expires_at is None
    assert m.source_message_id is not None  # the user's line it came from
    asked = brain.groq.for_model("memory")[0]["messages"][-1]["content"]
    assert "User: My sister is Asha" in asked and "Spark: Nice, Asha it is." in asked

    brain.clock.advance(DAY)  # a new thread: yesterday's turns aren't in the history
    brain.groq.queue(Turn(text=["I can't place calls yet. Text Asha instead?"]), model="fast")
    await turn(laptop, "call my sister")
    msgs = prompt(brain, 1)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"].endswith("What you know about the user: The user's sister is Asha.")


async def test_m2_found_memories_ride_in_the_note_not_the_system_prompt(
    brain: Brain, laptop: Laptop
) -> None:
    """Hybrid retrieval per line: what the profile doesn't hold comes in the volatile note."""
    assert brain.groq is not None
    for i in range(80):  # important memories fill the profile (≤ 1200 characters)
        await store.save(brain.rt, laptop.user_id, f"The user likes topic{i}.", "preference", 0.9)
    await store.save(brain.rt, laptop.user_id, "The user's dentist is Dr Rai.", "person", 0.3)
    brain.groq.queue(Turn(text=["Sure."]), model="fast")
    await turn(laptop, "book my dentist for friday")
    msgs = prompt(brain, 0)
    assert len(msgs[0]["content"].split("What you know about the user: ")[1]) <= 1200
    assert "Dr Rai" not in msgs[0]["content"]
    assert "remembered: The user's dentist is Dr Rai." in msgs[-1]["content"]


async def test_m3_forget_by_voice_and_it_never_resurfaces(brain: Brain, laptop: Laptop) -> None:
    """PHASES R3: forget removes the memory and its embedding; it never comes back."""
    assert brain.groq is not None
    await store.save(brain.rt, laptop.user_id, "The user's sister is Asha.", "person", 0.9)
    await store.save(brain.rt, laptop.user_id, "The user likes jazz.", "preference", 0.6)
    brain.groq.queue(
        Turn(text=["Done, forgotten."], tool_calls=[tool("forget", what="sister Asha")]),
        Turn(text=["You haven't told me."]),
        model="fast",
    )
    assert await turn(laptop, "forget that my sister is Asha") == ["Done, forgotten."]
    [left] = await saved(brain)
    assert left.text == "The user likes jazz."
    assert not brain.groq.for_model("memory")  # a memory tool ran: no extraction call

    await turn(laptop, "who is my sister Asha")
    msgs = prompt(brain, 1)
    assert "Asha" not in msgs[0]["content"] and "remembered" not in msgs[-1]["content"]
    assert [f.text for f in await store.search(brain.rt, laptop.user_id, "Asha sister")] == []


async def test_m3_forgetting_something_unknown_is_said(brain: Brain, laptop: Laptop) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(text=["Forgotten."], tool_calls=[tool("forget", what="my cat")]), model="fast"
    )
    said = await turn(laptop, "forget about my cat")
    assert said == ["Forgotten.", "Actually, I didn't have anything like that saved."]


async def test_m4_remember_by_voice_is_saved_at_once(brain: Brain, laptop: Laptop) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["Got it."],
            tool_calls=[tool("remember", text="The user parks on level 3.", kind="routine")],
        ),
        model="fast",
    )
    assert await turn(laptop, "remember that I parked on level 3") == ["Got it."]
    [m] = await saved(brain, 1)
    assert (m.text, m.kind, m.confirmed) == ("The user parks on level 3.", "routine", True)
    assert not brain.groq.for_model("memory")

    # offered only when the line is about remembering: always listed, they cost file delegations
    brain.groq.queue(Turn(text=["Sure."]), model="fast")
    await turn(laptop, "delete everything in my downloads")
    offered = [{t["function"]["name"] for t in r["tools"]} for r in brain.groq.for_model("fast")]
    assert {"remember", "forget"} <= offered[0] and not {"remember", "forget"} & offered[1]


async def test_m5_a_correction_replaces_the_old_fact(brain: Brain, laptop: Laptop) -> None:
    assert brain.groq is not None
    await store.save(brain.rt, laptop.user_id, "The user lives in Kathmandu.", "fact", 0.6)
    brain.groq.queue(Turn(text=["Pokhara, nice."]), model="fast")
    brain.groq.queue(
        learned(
            {
                "kind": "correction",
                "text": "The user lives in Pokhara.",
                "importance": 0.6,
                "replaces": 1,
            }
        ),
        model="memory",
    )
    await turn(laptop, "I moved to Pokhara last month, I live there now")
    for _ in range(300):
        [m] = await saved(brain)
        if "Pokhara" in m.text:
            break
        await asyncio.sleep(0.01)
    assert (m.text, m.kind) == ("The user lives in Pokhara.", "correction")
    asked = brain.groq.for_model("memory")[0]["messages"][-1]["content"]
    assert "Known memories:\n1. The user lives in Kathmandu." in asked


async def test_m6_commands_and_questions_cost_no_extraction(brain: Brain, laptop: Laptop) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["About 384,000 kilometres."]), model="fast")
    await turn(laptop, "how far is the moon")
    await asyncio.sleep(0.05)
    assert not brain.groq.for_model("memory")
    assert extract.personal("I'm allergic to peanuts") and extract.personal("my wife is Priya")
    assert not extract.personal("volume to 30") and not extract.personal("open spotify")


async def test_m7_what_the_agent_saves_waits_for_the_users_ok(brain: Brain, laptop: Laptop) -> None:
    """§21 governance: the agent may have read it in a file or a page, so it stays out of every
    prompt until the user confirms it on the Memory page."""
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["On it."],
            tool_calls=[tool("delegate", task="Remember the wifi password note", ack="On it.")],
        ),
        model="fast",
    )
    brain.groq.queue(
        Turn(tool_calls=[tool("remember", text="The user's wifi is called Lotus.")]),
        Turn(text=["Saved it for you to confirm."]),
        model="agent",
    )
    await turn(laptop, "remember what my wifi is called from that note")
    [m] = await saved(brain, 1)
    assert m.confirmed is False
    assert await store.profile(brain.rt, laptop.user_id) == []
    assert await store.search(brain.rt, laptop.user_id, "wifi Lotus") == []

    r = await brain.client.patch(
        f"/v2/memories/{m.id}",
        json={"confirmed": True},
        headers={"Authorization": f"Bearer {laptop.access_token}"},
    )
    assert r.status_code == 200 and r.json()["data"]["confirmed"] is True
    [p] = await store.profile(brain.rt, laptop.user_id)
    assert p.text == "The user's wifi is called Lotus."


async def test_m8_memory_page_routes(brain: Brain, laptop: Laptop) -> None:
    auth = {"Authorization": f"Bearer {laptop.access_token}"}
    a = await store.save(brain.rt, laptop.user_id, "The user's sister is Asha.", "person", 0.9)
    await store.save(brain.rt, laptop.user_id, "The user prefers tea.", "preference", 0.6)
    ben = await brain.sign_in("ben@example.com", "Ben's laptop")
    b = await store.save(
        brain.rt, uuid.UUID(ben["user"]["id"]), "The user's dog is Rex.", "fact", 0.5
    )

    items = (await brain.client.get("/v2/memories", headers=auth)).json()["data"]["items"]
    assert [i["text"] for i in items] == ["The user prefers tea.", "The user's sister is Asha."]
    found = (await brain.client.get("/v2/memories?q=asha", headers=auth)).json()["data"]["items"]
    assert [i["id"] for i in found] == [str(a.id)]

    r = await brain.client.patch(
        f"/v2/memories/{a.id}", json={"text": "The user's sister is Asha Rai."}, headers=auth
    )
    assert r.json()["data"]["text"] == "The user's sister is Asha Rai."
    hit = await store.search(brain.rt, laptop.user_id, "Rai")
    assert [h.id for h in hit] == [a.id]  # re-embedded and re-indexed

    for method in ("PATCH", "DELETE"):  # Ben's memory: never found, never touched
        r = await brain.client.request(
            method, f"/v2/memories/{b.id}", json={"text": "x"}, headers=auth
        )
        assert r.status_code == 404
    r = await brain.client.patch(f"/v2/memories/{a.id}", json={"confirmed": False}, headers=auth)
    assert r.status_code == 422  # un-confirming isn't a thing; delete it instead

    assert (await brain.client.delete(f"/v2/memories/{a.id}", headers=auth)).status_code == 200
    async with brain.rt.db() as db:
        assert await db.get(Memory, a.id) is None  # the embedding went with the row
        assert await db.get(Memory, b.id) is not None


async def test_m9_without_the_model_words_still_find_it(brain: Brain, laptop: Laptop) -> None:
    """The embedder downloads on first start: until then saves work and search uses words."""
    embedder = brain.rt.embedder
    assert isinstance(embedder, FakeEmbedder)
    embedder.on = False
    m = await store.save(brain.rt, laptop.user_id, "The user's sister is Asha.", "person", 0.9)
    assert m.embedding is None
    [hit] = await store.search(brain.rt, laptop.user_id, "call Asha")
    assert hit.id == m.id
    embedder.on = True  # the model is up: what was saved without it gets its vector
    assert await store.embed_missing(brain.rt) == 1
    async with brain.rt.db() as db:
        assert (await db.get(Memory, m.id)).embedding is not None


async def test_m10_the_same_fact_twice_is_one_memory(brain: Brain, laptop: Laptop) -> None:
    first = await store.save(brain.rt, laptop.user_id, "The user is vegetarian.", "fact", 0.6)
    again = await store.save(brain.rt, laptop.user_id, "The user is vegetarian!", "fact", 0.9)
    other = await store.save(brain.rt, laptop.user_id, "The user's sister is Asha.", "person", 0.9)
    assert again.id == first.id and again.importance == pytest.approx(0.9)
    assert other.id != first.id
    # close vectors never merge: a flipped preference reads like a paraphrase (survey §3.1)
    dark = await store.save(
        brain.rt, laptop.user_id, "The user prefers dark mode.", "preference", 0.6
    )
    light = await store.save(
        brain.rt, laptop.user_id, "The user prefers light mode.", "preference", 0.6
    )
    assert dark.id != light.id
    assert len(await saved(brain)) == 4


async def test_m11_unused_small_memories_lapse(brain: Brain, laptop: Laptop) -> None:
    """Decay (§8): low-importance memories expire 90 days after their last use; using one
    extends it; important ones never expire."""
    uid = laptop.user_id
    small = await store.save(brain.rt, uid, "The user tried sushi once.", "fact", 0.2)
    used = await store.save(brain.rt, uid, "The user likes green tea.", "preference", 0.3)
    big = await store.save(brain.rt, uid, "The user's sister is Asha.", "person", 0.9)
    brain.clock.advance(60 * DAY)
    assert [h.id for h in await store.search(brain.rt, uid, "green tea")] == [used.id]
    await asyncio.gather(*store._touching)  # last use is recorded after the answer
    brain.clock.advance(31 * DAY)
    hits = {h.id for h in await store.search(brain.rt, uid, "sushi tea Asha")}
    assert hits == {used.id, big.id}
    await store.save(brain.rt, uid, "The user drinks coffee.", "preference", 0.3)  # purges lapsed
    assert small.id not in {m.id for m in await saved(brain)}


async def test_m12_retrieval_p95_under_30ms_at_10k_memories(brain: Brain, laptop: Laptop) -> None:
    """PHASES R3: hybrid retrieval p95 < 30 ms with 10k memories for the user (and 10k for
    someone else in the same index). The query embedding is ~6 ms on top (real model)."""
    other = uuid.UUID((await brain.sign_in("ben@example.com", "Ben"))["user"]["id"])
    rng = random.Random(7)
    words = [f"w{i}" for i in range(200)]  # ~1% of memories share a word, like real ones
    hnsw = next(i for i in Memory.__table__.indexes if i.name == "ix_memories_embedding")
    # a bulk load: rows first, then the index (one-by-one HNSW inserts take a minute); its own
    # engine, because building the index can outlast the brain's 10 s command timeout
    loader = create_async_engine(TEST_DB, isolation_level="AUTOCOMMIT")
    async with loader.connect() as conn:
        await conn.run_sync(hnsw.drop)
        for uid in (laptop.user_id, other):
            await conn.execute(
                text(
                    "INSERT INTO memories (id, user_id, kind, text, embedding, importance) "
                    "SELECT gen_random_uuid(), :uid, 'fact', 'The user''s w' "
                    "|| floor(random() * 200)::int || ' is w' || floor(random() * 200)::int "
                    "|| ' (' || g || ').', (SELECT array_agg(random() - 0.5) "
                    "FROM generate_series(1, 384) WHERE g > 0)::vector::halfvec, random() "
                    "FROM generate_series(1, 10000) g"
                ),
                {"uid": uid},
            )
        await conn.run_sync(hnsw.create)
        await conn.execute(text("VACUUM ANALYZE memories"))  # what autovacuum does after a load
    await loader.dispose()
    queries = [f"what about my {rng.choice(words)} and {rng.choice(words)}" for _ in range(50)]
    for q in queries[:5]:  # warm-up
        await store.search(brain.rt, laptop.user_id, q, touch=False)
    took = []
    for q in queries:
        t0 = time.perf_counter()
        hits = await store.search(brain.rt, laptop.user_id, q, floor=False)
        took.append((time.perf_counter() - t0) * 1000)
        assert len(hits) == store.TOP_K
        await asyncio.gather(*store._touching)  # recorded after the turn, between turns
    took.sort()
    p95 = took[int(len(took) * 0.95) - 1]
    print(f"retrieval at 10k: p50 {took[len(took) // 2]:.1f} ms, p95 {p95:.1f} ms")
    assert p95 < 30, f"p95 {p95:.1f} ms"


async def test_m13_prompt_prefix_is_the_same_every_turn(brain: Brain, laptop: Laptop) -> None:
    """§21 prompt caching: system prompt (persona, then the profile) and tools are identical
    turn to turn for a user; the time and found memories ride only in the last message. The
    providers' cached-token counts add up to a hit rate per role."""
    assert brain.groq is not None
    for i in range(80):  # the profile is full; the gym is found per line
        await store.save(brain.rt, laptop.user_id, f"The user likes topic{i}.", "preference", 0.9)
    await store.save(brain.rt, laptop.user_id, "The user's gym is FitHub.", "fact", 0.3)
    first = {"usage": {"prompt_tokens": 1000, "completion_tokens": 9}}
    cached = {"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 900}}
    brain.groq.queue(
        Turn(text=["Sure."], last_chunk=first),
        Turn(text=["Okay."], last_chunk={"x_groq": {"usage": cached}}),  # Groq's shape
        model="fast",
    )
    await turn(laptop, "what's the weather like")
    brain.clock.advance(3 * 3600)
    await turn(laptop, "is my gym open today")
    one, two = brain.groq.for_model("fast")[:2]
    assert one["messages"][0] == two["messages"][0]
    assert one["tools"] == two["tools"]
    assert "remembered: The user's gym is FitHub." in two["messages"][-1]["content"]

    # the hit rate is tracked per role (Engines → Models); the laptop's token is 3 h old
    fresh = await brain.sign_in("asha@example.com", "Laptop")
    r = await brain.client.get("/v2/engines/chains", headers=brain.auth(fresh))
    assert r.json()["data"]["cache"]["reflex"] == {
        "input_tokens": 2000,
        "cached_tokens": 900,
        "hit_rate": 0.45,
    }


async def test_m14_partial_prefetch_searches_once_for_the_same_words(
    brain: Brain, laptop: Laptop, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8: memories are found on the partial transcript; the final only searches again if
    the words changed."""
    assert brain.groq is not None
    seen: list[str] = []
    real = store.search

    async def spy(rt: Any, user_id: uuid.UUID, query: str, *a: Any, **kw: Any) -> Any:
        if kw.get("touch", True):  # a turn's search, not the extractor's
            seen.append(query)
        return await real(rt, user_id, query, *a, **kw)

    monkeypatch.setattr(store, "search", spy)
    brain.groq.queue(Turn(text=["Sure."]), Turn(text=["Okay."]), model="fast")
    await laptop.call("signal.partial", {"signal_id": "s1", "text": "call my sister"})
    await laptop.say("call my sister", signal_id="s1")
    await laptop.reply("s1")
    assert seen == ["call my sister"]
    await laptop.call("signal.partial", {"signal_id": "s2", "text": "text my"})
    await laptop.say("text my brother", signal_id="s2")
    await laptop.reply("s2")
    assert seen == ["call my sister", "text my", "text my brother"]


def test_m15_extraction_output_is_checked_item_by_item() -> None:
    good = {"kind": "person", "text": "The user's sister is Asha.", "importance": 0.9}
    raw = "Sure!\n" + json.dumps({"memories": [good, {"kind": "gossip", "text": "x"}]})
    assert [i.text for i in extract.parse(raw)] == ["The user's sister is Asha."]
    assert extract.parse("no json here") == [] and extract.parse("{broken") == []
    many = json.dumps({"memories": [good] * 9})
    assert len(extract.parse(many)) == extract.MAX_NEW


async def test_m17_the_agent_gets_what_spark_remembers(brain: Brain, laptop: Laptop) -> None:
    """The agent's system prompt is static (cached), so the profile and the found memories ride
    in the job's first message."""
    assert brain.groq is not None
    await store.save(brain.rt, laptop.user_id, "The user's sister is Asha.", "person", 0.9)
    brain.groq.queue(
        Turn(text=["On it."], tool_calls=[tool("delegate", task="Email my sister", ack="On it.")]),
        model="fast",
    )
    brain.groq.queue(Turn(text=["I can't send email yet."]), model="agent")
    await turn(laptop, "email my sister about sunday")
    for _ in range(300):
        if brain.groq.for_model("agent"):
            break
        await asyncio.sleep(0.01)
    first = brain.groq.for_model("agent")[0]["messages"][-1]["content"]
    assert "remembered: The user's sister is Asha." in first
