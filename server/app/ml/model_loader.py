"""
Model Loader — downloads, loads, and caches all ML models.

Key behaviours
──────────────
• load=True models   — loaded eagerly on load_all_models() at boot.
• lazy_load=True     — skipped at boot; loaded transparently on first
                       get_model() call, then cached for the process lifetime.
• load=False, lazy_load=False — completely skipped; get_model() returns None.
• Parallel loading   — all eager models start concurrently via ThreadPoolExecutor.
• Meta-tensor fix    — SentenceTransformer receives model_kwargs={"device_map": None}
                       so transformers never places weights on a meta device.
• Lazy device        — torch is never imported at module level; device is resolved
                       on the first desktop load call.
"""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from app.ml.config import MODELS_CONFIG, apply_runtime_device_to_models
from app.config import settings

logger = logging.getLogger(__name__)


class ModelLoader:
    """Singleton that owns every loaded ML model for the process lifetime."""

    _instance:        Optional["ModelLoader"] = None
    _models:          Dict[str, Any]          = {}
    _initialized:     bool                    = False
    _runtime_device:  Optional[str]           = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.__class__._initialized = True

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _desktop() -> bool:
        return settings.environment == "DESKTOP"

    def _ensure_device(self) -> str:
        if self._runtime_device is None:
            self._runtime_device = apply_runtime_device_to_models()
            logger.info("Runtime device resolved: %s", self._runtime_device)
        return self._runtime_device

    @staticmethod
    def _is_valid_st_dir(path) -> bool:
        return all([
            (path / "modules.json").exists(),
            (path / "1_Pooling" / "config.json").exists(),
        ])

    @staticmethod
    def _should_eager_load(cfg: dict) -> bool:
        return bool(cfg.get("load", True))

    @staticmethod
    def _should_lazy_load(cfg: dict) -> bool:
        """True only when load=False AND lazy_load=True."""
        return not cfg.get("load", True) and bool(cfg.get("lazy_load", False))

    @staticmethod
    def _is_disabled(cfg: dict) -> bool:
        """load=False + lazy_load=False → model is disabled."""
        return not cfg.get("load", True) and not cfg.get("lazy_load", False)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_model(self, model_key: str) -> bool:
        if not self._desktop():
            return False

        self._ensure_device()
        cfg = MODELS_CONFIG.get(model_key)
        if not cfg:
            logger.error("Unknown model key: %s", model_key)
            return False

        # Don't download disabled models
        if self._is_disabled(cfg):
            logger.debug("Model '%s' is disabled — skipping download", model_key)
            return True

        path       = cfg["path"]
        model_type = cfg["type"]

        if path.exists() and any(path.iterdir()):
            if model_type == "sentence-transformer":
                if self._is_valid_st_dir(path):
                    return True
                logger.warning("Model '%s' dir incomplete — re-downloading", model_key)
                shutil.rmtree(path, ignore_errors=True)
            else:
                return True

        path.mkdir(parents=True, exist_ok=True)

        try:
            if model_type == "sentence-transformer":
                from sentence_transformers import SentenceTransformer
                m = SentenceTransformer(cfg["name"], cache_folder=str(path.parent))
                m.save(str(path))
                if not self._is_valid_st_dir(path):
                    raise RuntimeError(f"ST artifacts incomplete at {path}")

            elif model_type == "whisper":
                from faster_whisper import WhisperModel
                # faster-whisper resolves model name directly (e.g. "small")
                model_name = cfg["name"].split("/")[-1].replace("faster-whisper-", "")
                path.mkdir(parents=True, exist_ok=True)
                WhisperModel(model_name, download_root=str(path), device="cpu")

            elif model_type == "transformers":
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                m = AutoModelForSequenceClassification.from_pretrained(cfg["name"])
                t = AutoTokenizer.from_pretrained(cfg["name"])
                m.save_pretrained(str(path))
                t.save_pretrained(str(path))

            logger.info("Downloaded '%s' successfully", model_key)
            return True

        except Exception as exc:
            logger.error("Download failed for '%s': %s", model_key, exc)
            return False

    # ── Load (single model) ────────────────────────────────────────────────────

    def load_model(self, model_key: str, force: bool = False) -> Optional[Any]:
        """
        Load one model into memory.
        Respects load/lazy_load flags unless force=True.
        Thread-safe for parallel calls.
        """
        if not self._desktop():
            return None

        device = self._ensure_device()
        cfg    = MODELS_CONFIG.get(model_key)

        if not cfg:
            logger.error("Unknown model key: %s", model_key)
            return None

        # Respect disabled flag unless explicitly forced
        if not force and self._is_disabled(cfg):
            logger.debug(
                "Model '%s' is disabled (load=False, lazy_load=False) — skipping",
                model_key,
            )
            return None

        if not force and model_key in self._models:
            return self._models[model_key]

        if not self.download_model(model_key):
            return None

        logger.info("Loading '%s' from %s on %s", model_key, cfg["path"], device)

        try:
            model = self._load_by_type(cfg["type"], cfg["path"], cfg, device)
        except Exception as exc:
            logger.error("Failed to load '%s': %s", model_key, exc, exc_info=True)
            return None

        self._models[model_key] = model
        logger.info("'%s' ready on %s", model_key, device)
        return model

    def _load_by_type(self, mtype: str, path, cfg: dict, device: str) -> Any:
        if mtype == "sentence-transformer":
            return self._load_sentence_transformer(path, cfg, device)

        if mtype == "whisper":
            from faster_whisper import WhisperModel
            model_name  = cfg["name"].split("/")[-1].replace("faster-whisper-", "")
            compute     = "float16" if device == "cuda" else "int8"
            cpu_threads = int(getattr(settings, "WHISPER_CPU_THREADS", 4))
            return WhisperModel(
                model_name,
                device=device,
                compute_type=compute,
                cpu_threads=cpu_threads,
                download_root=str(path),
            )

        if mtype == "transformers":
            from transformers import pipeline
            return pipeline(
                "text-classification",
                model=str(path), tokenizer=str(path),
                device=0 if device == "cuda" else -1,
            )

        raise ValueError(f"Unknown model type: {mtype}")

    @staticmethod
    def _load_sentence_transformer(path, cfg: dict, device: str):
        import torch
        from sentence_transformers import SentenceTransformer

        model_kwargs: dict = {"device_map": None}
        if device in ("cpu", "vulkan"):
            model_kwargs["dtype"] = torch.float32

        model = SentenceTransformer(str(path), device=device, model_kwargs=model_kwargs)
        if cfg.get("max_seq_length"):
            model.max_seq_length = cfg["max_seq_length"]
        return model

    # ── Parallel bulk load (eager models only) ─────────────────────────────────

    def load_all_models(self) -> bool:
        """
        Load all models where load=True in parallel.
        Models with load=False are skipped here regardless of lazy_load.
        """
        if not self._desktop():
            return True

        self._ensure_device()

        eager_keys = [k for k, cfg in MODELS_CONFIG.items() if self._should_eager_load(cfg)]
        skip_keys  = [k for k, cfg in MODELS_CONFIG.items() if not self._should_eager_load(cfg)]

        if skip_keys:
            for k in skip_keys:
                cfg = MODELS_CONFIG[k]
                tag = "lazy" if self._should_lazy_load(cfg) else "disabled"
                logger.info("Skipping '%s' at boot (%s)", k, tag)

        if not eager_keys:
            return True

        logger.info("Eager loading %d model(s): %s", len(eager_keys), eager_keys)
        success = True

        with ThreadPoolExecutor(max_workers=len(eager_keys), thread_name_prefix="ml_load") as ex:
            futures = {ex.submit(self.load_model, k): k for k in eager_keys}
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    if fut.result() is None:
                        logger.warning("Model '%s' did not load", key)
                        success = False
                except Exception as exc:
                    logger.error("Model '%s' load raised: %s", key, exc)
                    success = False

        return success

    def download_all_models(self) -> bool:
        """Download all non-disabled models in parallel."""
        if not self._desktop():
            return True

        self._ensure_device()
        keys    = [k for k, cfg in MODELS_CONFIG.items() if not self._is_disabled(cfg)]
        success = True

        with ThreadPoolExecutor(max_workers=max(1, len(keys)), thread_name_prefix="ml_dl") as ex:
            futures = {ex.submit(self.download_model, k): k for k in keys}
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    if not fut.result():
                        success = False
                except Exception as exc:
                    logger.error("Download '%s' raised: %s", key, exc)
                    success = False

        return success

    # ── Accessor — respects lazy_load ──────────────────────────────────────────

    def get_model(self, model_key: str) -> Optional[Any]:
        """
        Return a loaded model.

        Behaviour by flag:
          load=True            → already in cache from boot; returns immediately.
          load=False, lazy=True  → loads now on first call, cached for all future calls.
          load=False, lazy=False → disabled; returns None without loading.
        """
        if model_key in self._models:
            return self._models[model_key]

        cfg = MODELS_CONFIG.get(model_key)
        if not cfg:
            logger.error("Unknown model key: %s", model_key)
            return None

        if self._is_disabled(cfg):
            logger.debug("get_model('%s') — model is disabled, returning None", model_key)
            return None

        # Lazy load — first access triggers load
        if self._should_lazy_load(cfg):
            logger.info("Lazy-loading '%s' on first access", model_key)
            return self.load_model(model_key)

        return None

    # ── Warmup ─────────────────────────────────────────────────────────────────

    def warmup(self) -> None:
        """Dummy inference on every loaded model to avoid cold starts."""
        if not self._desktop():
            return

        emb = self._models.get("embedding")
        if emb:
            try:
                emb.encode(["warmup"], show_progress_bar=False)
                logger.info("Embedding model warmed up")
            except Exception as exc:
                logger.warning("Embedding warmup failed: %s", exc)

        emo = self._models.get("emotion")
        if emo:
            try:
                emo("warmup text")
                logger.info("Emotion model warmed up")
            except Exception as exc:
                logger.warning("Emotion warmup failed: %s", exc)

    def warmup_models(self) -> None:
        """Alias for warmup() — backwards compatibility."""
        return self.warmup()

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def unload(self, model_key: str) -> None:
        self._models.pop(model_key, None)
        logger.info("Unloaded model '%s'", model_key)

    def unload_all(self) -> None:
        self._models.clear()
        logger.info("All models unloaded")


model_loader = ModelLoader()