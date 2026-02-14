"""
Startup initializer registrations.

Registers all module-level warm-up / init functions with the
``auto_initializer`` registry.  Importing this module is enough —
``main.py`` just does::

    import app.startup_registrations          # registers everything
    from app.auto_initializer import run_all  # then runs them
    await run_all()
"""

from app.auto_initializer import register


# ── 1. API Key cache (sync — reads Windows registry once) ──
def _warmup_key_cache() -> None:
    from app.ai.providers.key_manager import _KeyCache
    _KeyCache.get_all()


register("KeyCache (API keys)", _warmup_key_cache)


# ── 2. Cache client (LocalKV / LanceDB / Redis) ──
async def _warmup_cache_client() -> None:
    from app.cache import redis_manager
    await redis_manager._ensure_client()


register("Cache client (LocalKV/Redis)", _warmup_cache_client)


# ── 3. TTS engine (Kokoro) ──
async def _warmup_tts() -> None:
    from app.services.tts_services import tts_service
    await tts_service.warmup_tts_engine()


register("TTS engine (Kokoro)", _warmup_tts)
