import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from app.path.artifacts import ArtifactStore
    from app.path.manager import PathManager
    from tools.tools.system.screenshot import ScreenshotCaptureTool
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    ArtifactStore = None  # type: ignore[assignment]
    PathManager = None  # type: ignore[assignment]
    ScreenshotCaptureTool = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Artifact imports unavailable: {_IMPORT_ERROR}")
class ArtifactStoreTests(unittest.TestCase):
    def test_path_manager_exposes_grouped_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pm = PathManager(env={"JARVIS_DATA_DIR": temp_dir})

            self.assertEqual(pm.get_layout().user_data_dir, Path(temp_dir))
            self.assertEqual(pm.get_artifact_paths().root, pm.get_artifacts_dir())
            self.assertEqual(pm.get_tool_paths().registry_file, pm.get_tools_registry_file())

    def test_register_and_list_artifact_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pm = PathManager(env={"JARVIS_DATA_DIR": temp_dir})
            store = ArtifactStore(path_manager=pm)
            screenshot_dir = pm.get_screenshots_dir(user_id="u1")
            file_path = screenshot_dir / "example.txt"
            file_path.write_text("artifact", encoding="utf-8")

            record = store.register_file(
                kind="screenshot",
                tool_name="screenshot_capture",
                file_path=file_path,
                user_id="u1",
                task_id="task_1",
            )

            self.assertEqual(record.kind, "screenshot")
            self.assertTrue(store.resolve_artifact_path(record).exists())

            listed = store.list_artifacts(kind="screenshot", user_id="u1", latest_only=True)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].artifact_id, record.artifact_id)

    def test_screenshot_tool_uses_managed_path_and_creates_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pm = PathManager(env={"JARVIS_DATA_DIR": temp_dir})
            store = ArtifactStore(path_manager=pm)

            def fake_capture(_self, _target, save_path):
                path = Path(save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-png")
                return str(path), "100x100"

            with (
                patch("tools.tools.system.screenshot.PathManager", return_value=pm),
                patch("tools.tools.system.screenshot.get_artifact_store", return_value=store),
                patch.object(ScreenshotCaptureTool, "_capture_screenshot", fake_capture),
            ):
                result = asyncio.run(ScreenshotCaptureTool().execute({"_user_id": "u1"}))

            self.assertTrue(result.success)
            self.assertIn(temp_dir, result.data["file_path"])
            self.assertIn("artifact_id", result.data)
            record = store.get_artifact(result.data["artifact_id"])
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.user_id, "u1")


if __name__ == "__main__":
    unittest.main()
