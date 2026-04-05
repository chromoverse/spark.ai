import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from tools.tools.file_system.operations import FileOpenTool
    from tools.utils.path_resolver.path_resolver import PathResolver
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    FileOpenTool = None  # type: ignore[assignment]
    PathResolver = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"File open imports unavailable: {_IMPORT_ERROR}")
class PathResolverWindowsFolderTests(unittest.TestCase):
    def test_windows_downloads_uses_user_shell_folder_registry(self):
        with (
            patch.dict(os.environ, {"USERPROFILE": r"C:\Users\Tester"}, clear=False),
            patch("tools.utils.path_resolver.path_resolver.platform.system", return_value="Windows"),
            patch.object(
                PathResolver,
                "_read_windows_user_shell_folders",
                return_value={
                    "{374DE290-123F-4565-9164-39C4925E467B}": r"%USERPROFILE%\OneDrive\Downloads",
                },
            ),
        ):
            resolver = PathResolver()

        self.assertEqual(
            str(resolver.known_folders["Downloads"]),
            r"C:\Users\Tester\OneDrive\Downloads",
        )
        resolved, success, error = resolver.resolve("downloads")
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(resolved, r"C:\Users\Tester\OneDrive\Downloads")


@unittest.skipIf(_IMPORT_ERROR is not None, f"File open imports unavailable: {_IMPORT_ERROR}")
class FileOpenToolResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_open_searches_user_paths_when_simple_name_is_not_literal(self):
        fake_resolver = SimpleNamespace(
            home=Path(r"C:\Users\Tester"),
            known_folders={"Downloads": Path(r"C:\Users\Tester\OneDrive\Downloads")},
            FOLDER_ALIASES={"downloads": "Downloads"},
            resolve=lambda path, must_exist=False: (r"D:\workspace\Downloads", True, None),
        )

        with (
            patch("tools.tools.file_system.operations.get_path_resolver", return_value=fake_resolver),
            patch(
                "tools.tools.file_system.operations._search_user_paths",
                return_value=r"C:\Users\Tester\OneDrive\Downloads",
            ),
            patch(
                "tools.tools.file_system.operations.os.path.exists",
                side_effect=lambda path: path == r"C:\Users\Tester\OneDrive\Downloads",
            ),
            patch("tools.tools.file_system.operations._shell_open_path") as shell_open,
        ):
            result = await FileOpenTool().execute({"path": "Downloads"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["absolute_path"], r"C:\Users\Tester\OneDrive\Downloads")
        shell_open.assert_called_once_with(r"C:\Users\Tester\OneDrive\Downloads")

    async def test_file_open_allows_shell_targets_without_filesystem_lookup(self):
        with patch("tools.tools.file_system.operations._shell_open_path") as shell_open:
            result = await FileOpenTool().execute({"path": "shell:Downloads"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["absolute_path"], "shell:Downloads")
        shell_open.assert_called_once_with("shell:Downloads")


if __name__ == "__main__":
    unittest.main()
