import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

try:
    from app.path.artifacts import ArtifactStore
    from app.path.manager import PathManager
    from tools.tools.file_system.operations import FileCreateTool
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    ArtifactStore = None  # type: ignore[assignment]
    PathManager = None  # type: ignore[assignment]
    FileCreateTool = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@contextmanager
def _pushd(path: str):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _build_path_manager(data_root: str, server_root: str) -> "PathManager":
    return PathManager(
        env={
            "JARVIS_DATA_DIR": data_root,
            "JARVIS_SERVER_DIR": server_root,
        }
    )


@unittest.skipIf(_IMPORT_ERROR is not None, f"FileCreateTool imports unavailable: {_IMPORT_ERROR}")
class FileCreateArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_bare_filename_redirects_into_documents_artifact_dir(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_root = Path(temp_root) / "data"
            server_root = Path(temp_root) / "server"
            work_root = Path(temp_root) / "work"
            server_root.mkdir(parents=True, exist_ok=True)
            work_root.mkdir(parents=True, exist_ok=True)

            path_manager = _build_path_manager(str(data_root), str(server_root))
            artifact_store = ArtifactStore(path_manager=path_manager)

            with (
                _pushd(str(work_root)),
                patch("app.path.manager.PathManager", return_value=path_manager),
                patch("app.path.artifacts.get_artifact_store", return_value=artifact_store),
            ):
                result = await FileCreateTool().execute(
                    {
                        "path": "weekly_plan.txt",
                        "content": "finish the sprint",
                        "_user_id": "u1",
                    }
                )

            self.assertTrue(result.success)
            absolute_path = Path(result.data["absolute_path"])
            self.assertEqual(absolute_path.parent, path_manager.get_artifact_dir("documents", "u1"))
            self.assertEqual(absolute_path.read_text(encoding="utf-8"), "finish the sprint")
            self.assertEqual(result.data["artifact_kind"], "document")

            record = artifact_store.get_artifact(result.data["artifact_id"])
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.user_id, "u1")
            self.assertIn("artifacts/documents/u1/weekly_plan.txt", record.relative_path.replace("\\", "/"))

    async def test_relative_path_redirects_and_keeps_basename_only(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_root = Path(temp_root) / "data"
            server_root = Path(temp_root) / "server"
            work_root = Path(temp_root) / "work"
            server_root.mkdir(parents=True, exist_ok=True)
            work_root.mkdir(parents=True, exist_ok=True)

            path_manager = _build_path_manager(str(data_root), str(server_root))
            artifact_store = ArtifactStore(path_manager=path_manager)

            with (
                _pushd(str(work_root)),
                patch("app.path.manager.PathManager", return_value=path_manager),
                patch("app.path.artifacts.get_artifact_store", return_value=artifact_store),
            ):
                result = await FileCreateTool().execute(
                    {
                        "path": "notes/weekly_plan.txt",
                        "content": "keep it tidy",
                        "_user_id": "u1",
                    }
                )

            self.assertTrue(result.success)
            absolute_path = Path(result.data["absolute_path"])
            self.assertEqual(absolute_path.parent, path_manager.get_artifact_dir("documents", "u1"))
            self.assertEqual(absolute_path.name, "weekly_plan.txt")

    async def test_server_absolute_path_is_redirected_out_of_server_tree(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_root = Path(temp_root) / "data"
            server_root = Path(temp_root) / "server"
            server_root.mkdir(parents=True, exist_ok=True)

            path_manager = _build_path_manager(str(data_root), str(server_root))
            artifact_store = ArtifactStore(path_manager=path_manager)
            requested_path = server_root / "scratch" / "inside_server.txt"

            with (
                patch("app.path.manager.PathManager", return_value=path_manager),
                patch("app.path.artifacts.get_artifact_store", return_value=artifact_store),
            ):
                result = await FileCreateTool().execute(
                    {
                        "path": str(requested_path),
                        "content": "should redirect",
                        "_user_id": "u1",
                    }
                )

            self.assertTrue(result.success)
            absolute_path = Path(result.data["absolute_path"])
            self.assertNotEqual(absolute_path, requested_path)
            self.assertEqual(absolute_path.parent, path_manager.get_artifact_dir("documents", "u1"))
            self.assertFalse(requested_path.exists())

    async def test_explicit_absolute_path_outside_server_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_root = Path(temp_root) / "data"
            server_root = Path(temp_root) / "server"
            explicit_path = Path(temp_root) / "user_notes" / "manual.txt"
            server_root.mkdir(parents=True, exist_ok=True)

            path_manager = _build_path_manager(str(data_root), str(server_root))
            artifact_store = ArtifactStore(path_manager=path_manager)

            with (
                patch("app.path.manager.PathManager", return_value=path_manager),
                patch("app.path.artifacts.get_artifact_store", return_value=artifact_store),
            ):
                result = await FileCreateTool().execute(
                    {
                        "path": str(explicit_path),
                        "content": "write exactly here",
                        "_user_id": "u1",
                    }
                )

            self.assertTrue(result.success)
            self.assertEqual(Path(result.data["absolute_path"]), explicit_path.resolve())
            self.assertEqual(explicit_path.read_text(encoding="utf-8"), "write exactly here")

            record = artifact_store.get_artifact(result.data["artifact_id"])
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(artifact_store.resolve_artifact_path(record), explicit_path.resolve())

    async def test_existing_redirected_file_requires_overwrite_true(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_root = Path(temp_root) / "data"
            server_root = Path(temp_root) / "server"
            work_root = Path(temp_root) / "work"
            server_root.mkdir(parents=True, exist_ok=True)
            work_root.mkdir(parents=True, exist_ok=True)

            path_manager = _build_path_manager(str(data_root), str(server_root))
            artifact_store = ArtifactStore(path_manager=path_manager)

            with (
                _pushd(str(work_root)),
                patch("app.path.manager.PathManager", return_value=path_manager),
                patch("app.path.artifacts.get_artifact_store", return_value=artifact_store),
            ):
                first = await FileCreateTool().execute(
                    {
                        "path": "weekly_plan.txt",
                        "content": "first version",
                        "_user_id": "u1",
                    }
                )
                second = await FileCreateTool().execute(
                    {
                        "path": "weekly_plan.txt",
                        "content": "second version",
                        "_user_id": "u1",
                    }
                )

            self.assertTrue(first.success)
            self.assertFalse(second.success)
            self.assertIn("File already exists", second.error or "")
            redirected_path = Path(first.data["absolute_path"])
            self.assertEqual(redirected_path.read_text(encoding="utf-8"), "first version")


if __name__ == "__main__":
    unittest.main()
