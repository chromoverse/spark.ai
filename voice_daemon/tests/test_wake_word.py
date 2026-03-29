from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

VOICE_DAEMON_ROOT = Path(__file__).resolve().parents[1]
if str(VOICE_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICE_DAEMON_ROOT))


def _reload_modules(temp_root: Path):
    env_path = temp_root / ".env.test"
    env_path.write_text("DAEMON_SERVICE_TOKEN=test-token\n", encoding="utf-8")

    env = {
        "SPARK_ENV_PATH": str(env_path),
        "JARVIS_DATA_DIR": str(temp_root / "appdata"),
        "MODELS_DIR": str(temp_root / "models"),
    }

    with mock.patch.dict(os.environ, env, clear=True):
        import config.settings as settings
        import core.wake_word as wake_word

        settings = importlib.reload(settings)
        wake_word = importlib.reload(wake_word)
        return settings, wake_word


class WakeWordTests(unittest.TestCase):
    def test_load_uses_all_configured_model_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            models_dir = root / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "hey_spark.onnx").write_bytes(b"fake-model-1")
            (models_dir / "spark.onnx").write_bytes(b"fake-model-2")

            settings, wake_word = _reload_modules(root)
            captured: dict[str, object] = {}

            fake_openwakeword_model = types.ModuleType("openwakeword.model")

            class FakeModel:
                def __init__(self, *, wakeword_models, inference_framework):
                    captured["wakeword_models"] = wakeword_models
                    captured["inference_framework"] = inference_framework

            fake_openwakeword_model.Model = FakeModel
            fake_openwakeword = types.ModuleType("openwakeword")

            with mock.patch.dict(
                sys.modules,
                {
                    "openwakeword": fake_openwakeword,
                    "openwakeword.model": fake_openwakeword_model,
                },
            ):
                detector = wake_word.WakeWordDetector()
                detector.load()

            self.assertEqual(
                captured["wakeword_models"],
                list(settings.WAKE_WORD_MODEL_PATHS),
            )
            self.assertEqual(captured["inference_framework"], "onnx")

    def test_load_fails_fast_when_model_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            models_dir = root / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "hey_spark.onnx").write_bytes(b"fake-model-1")

            _, wake_word = _reload_modules(root)
            detector = wake_word.WakeWordDetector()

            with self.assertRaises(RuntimeError) as ctx:
                detector.load()

            self.assertIn("Missing Spark wake word model file(s)", str(ctx.exception))
            self.assertIn("spark.onnx", str(ctx.exception))

    def test_best_prediction_maps_model_name_back_to_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            models_dir = root / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "hey_spark.onnx").write_bytes(b"fake-model-1")
            (models_dir / "spark.onnx").write_bytes(b"fake-model-2")

            _, wake_word = _reload_modules(root)
            detector = wake_word.WakeWordDetector()

            label, score = detector._get_best_prediction(
                {
                    str(models_dir / "hey_spark.onnx"): [0.2, 0.95],
                    str(models_dir / "spark.onnx"): [0.3, 0.4],
                }
            )

            self.assertEqual(label, "hey_spark")
            self.assertEqual(score, 0.95)


if __name__ == "__main__":
    unittest.main()
