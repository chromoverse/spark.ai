"""
Startup initializer registrations.

Registers all module-level warm-up / init functions with the
``auto_initializer`` registry.  Importing this module is enough —
``main.py`` just does::

    import app.startup_registrations          # registers everything
    from app.auto_initializer import run_all  # then runs them
    await run_all()
"""

import logging
import time

from app.auto_initializer import register

logger = logging.getLogger(__name__)


# ── 0. Runtime dependency bootstrap (device-aware package install) ──
# async def _bootstrap_runtime_dependencies() -> None:
#     from app.bootstrap.runtime_dependency_bootstrap import ensure_runtime_dependencies
#     from app.config import settings

#     if settings.environment != "DESKTOP":
#         logger.info("Skipping runtime dependency bootstrap (env=%s)", settings.environment)
#         return
 
#     report = await ensure_runtime_dependencies()
#     if report.failed and bool(getattr(settings, "RUNTIME_AUTO_INSTALL_STRICT", False)):
#         raise RuntimeError(
#             "Runtime dependency bootstrap failed: " + ", ".join(report.failed)
#         )


# register("Runtime dependencies (device-aware bootstrap)", _bootstrap_runtime_dependencies)


# ── 1. API Key cache (sync — reads Windows registry once) ──
def _warmup_key_cache() -> None:
    from app.ai.providers.key_manager import _KeyCache
    _KeyCache.get_all()


register("KeyCache (API keys)", _warmup_key_cache)


# ── 2. Cache client (LocalKV / LanceDB / Redis) ──
async def _warmup_cache_client() -> None:
    from app.config import settings
    from app.cache import cache_manager

    try:
        await cache_manager._ensure_client()
    except Exception as exc:
        if settings.environment == "PRODUCTION":
            logger.warning(
                "Cache warmup failed in PRODUCTION; continuing without warm cache: %s",
                exc,
            )
            return
        raise


register("Cache client (LocalKV/Redis)", _warmup_cache_client)


# ── 3. TTS engine (Kokoro) ──
async def _warmup_tts() -> None:
    from app.config import settings
    if settings.environment != "DESKTOP":
        logger.info("Skipping Kokoro TTS warmup (env=%s)", settings.environment)
        return
    from app.services.tts_services import tts_service
    await tts_service.warmup_tts_engine()


register("TTS engine (Kokoro)", _warmup_tts)


# ── 4. Kernel runtime (event bus, persistence, logs) ──
async def _init_kernel_runtime() -> None:
    from app.kernel import init_kernel_runtime
    await init_kernel_runtime()


register("Kernel Runtime (events + persistence + logs)", _init_kernel_runtime)


# ── 5. Agentic System (Orchestrator, Engine, Tools) ──
async def _init_agent_system() -> None:
    from app.config import settings  # Module-level singleton (already validated)
    from app.kernel import KernelEvent, emit_kernel_event
    
    environment = settings.environment
    logger.info("Agent system environment: %s", environment)
    
    # ── Step 1: Sync runtime tools into AppData root ──
    from app.plugins.tools.scripts.runtime_sync import get_tools_runtime_sync, get_runtime_tools_paths
    from app.plugins.tools.scripts.dependency_checker import check_requirements
    await emit_kernel_event(
        KernelEvent(
            event_type="tools_sync_started",
            user_id="system",
            status="running",
            payload={"prefer_cdn": settings.TOOLS_CDN_ENABLED},
        )
    )
    try:
        sync_result = get_tools_runtime_sync().sync(prefer_cdn=settings.TOOLS_CDN_ENABLED)
        await emit_kernel_event(
            KernelEvent(
                event_type="tools_sync_completed",
                user_id="system",
                status="success",
                payload={
                    "synced": sync_result.synced,
                    "reason": sync_result.reason,
                    "runtime_version": sync_result.runtime_version,
                    "seed_version": sync_result.seed_version,
                    "source_used": sync_result.source_used,
                    "healthy": sync_result.healthy,
                    "runtime_root": sync_result.runtime_root,
                },
            )
        )
        logger.info(
            "Tools sync: %s (synced=%s, source=%s)",
            sync_result.reason,
            sync_result.synced,
            sync_result.source_used,
        )
    except Exception as exc:
        await emit_kernel_event(
            KernelEvent(
                event_type="tools_sync_failed",
                user_id="system",
                status="failed",
                payload={"error": str(exc)},
            )
        )
        raise

    # ── Step 1b: Ensure runtime tools requirements are installed in main env ──
    req_path = get_runtime_tools_paths().runtime_root / "requirements.txt"
    req_result = check_requirements(req_path)
    if req_result.missing:
        await emit_kernel_event(
            KernelEvent(
                event_type="tools_requirements_failed",
                user_id="system",
                status="failed",
                payload={
                    "requirements_path": req_result.requirements_path,
                    "missing": req_result.missing,
                },
            )
        )
        raise RuntimeError(
            "Missing tools_plugin runtime dependencies in main server env: "
            + ", ".join(req_result.missing)
        )

    await emit_kernel_event(
        KernelEvent(
            event_type="tools_requirements_ok",
            user_id="system",
            status="success",
            payload={
                "requirements_path": req_result.requirements_path,
                "checked": req_result.checked,
            },
        )
    )

    # ── Step 2: Load Tool Registry (from runtime root by default) ──
    from app.plugins.tools.registry_loader import load_tool_registry
    load_tool_registry()
    
    # ── Step 3: Load Tool Instances (runtime plugins) ──
    from app.plugins.tools.tool_instance_loader import load_all_tools
    load_all_tools()

    # ── Step 4: Generate typed SDK for developer DX ──
    from app.plugins.tools.scripts.sdk_generator import get_tools_sdk_generator
    get_tools_sdk_generator().generate()
    
    # ── Step 5: Initialize Orchestrator ──
    from app.agent.execution_gateway import init_orchestrator
    init_orchestrator()
    
    # ── Step 6: Initialize Task Emitter FIRST (engine depends on it) ──
    from app.agent.execution_gateway import init_task_emitter
    emitter = init_task_emitter()
    emitter.set_environment(environment)
    
    # Wire Socket Handler for production/non-desktop modes
    if environment != "DESKTOP":
        try:
            from app.socket import sio, connected_users
            from app.socket.task_handler import register_task_events
            task_handler = await register_task_events(sio, connected_users)
            emitter.set_socket_handler(task_handler)
            logger.info("Socket task handler wired (%s mode)", environment)
        except Exception as e:
            logger.error("Failed to wire socket handler: %s", e)
    
    # ── Step 7: Initialize Execution Engine ──
    from app.agent.execution_gateway import init_execution_engine
    engine = init_execution_engine()
    
    # ── Step 8: Initialize Server Executor ──
    from app.agent.execution_gateway import init_server_executor
    server_executor = init_server_executor()
    
    # ── Step 9: WIRE EVERYTHING TOGETHER ──
    engine.set_server_executor(server_executor)
    engine.set_client_emitter(emitter)
    
    logger.info("Agent system ready (env=%s, emitter=%s)", environment, emitter.environment)


