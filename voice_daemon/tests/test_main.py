from __future__ import annotations

import asyncio
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


def _prepare_environment(temp_root: Path):
    env_path = temp_root / ".env.test"
    env_path.write_text("DAEMON_SERVICE_TOKEN=test-token\n", encoding="utf-8")
    models_dir = temp_root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "hey_spark.onnx").write_bytes(b"fake-model-1")
    (models_dir / "spark.onnx").write_bytes(b"fake-model-2")

    env = {
        "SPARK_ENV_PATH": str(env_path),
        "JARVIS_DATA_DIR": str(temp_root / "appdata"),
        "MODELS_DIR": str(models_dir),
    }

    with mock.patch.dict(os.environ, env, clear=True):
        import config.settings as settings
        import main as daemon_main

        settings = importlib.reload(settings)
        daemon_main = importlib.reload(daemon_main)
        return settings, daemon_main


class FakeSio:
    def on(self, *_args, **_kwargs):
        return None


class MainSmokeTests(unittest.TestCase):
    def test_main_logs_shared_config_and_wake_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings, daemon_main = _prepare_environment(root)

            fake_wait_for_server = types.ModuleType("health.server_watch")

            async def wait_for_server():
                return True

            fake_wait_for_server.wait_for_server = wait_for_server

            wake_word_calls: list[str] = []
            fake_wake_word = types.ModuleType("core.wake_word")
            fake_wake_word.wake_word_detector = types.SimpleNamespace(
                load=lambda: wake_word_calls.append("wake"),
            )

            vad_calls: list[str] = []
            fake_vad = types.ModuleType("core.vad")
            fake_vad.vad = types.SimpleNamespace(load=lambda: vad_calls.append("vad"))

            mic_calls: list[str] = []
            fake_mic = types.ModuleType("core.mic")
            fake_mic.mic = types.SimpleNamespace(start=lambda _loop: mic_calls.append("start"))

            socket_calls: list[str] = []
            fake_socket_client = types.ModuleType("stream.socket_client")

            async def connect():
                socket_calls.append("connect")

            async def wait():
                socket_calls.append("wait")

            fake_socket_client.socket_client = types.SimpleNamespace(
                connect=connect,
                wait=wait,
                _sio=FakeSio(),
            )

            tts_calls: list[str] = []
            fake_tts_player = types.ModuleType("playback.tts_player")

            async def start():
                tts_calls.append("start")

            fake_tts_player.tts_player = types.SimpleNamespace(
                register=lambda: tts_calls.append("register"),
                start=start,
            )

            with mock.patch.dict(
                sys.modules,
                {
                    "health.server_watch": fake_wait_for_server,
                    "core.wake_word": fake_wake_word,
                    "core.vad": fake_vad,
                    "core.mic": fake_mic,
                    "stream.socket_client": fake_socket_client,
                    "playback.tts_player": fake_tts_player,
                },
            ):
                with self.assertLogs("voice_daemon", level="INFO") as logs:
                    asyncio.run(daemon_main.main())

            joined_logs = "\n".join(logs.output)
            self.assertIn(str(settings.SHARED_CONFIG_PATH), joined_logs)
            self.assertIn("hey spark, spark", joined_logs)
            self.assertIn('Say "hey spark or spark" to activate', joined_logs)
            self.assertEqual(wake_word_calls, ["wake"])
            self.assertEqual(vad_calls, ["vad"])
            self.assertEqual(mic_calls, ["start"])
            self.assertEqual(socket_calls, ["connect", "wait"])
            self.assertEqual(tts_calls, ["register", "start"])


if __name__ == "__main__":
    unittest.main()
