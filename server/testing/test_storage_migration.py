import tempfile
import unittest
from pathlib import Path

try:
    from app.path.manager import PathManager
    from scripts.migrate_storage_layout import inspect_storage_layout, migrate_storage_layout
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    PathManager = None  # type: ignore[assignment]
    inspect_storage_layout = None  # type: ignore[assignment]
    migrate_storage_layout = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


def _build_path_manager(primary_root: str, fallback_root: str, server_root: str) -> "PathManager":
    path_manager = PathManager(
        env={
            "JARVIS_DATA_DIR": primary_root,
            "JARVIS_SERVER_DIR": server_root,
        }
    )
    path_manager._fallback_user_data_dir = Path(fallback_root)  # type: ignore[attr-defined]
    path_manager._using_fallback_user_data_dir = False  # type: ignore[attr-defined]
    return path_manager


@unittest.skipIf(_IMPORT_ERROR is not None, f"Storage migration imports unavailable: {_IMPORT_ERROR}")
class StorageMigrationTests(unittest.TestCase):
    def test_dry_run_reports_pending_migration_without_touching_files(self):
        with tempfile.TemporaryDirectory() as temp_root:
            primary_root = Path(temp_root) / "primary"
            fallback_root = Path(temp_root) / "fallback"
            server_root = Path(temp_root) / "server"
            server_root.mkdir(parents=True, exist_ok=True)
            source_file = fallback_root / "models" / "voice.bin"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("model-data", encoding="utf-8")

            path_manager = _build_path_manager(str(primary_root), str(fallback_root), str(server_root))
            result = migrate_storage_layout(path_manager=path_manager, apply=False)

            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["totals"]["files_to_migrate"], 1)
            self.assertTrue(source_file.exists())
            self.assertFalse((primary_root / "models" / "voice.bin").exists())

    def test_apply_moves_missing_files_and_removes_verified_source(self):
        with tempfile.TemporaryDirectory() as temp_root:
            primary_root = Path(temp_root) / "primary"
            fallback_root = Path(temp_root) / "fallback"
            server_root = Path(temp_root) / "server"
            server_root.mkdir(parents=True, exist_ok=True)
            source_file = fallback_root / "db" / "kvstore.db"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("sqlite-bytes", encoding="utf-8")

            path_manager = _build_path_manager(str(primary_root), str(fallback_root), str(server_root))
            result = migrate_storage_layout(path_manager=path_manager, apply=True)

            target_file = primary_root / "db" / "kvstore.db"
            self.assertTrue(target_file.exists())
            self.assertEqual(target_file.read_text(encoding="utf-8"), "sqlite-bytes")
            self.assertFalse(source_file.exists())
            self.assertEqual(result["totals"]["migrated_files"], 1)
            self.assertIn("migrated_file", [item["action"] for item in result["operations"]])

    def test_apply_skips_existing_target_files_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp_root:
            primary_root = Path(temp_root) / "primary"
            fallback_root = Path(temp_root) / "fallback"
            server_root = Path(temp_root) / "server"
            server_root.mkdir(parents=True, exist_ok=True)

            source_file = fallback_root / "logs" / "server.log"
            target_file = primary_root / "logs" / "server.log"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("fallback-log", encoding="utf-8")
            target_file.write_text("primary-log", encoding="utf-8")

            path_manager = _build_path_manager(str(primary_root), str(fallback_root), str(server_root))
            result = migrate_storage_layout(path_manager=path_manager, apply=True)

            self.assertTrue(source_file.exists())
            self.assertEqual(source_file.read_text(encoding="utf-8"), "fallback-log")
            self.assertEqual(target_file.read_text(encoding="utf-8"), "primary-log")
            self.assertIn("skipped_existing", [item["action"] for item in result["operations"]])
            self.assertEqual(result["totals"]["migrated_files"], 0)

    def test_tools_plugin_cleanup_is_reported_in_dry_run_and_removed_on_apply(self):
        with tempfile.TemporaryDirectory() as temp_root:
            primary_root = Path(temp_root) / "primary"
            fallback_root = Path(temp_root) / "fallback"
            server_root = Path(temp_root) / "server"
            server_root.mkdir(parents=True, exist_ok=True)

            tools_plugin_file = primary_root / "tools_plugin" / "stale.txt"
            tools_plugin_file.parent.mkdir(parents=True, exist_ok=True)
            tools_plugin_file.write_text("stale", encoding="utf-8")

            path_manager = _build_path_manager(str(primary_root), str(fallback_root), str(server_root))
            dry_run = inspect_storage_layout(path_manager=path_manager, cleanup_tools_plugin=True)
            self.assertTrue(dry_run["cleanup"]["eligible"])
            self.assertTrue(tools_plugin_file.exists())

            applied = migrate_storage_layout(
                path_manager=path_manager,
                apply=True,
                cleanup_tools_plugin=True,
            )

            self.assertFalse((primary_root / "tools_plugin").exists())
            self.assertIn("removed_tools_plugin", [item["action"] for item in applied["operations"]])


if __name__ == "__main__":
    unittest.main()
