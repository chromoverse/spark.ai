"""
Auto Initializer — Centralized startup registry.

Any module can register an async (or sync) initializer function.  During
application startup ``main.py`` calls ``run_all()`` once to execute every
registered function in registration order.

Usage
-----
**Register an initializer (in any module):**

    from app.auto_initializer import register

    async def _warmup_tts():
        from app.services.tts_services import tts_service
        await tts_service.warmup_tts_engine()

    register("tts", _warmup_tts)

**Run all at startup (in main.py):**

    from app.auto_initializer import run_all

    await run_all()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Union

logger = logging.getLogger(__name__)

# (name, callable) — order matters
_registry: list[tuple[str, Callable[[], Union[None, Awaitable[None]]]]] = []


def register(
    name: str,
    fn: Callable[[], Union[None, Awaitable[None]]],
) -> None:
    """
    Register an initializer.

    Args:
        name: Human-readable label for log output.
        fn:   Sync or async callable (no arguments).
    """
    _registry.append((name, fn))


async def run_all() -> None:
    """Execute every registered initializer sequentially, logging timing."""
    if not _registry:
        logger.info("ℹ️  AutoInitializer: nothing registered")
        return

    logger.info("=" * 60)
    logger.info(f"🚀 AutoInitializer: running {len(_registry)} initializer(s)...")
    logger.info("=" * 60)

    for name, fn in _registry:
        t0 = time.time()
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
            elapsed = time.time() - t0
            logger.info(f"  ✅ {name} ({elapsed:.2f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"  ❌ {name} failed ({elapsed:.2f}s): {e}")
            # Don't raise — allow other initializers to still run.

    logger.info("=" * 60)
    logger.info("✅ AutoInitializer: all done")
    logger.info("=" * 60)
