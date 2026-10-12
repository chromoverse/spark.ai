"""Provider chains per role, free first (REDESIGN §5.3, §5.5), and the runner that walks them.

A call goes to the first entry that is enabled, has a key, and whose circuit is closed. Reflex
calls are hedged: no first token by `hedge_s` → the next entry starts in parallel and the first
stream to produce output wins. Failures before output fall through silently; a failure after
output yields `Restart` and the next entry starts over. Only `ChainExhausted` reaches the caller,
except for roles that surface malformed output (`Malformed`): the agent retries once, then
escalates past that entry with `exclude` (§5.2).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypeVar

import httpx
from redis.asyncio import Redis

from app.core.clock import Clock, within
from app.core.config import Settings
from app.llm import claude, openai_compat
from app.llm.health import Health, health_id
from app.llm.types import (
    ChainExhausted,
    Done,
    ErrorKind,
    Malformed,
    Message,
    ProviderError,
    Restart,
    StreamEvent,
    ToolDef,
)

logger = logging.getLogger(__name__)

Role = Literal["reflex", "agent", "subagent", "review", "memory"]
T = TypeVar("T")


@dataclass(frozen=True)
class Entry:
    provider: str
    model: str
    paid: bool = False
    trains_on_data: bool = False
    extra: dict[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class RoleConfig:
    hedge_s: float | None  # start the next entry in parallel when no first token by then
    ttft_timeout_s: float  # an entry with no first token by then has failed
    gap_s: float  # a stream silent for longer has stalled (REDESIGN §19.1)
    max_tokens: int
    surface_malformed: bool = False  # raise Malformed instead of falling through


# gpt-oss reasons before answering; "low" keeps time-to-first-token inside the reflex budget.
_FAST = {"reasoning_effort": "low"}
_MEDIUM = {"reasoning_effort": "medium"}  # agent effort default (§28)
_EFFORT = {"output_config": {"effort": "medium"}}
_SUB = [
    Entry("groq", "openai/gpt-oss-20b", extra=_FAST),
    Entry("groq", "qwen/qwen3.8-27b"),
    Entry("cloudflare", "@cf/openai/gpt-oss-20b"),
    Entry("nvidia", "nvidia/nemotron-3-super"),
    Entry("openrouter", "openai/gpt-oss-20b:free"),
    Entry("anthropic", "claude-haiku-5-5", paid=True, extra={"output_config": {"effort": "low"}}),
]

# Order is free first, then measured quality and latency. The R1 reflex eval + latency bench
# ordered the reflex; the R2 agent eval orders the agent chain. Each Groq model has its own rate
# limit bucket, so escalating to the next model also escapes a 429.
CHAINS: dict[Role, list[Entry]] = {
    "reflex": [
        Entry("groq", "openai/gpt-oss-20b", extra=_FAST),
        Entry("groq", "openai/gpt-oss-120b", extra=_FAST),
        Entry("cloudflare", "@cf/openai/gpt-oss-20b"),
        Entry("gemini", "gemini-flash-lite-latest", trains_on_data=True),
        Entry("mistral", "mistral-small-latest"),
        # thinking off + low effort: the fastest Claude for spoken replies (§5.1)
        Entry(
            "anthropic",
            "claude-haiku-5-5",
            paid=True,
            extra={"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
        ),
    ],
    "agent": [
        Entry("groq", "openai/gpt-oss-120b", extra=_MEDIUM),
        Entry("groq", "qwen/qwen3.8-27b"),
        Entry("groq", "openai/gpt-oss-20b", extra=_MEDIUM),
        Entry("nvidia", "deepseek-ai/deepseek-v4"),
        Entry("cloudflare", "@cf/openai/gpt-oss-120b"),
        Entry("mistral", "mistral-medium-latest"),
        Entry("gemini", "gemini-flash-latest", trains_on_data=True),
        Entry("openrouter", "openai/gpt-oss-120b:free"),
        Entry("anthropic", "claude-haiku-5-5", paid=True, extra=_EFFORT),
        Entry("anthropic", "claude-sonnet-5-5", paid=True, extra=_EFFORT),
        Entry("anthropic", "claude-opus-5-5", paid=True, extra=_EFFORT),
    ],
    # Off the voice path where a wrong call costs something (the safety check before an action
    # on the user's computer, read-only research for the agent): the stronger free model first.
    # Extraction scores 32/32 on 20b, so it stays there and off the agent's 120b quota.
    "subagent": [Entry("groq", "openai/gpt-oss-120b", extra=_MEDIUM), *_SUB],
    "review": [Entry("groq", "openai/gpt-oss-120b", extra=_FAST), *_SUB],
    "memory": _SUB,  # extraction after turns (§8): background, never on the voice path
}

ROLES: dict[Role, RoleConfig] = {
    "reflex": RoleConfig(hedge_s=0.35, ttft_timeout_s=2.5, gap_s=1.5, max_tokens=300),
    # reasoning models think before the first token; the agent isn't on the voice path
    "agent": RoleConfig(None, 30.0, 15.0, 2048, surface_malformed=True),
    "subagent": RoleConfig(None, 20.0, 15.0, 1024, surface_malformed=True),
    "review": RoleConfig(None, 5.0, 5.0, 200),
    "memory": RoleConfig(None, 20.0, 15.0, 600),
}
# The hedge is for a late first token, late for that entry: from Nepal Groq's usual TTFT is
# ~450 ms, so a fixed 350 ms hedge fired on ~95% of calls and doubled every turn's free quota
# (latency bench, 2026-10-10). Near the provider (R7 region) the 350 ms floor still applies.
HEDGE_OVER_USUAL = 1.3


def _keys(secret: Any) -> list[str]:
    return [k.strip() for k in secret.get_secret_value().split(",") if k.strip()]


def providers(settings: Settings) -> dict[str, tuple[str, list[str]]]:
    """provider → (base URL, API keys). A provider without keys is skipped."""
    cf = settings.cloudflare_account_id
    return {
        "groq": ("https://api.groq.com/openai/v1", _keys(settings.groq_api_keys)),
        "nvidia": ("https://integrate.api.nvidia.com/v1", _keys(settings.nvidia_api_keys)),
        "cloudflare": (
            f"https://api.cloudflare.com/client/v4/accounts/{cf}/ai/v1",
            _keys(settings.cloudflare_api_tokens) if cf else [],
        ),
        "mistral": ("https://api.mistral.ai/v1", _keys(settings.mistral_api_keys)),
        "gemini": (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            _keys(settings.gemini_api_keys),
        ),
        "openrouter": ("https://openrouter.ai/api/v1", _keys(settings.openrouter_api_keys)),
        "anthropic": ("", _keys(settings.anthropic_api_key)),  # the SDK knows its own URL
    }


@dataclass(frozen=True)
class Candidate:
    entry: Entry
    base_url: str
    api_key: str = field(repr=False)
    ttft_ms: float | None = field(default=None, compare=False)  # usual, from health

    @property
    def hid(self) -> str:
        return health_id(self.entry.provider, self.api_key, self.entry.model)

    @property
    def label(self) -> str:
        return f"{self.entry.provider}/{self.entry.model}"


async def _next(agen: AsyncIterator[StreamEvent]) -> StreamEvent | None:
    try:
        return await agen.__anext__()
    except StopAsyncIteration:
        return None


async def _within(clock: Clock, aw: Awaitable[T], seconds: float, kind: ErrorKind) -> T:
    try:
        return await within(clock, aw, seconds)
    except TimeoutError:
        raise ProviderError(kind) from None


class ChainRunner:
    def __init__(self, settings: Settings, clock: Clock, http: httpx.AsyncClient, redis: Redis):
        self.settings = settings
        self.clock = clock
        self.http = http
        self.health = Health(redis, clock)
        self._claude: dict[str, Any] = {}  # api key → AsyncAnthropic, built on first paid call

    async def aclose(self) -> None:
        for api in self._claude.values():
            await api.close()

    async def _count_cache(self, role: Role, usage: dict[str, int]) -> None:
        """Prompt-cache hits per role per day (§21): cached input tokens / input tokens."""
        if not usage.get("input_tokens"):
            return
        key = f"cache:{role}:{self.clock.now():%Y-%m-%d}"
        try:
            async with self.health.redis.pipeline(transaction=False) as pipe:
                pipe.hincrby(key, "input_tokens", usage["input_tokens"])
                pipe.hincrby(key, "cached_tokens", usage.get("cache_read_tokens", 0))
                pipe.expire(key, 8 * 86400)
                await pipe.execute()
        except Exception:
            logger.warning("cache stats not counted", exc_info=True)

    async def candidates(
        self, role: Role, *, allow_training: bool, exclude: frozenset[str] = frozenset()
    ) -> list[Candidate]:
        table = providers(self.settings)
        out: list[Candidate] = []
        for entry in CHAINS[role]:
            if entry.paid and not self.settings.paid_providers_enabled:
                continue
            if entry.trains_on_data and not allow_training:
                continue
            if f"{entry.provider}/{entry.model}" in exclude:
                continue
            base_url, keys = table.get(entry.provider, ("", []))
            out.extend(Candidate(entry, base_url, k) for k in keys)
        states = await self.health.states([c.hid for c in out])
        return [replace(c, ttft_ms=ttft) for c, (ok, ttft) in zip(out, states, strict=True) if ok]

    def _open(
        self,
        c: Candidate,
        role: Role,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
    ) -> AsyncGenerator[StreamEvent, None]:
        if c.entry.provider == "anthropic":
            api = self._claude.get(c.api_key) or self._claude.setdefault(
                c.api_key, claude.client(c.api_key)
            )
            return claude.stream(
                api,
                model=c.entry.model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=ROLES[role].max_tokens,
                extra=c.entry.extra,
            )
        return openai_compat.stream(
            self.http,
            base_url=c.base_url,
            api_key=c.api_key,
            model=c.entry.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=ROLES[role].max_tokens,
            extra=c.entry.extra,
        )

    async def stream(
        self,
        role: Role,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef] = (),
        allow_training: bool = False,
        exclude: frozenset[str] = frozenset(),
    ) -> AsyncGenerator[StreamEvent, None]:
        """`exclude` skips entries by "provider/model" (a job that escalated past them)."""
        cfg = ROLES[role]
        pending = await self.candidates(role, allow_training=allow_training, exclude=exclude)
        if not pending:
            raise ChainExhausted(role)
        while True:
            cand, agen, first = await self._race(pending, cfg, role, system, messages, tools)
            try:
                yield first
                while True:
                    ev = await _within(self.clock, _next(agen), cfg.gap_s, "stalled")
                    if ev is None:
                        return
                    if isinstance(ev, Done):
                        await self._count_cache(role, ev.usage)
                        ev = replace(ev, provider=cand.label)
                    yield ev
            except ProviderError as exc:
                logger.warning("llm stream broke", extra={"llm": cand.label, "error": exc.kind})
                if exc.kind == "malformed" and cfg.surface_malformed:
                    raise Malformed(cand.label) from exc
                await self.health.fail(cand.hid, exc)
                if not pending:
                    raise ChainExhausted(role) from exc
                yield Restart(exc.kind)
            finally:
                await agen.aclose()

    async def _race(
        self,
        pending: list[Candidate],
        cfg: RoleConfig,
        role: Role,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
    ) -> tuple[Candidate, AsyncGenerator[StreamEvent, None], StreamEvent]:
        """Runs entries until one produces output. Hedged losers go back to the front of
        `pending` (they didn't fail); failed ones are recorded and dropped."""
        running: dict[asyncio.Future[StreamEvent | None], tuple[Candidate, Any, float]] = {}

        def start() -> Candidate:
            c = pending.pop(0)
            agen = self._open(c, role, system, messages, tools)
            task = asyncio.ensure_future(
                _within(self.clock, _next(agen), cfg.ttft_timeout_s, "timeout")
            )
            running[task] = (c, agen, self.clock.monotonic())
            return c

        def arm(c: Candidate) -> asyncio.Future[None] | None:
            if cfg.hedge_s is None or not pending:
                return None
            late_s = max(cfg.hedge_s, (c.ttft_ms or 0) / 1000 * HEDGE_OVER_USUAL)
            return asyncio.ensure_future(self.clock.sleep(late_s))

        hedge = arm(start())
        try:
            while running:
                waiting: set[asyncio.Future[Any]] = set(running)
                if hedge is not None:
                    waiting.add(hedge)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if hedge is not None and hedge in done:
                    logger.info("llm hedge", extra={"llm": pending[0].label})
                    hedge = arm(start())
                for task in [t for t in done if t in running]:
                    c, agen, t0 = running.pop(task)
                    try:
                        ev = task.result()
                        if ev is None or isinstance(ev, Done):
                            raise ProviderError("malformed", "empty output")
                    except ProviderError as exc:
                        logger.warning(
                            "llm entry failed", extra={"llm": c.label, "error": exc.kind}
                        )
                        if exc.kind == "malformed" and cfg.surface_malformed:
                            await agen.aclose()
                            raise Malformed(c.label) from exc
                        await self.health.fail(c.hid, exc)
                        await agen.aclose()
                        if not running and pending:
                            if hedge is not None:
                                hedge.cancel()
                            hedge = arm(start())
                        continue
                    ttft_ms = (self.clock.monotonic() - t0) * 1000
                    await self.health.ok(c.hid, ttft_ms)
                    logger.info("llm first token", extra={"llm": c.label, "ttft_ms": ttft_ms})
                    for loser, (lc, lagen, _) in list(running.items()):
                        loser.cancel()
                        await asyncio.wait({loser})
                        await lagen.aclose()
                        pending.insert(0, lc)
                    running.clear()
                    return c, agen, ev
        finally:
            if hedge is not None:
                hedge.cancel()
            for task, (_, agen, _) in running.items():
                task.cancel()
                await asyncio.wait({task})
                await agen.aclose()
        raise ChainExhausted(role)


__all__ = ["CHAINS", "ChainExhausted", "ChainRunner", "Restart"]
