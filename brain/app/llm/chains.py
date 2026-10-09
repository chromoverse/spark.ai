"""Provider chains per role, free first (REDESIGN §5.3, §5.5), and the runner that walks them.

A call goes to the first entry that is enabled, has a key, and whose circuit is closed. Reflex
calls are hedged: no first token by `hedge_s` → the next entry starts in parallel and the first
stream to produce output wins. Failures before output fall through silently; a failure after
output yields `Restart` and the next entry starts over. Only `ChainExhausted` reaches the caller.
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
    Message,
    ProviderError,
    Restart,
    StreamEvent,
    ToolDef,
)

logger = logging.getLogger(__name__)

Role = Literal["reflex"]
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


# gpt-oss reasons before answering; "low" keeps time-to-first-token inside the reflex budget.
_FAST = {"reasoning_effort": "low"}

# Order is free first, then measured quality and latency. The R1 reflex eval + latency bench
# re-order these (PHASES R1); agent/subagent chains land with the agent loop in R2.
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
}

ROLES: dict[Role, RoleConfig] = {
    "reflex": RoleConfig(hedge_s=0.35, ttft_timeout_s=2.5, gap_s=1.5, max_tokens=300),
}


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

    async def candidates(self, role: Role, *, allow_training: bool) -> list[Candidate]:
        table = providers(self.settings)
        out: list[Candidate] = []
        for entry in CHAINS[role]:
            if entry.paid and not self.settings.paid_providers_enabled:
                continue
            if entry.trains_on_data and not allow_training:
                continue
            base_url, keys = table.get(entry.provider, ("", []))
            out.extend(Candidate(entry, base_url, k) for k in keys)
        healthy = await self.health.closed([c.hid for c in out])
        return [c for c, ok in zip(out, healthy, strict=True) if ok]

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
    ) -> AsyncGenerator[StreamEvent, None]:
        cfg = ROLES[role]
        pending = await self.candidates(role, allow_training=allow_training)
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
                    yield replace(ev, provider=cand.label) if isinstance(ev, Done) else ev
            except ProviderError as exc:
                logger.warning("llm stream broke", extra={"llm": cand.label, "error": exc.kind})
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

        def start() -> None:
            c = pending.pop(0)
            agen = self._open(c, role, system, messages, tools)
            task = asyncio.ensure_future(
                _within(self.clock, _next(agen), cfg.ttft_timeout_s, "timeout")
            )
            running[task] = (c, agen, self.clock.monotonic())

        def arm() -> asyncio.Future[None] | None:
            if cfg.hedge_s is None or not pending:
                return None
            return asyncio.ensure_future(self.clock.sleep(cfg.hedge_s))

        start()
        hedge = arm()
        try:
            while running:
                waiting: set[asyncio.Future[Any]] = set(running)
                if hedge is not None:
                    waiting.add(hedge)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if hedge is not None and hedge in done:
                    logger.info("llm hedge", extra={"llm": pending[0].label})
                    start()
                    hedge = arm()
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
                        await self.health.fail(c.hid, exc)
                        await agen.aclose()
                        if not running and pending:
                            start()
                            if hedge is not None:
                                hedge.cancel()
                            hedge = arm()
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
