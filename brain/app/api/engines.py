from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import Me, Rt
from app.core.errors import ok
from app.llm.chains import CHAINS, providers
from app.llm.health import health_id

router = APIRouter(prefix="/v2/engines")


@router.get("/chains")
async def chains(me: Me, rt: Rt) -> dict[str, Any]:
    """Each role's chain, free first (Engines → Models): whether an entry can run (paid on, a key,
    the user's training opt-in) and its health across keys, plus today's prompt-cache hit rate
    per role. Keys never leave the brain."""
    table = providers(rt.settings)
    out: dict[str, list[dict[str, Any]]] = {}
    for role, entries in CHAINS.items():
        rows = []
        for e in entries:
            keys = table.get(e.provider, ("", []))[1]
            states = await rt.llm.health.states([health_id(e.provider, k, e.model) for k in keys])
            ttfts = [t for _, t in states if t is not None]
            rows.append(
                {
                    "provider": e.provider,
                    "model": e.model,
                    "paid": e.paid,
                    "trains_on_data": e.trains_on_data,
                    "keys": len(keys),
                    "enabled": bool(keys) and (not e.paid or rt.settings.paid_providers_enabled),
                    "healthy": any(open_ for open_, _ in states),
                    "ttft_ms": round(min(ttfts)) if ttfts else None,
                }
            )
        out[role] = rows
    day = f"{rt.clock.now():%Y-%m-%d}"
    cache = {}
    for role in CHAINS:  # prompt-cache hits today (§21); provider-wide, never per user
        h = await rt.redis.hgetall(f"cache:{role}:{day}")
        seen, hit = int(h.get("input_tokens", 0)), int(h.get("cached_tokens", 0))
        cache[role] = {
            "input_tokens": seen,
            "cached_tokens": hit,
            "hit_rate": round(hit / seen, 3) if seen else None,
        }
    return ok({"roles": out, "cache": cache})
