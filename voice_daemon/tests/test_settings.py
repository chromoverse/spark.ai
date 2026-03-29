from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

VOICE_DAEMON_ROOT = Path(__file__).resolve().parents[1]
if str(VOICE_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICE_DAEMON_ROOT))


def _load_settings(temp_root: Path, env_lines: list[str], extra_env: dict[str, str] | None = None):
    env_path = temp_root / ".env.test"
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    env = {
        "SPARK_ENV_PATH": str(env_path),
        "JARVIS_DATA_DIR": str(temp_root / "appdata"),
    }
    if extra_env:
        env.update(extra_env)

    with mock.patch.dict(os.environ, env, clear=True):
        import config.settings as settings

        return importlib.reload(settings)


class SettingsTests(unittest.TestCase):
    def test_shared_config_is_seeded_from_env_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = _load_settings(
                root,
                [
                    "DAEMON_SERVICE_TOKEN=test-token",
                    "WAKE_WORD_PHRASES=hey spark,spark",
                    "WAKE_WORD_MODELS=hey_spark,spark",
                    "WAKE_WORD_THRESHOLD=0.7",
                    "WAKE_WORD_COOLDOWN_S=1.5",
                ],
            )

            config_path = Path(settings.SHARED_CONFIG_PATH)
            self.assertTrue(config_path.exists())
            payload = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(
                payload["voice_daemon"],
                {
                    "wake_phrases": ["hey spark", "spark"],
                    "wake_models": ["hey_spark", "spark"],
                    "wake_threshold": 0.7,
                    "wake_cooldown_s": 1.5,
                },
            )
            self.assertEqual(settings.WAKE_WORD_PHRASES, ("hey spark", "spark"))
            self.assertEqual(settings.WAKE_WORD_MODELS, ("hey_spark", "spark"))
            self.assertEqual(settings.WAKE_WORD_THRESHOLD, 0.7)
            self.assertEqual(settings.WAKE_WORD_COOLDOWN_S, 1.5)
            self.assertEqual(settings.DAEMON_SERVICE_TOKEN, "test-token")

    def test_shared_config_takes_precedence_over_env_for_wake_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            appdata = root / "appdata"
            appdata.mkdir(parents=True, exist_ok=True)
            config_path = appdata / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "voice_daemon": {
                            "wake_phrases": ["spark"],
                            "wake_models": ["spark"],
                            "wake_threshold": 0.92,
                            "wake_cooldown_s": 3.0,
                        }
                    }
                ),
                encoding="utf-8",
            )

            settings = _load_settings(
                root,
                [
                    "DAEMON_SERVICE_TOKEN=test-token",
                    "WAKE_WORD_PHRASES=env one,env two",
                    "WAKE_WORD_MODELS=env_one,env_two",
                    "WAKE_WORD_THRESHOLD=0.4",
                    "WAKE_WORD_COOLDOWN_S=0.2",
                ],
            )

            self.assertEqual(settings.WAKE_WORD_PHRASES, ("spark",))
            self.assertEqual(settings.WAKE_WORD_MODELS, ("spark",))
            self.assertEqual(settings.WAKE_WORD_THRESHOLD, 0.92)
            self.assertEqual(settings.WAKE_WORD_COOLDOWN_S, 3.0)
            self.assertEqual(settings.DAEMON_SERVICE_TOKEN, "test-token")


if __name__ == "__main__":
    unittest.main()