register("Agentic System (Orchestrator + Tools)", _init_agent_system)


# ── 6. Ensure model assets are present on startup ──
def _download_models_if_needed() -> None:
    from app.config import settings
    if settings.environment != "DESKTOP":
        logger.info("Skipping model asset download check (env=%s)", settings.environment)
        return
    from app.ml.model_loader import model_loader
    model_loader.download_all_models()


register("Model assets (download check)", _download_models_if_needed)


# ── 7. Pinecone runtime warmup (production only) ──
def _warmup_pinecone_runtime() -> None:
    from app.config import settings
    from app.startup_state import startup_state

    startup_state.pinecone_service = None
    startup_state.pinecone_ready = False

    if settings.environment != "PRODUCTION":
        logger.info("Skipping Pinecone warmup (env=%s)", settings.environment)
        return

    try:
        from app.db.pinecone import config as pinecone_config

        service = pinecone_config.get_pinecone_service()
        # A lightweight call that verifies index binding at startup.
        _ = service.get_index_stats()
        startup_state.pinecone_service = service
        startup_state.pinecone_ready = True
        logger.info("✅ Pinecone runtime warmed up (production)")
    except Exception as exc:
        logger.warning("⚠️ Pinecone warmup failed in PRODUCTION: %s", exc)


register("Pinecone runtime warmup (production)", _warmup_pinecone_runtime)


# ── 8. Local ML runtime load (desktop only) ──
async def _init_local_ml_runtime() -> None:
    from app.config import settings
    from app.startup_state import startup_state

    startup_state.model_loader = None
    startup_state.embedding_worker = None
    startup_state.ml_device = None
    startup_state.embedding_ready = False

    if settings.environment != "DESKTOP":
        logger.info("Skipping local ML runtime load (env=%s)", settings.environment)
        return

    from app.ml import model_loader, embedding_worker, get_device, get_embedding
    device = get_device()

    startup_state.model_loader = model_loader
    startup_state.embedding_worker = embedding_worker
    startup_state.ml_device = device

    logger.info("=" * 60)
    logger.info(" Loading ML models on device: %s", device)
    logger.info("=" * 60)

    success = model_loader.load_all_models()
    if success:
        logger.info(" All ML models loaded successfully")
    else:
        logger.warning("⚠️  Some ML models failed to load - check logs")

    # Warmup whatever managed to load (for example embedding even if whisper fails).
    model_loader.warmup_models()
    logger.info(" Model warmup step completed")

    # Explicitly enforce embedding readiness independent of other model failures.
    embedding_model = model_loader.get_model("embedding")
    if embedding_model is None:
        embedding_model = model_loader.load_model("embedding")
    if embedding_model is None:
        logger.warning("⚠️ Embedding model unavailable at startup")
        return

    try:
        primer_started = time.perf_counter()
        primer_vector = await get_embedding("startup embedding warmup")
        primer_ms = (time.perf_counter() - primer_started) * 1000
        startup_state.embedding_ready = bool(primer_vector)
        logger.info(
            "✅ Embedding worker primed at startup (dim=%d, elapsed_ms=%.0f)",
            len(primer_vector),
            primer_ms,
        )
    except Exception as exc:
        logger.warning("⚠️ Embedding worker startup prime failed: %s", exc)


register("Local ML runtime (desktop only)", _init_local_ml_runtime)


