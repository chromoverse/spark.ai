from __future__ import annotations

"""Safely migrate SparkAI runtime data into the canonical storage layout.

This utility treats the requested user data directory as the canonical root and
the repo-local `.sparkai_data` directory as fallback-only storage. By default it
reports what would be migrated. `--apply` performs verified file-by-file moves
for missing data only and optionally removes stale `tools_plugin` content.
"""

import argparse
import filecmp
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


from app.path.manager import PathManager


MANAGED_STORAGE_DIRS = (
    "db",
    "memory",
    "models",
    "binaries",
    "artifacts",
    "logs",
)


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _directory_status(
    *,
    source_exists: bool,
    files_to_migrate: List[str],
    skipped_existing: List[str],
    conflicts: List[str],
    empty_source: bool,
) -> str:
    if not source_exists:
        return "source_missing"
    if empty_source and not files_to_migrate and not skipped_existing and not conflicts:
        return "empty_source"
    if files_to_migrate and conflicts:
        return "partial_conflicts"
    if conflicts and not files_to_migrate:
        return "conflicts_only"
    if files_to_migrate:
        return "ready_to_migrate"
    if skipped_existing:
        return "already_present"
    return "up_to_date"


def _scan_directory(source_dir: Path, target_dir: Path) -> Dict[str, Any]:
    files_to_migrate: List[str] = []
    skipped_existing: List[str] = []
    conflicts: List[str] = []

    source_exists = source_dir.exists()
    if not source_exists:
        return {
            "name": source_dir.name,
            "source": str(source_dir),
            "target": str(target_dir),
            "source_exists": False,
            "empty_source": False,
            "files_to_migrate": files_to_migrate,
            "skipped_existing": skipped_existing,
            "conflicts": conflicts,
            "status": "source_missing",
        }

    if source_dir.is_file():
        conflicts.append(source_dir.name)
        return {
            "name": source_dir.name,
            "source": str(source_dir),
            "target": str(target_dir),
            "source_exists": True,
            "empty_source": False,
            "files_to_migrate": files_to_migrate,
            "skipped_existing": skipped_existing,
            "conflicts": conflicts,
            "status": "conflicts_only",
        }

    saw_any_entries = False
    for current_root, dirnames, filenames in os.walk(source_dir):
        current_path = Path(current_root)
        rel_root = current_path.relative_to(source_dir)
        saw_any_entries = saw_any_entries or bool(dirnames or filenames)

        filtered_dirnames: List[str] = []
        for dirname in dirnames:
            target_candidate = target_dir / rel_root / dirname
            if target_candidate.exists() and not target_candidate.is_dir():
                conflicts.append((rel_root / dirname).as_posix())
                continue
            filtered_dirnames.append(dirname)
        dirnames[:] = filtered_dirnames

        for filename in filenames:
            source_file = current_path / filename
            rel_path = source_file.relative_to(source_dir)
            target_file = target_dir / rel_path

            if target_file.exists():
                skipped_existing.append(rel_path.as_posix())
                continue

            files_to_migrate.append(rel_path.as_posix())

    empty_source = not saw_any_entries
    return {
        "name": source_dir.name,
        "source": str(source_dir),
        "target": str(target_dir),
        "source_exists": True,
        "empty_source": empty_source,
        "files_to_migrate": files_to_migrate,
        "skipped_existing": skipped_existing,
        "conflicts": conflicts,
        "status": _directory_status(
            source_exists=True,
            files_to_migrate=files_to_migrate,
            skipped_existing=skipped_existing,
            conflicts=conflicts,
            empty_source=empty_source,
        ),
    }


def inspect_storage_layout(
    path_manager: PathManager | None = None,
    *,
    cleanup_tools_plugin: bool = False,
) -> Dict[str, Any]:
    pm = path_manager or PathManager()
    primary_root = pm.get_requested_user_data_dir()
    fallback_root = pm.get_fallback_user_data_dir()
    active_root = pm.get_user_data_dir()

    assessments = [
        _scan_directory(fallback_root / name, primary_root / name)
        for name in MANAGED_STORAGE_DIRS
    ]

    tools_plugin_path = primary_root / "tools_plugin"
    cleanup = {
        "requested": cleanup_tools_plugin,
        "path": str(tools_plugin_path),
        "exists": tools_plugin_path.exists(),
        "eligible": cleanup_tools_plugin and tools_plugin_path.exists(),
    }

    totals = {
        "managed_dirs": len(assessments),
        "files_to_migrate": sum(len(item["files_to_migrate"]) for item in assessments),
        "skipped_existing": sum(len(item["skipped_existing"]) for item in assessments),
        "conflicts": sum(len(item["conflicts"]) for item in assessments),
    }

    warnings: List[str] = []
    if primary_root.resolve() == fallback_root.resolve():
        warnings.append("Primary and fallback roots resolve to the same path; nothing to migrate.")
    if pm.is_using_fallback_user_data_dir():
        warnings.append("Runtime is currently using fallback storage because the primary root was not writable.")

    return {
        "mode": "dry-run",
        "primary_root": str(primary_root),
        "fallback_root": str(fallback_root),
        "active_root": str(active_root),
        "using_fallback_root": pm.is_using_fallback_user_data_dir(),
        "managed_directories": assessments,
        "cleanup": cleanup,
        "totals": totals,
        "warnings": warnings,
        "operations": [],
    }


def _verify_copy(source_file: Path, target_file: Path) -> bool:
    return target_file.exists() and filecmp.cmp(source_file, target_file, shallow=False)


def _remove_empty_directories(root: Path) -> List[str]:
    removed: List[str] = []
    if not root.exists() or not root.is_dir():
        return removed

    for current_root, dirnames, filenames in os.walk(root, topdown=False):
        if dirnames or filenames:
            continue
        current_path = Path(current_root)
        if current_path == root:
            continue
        current_path.rmdir()
        removed.append(str(current_path))

    return removed


def migrate_storage_layout(
    path_manager: PathManager | None = None,
    *,
    apply: bool = False,
    cleanup_tools_plugin: bool = False,
) -> Dict[str, Any]:
    summary = inspect_storage_layout(
        path_manager=path_manager,
        cleanup_tools_plugin=cleanup_tools_plugin,
    )
    summary["mode"] = "apply" if apply else "dry-run"
    if not apply:
        return summary

    primary_root = Path(summary["primary_root"])
    fallback_root = Path(summary["fallback_root"])
    operations: List[Dict[str, Any]] = []

    primary_root.mkdir(parents=True, exist_ok=True)

    if primary_root.resolve() != fallback_root.resolve():
        for directory_summary in summary["managed_directories"]:
            source_dir = Path(directory_summary["source"])
            target_dir = Path(directory_summary["target"])
            if not source_dir.exists() or not source_dir.is_dir():
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            for rel_text in directory_summary["conflicts"]:
                operations.append(
                    {
                        "action": "conflict",
                        "path": rel_text,
                        "source": str(source_dir / Path(rel_text)),
                        "target": str(target_dir / Path(rel_text)),
                    }
                )

            for rel_text in directory_summary["skipped_existing"]:
                operations.append(
                    {
                        "action": "skipped_existing",
                        "path": rel_text,
                        "source": str(source_dir / Path(rel_text)),
                        "target": str(target_dir / Path(rel_text)),
                    }
                )

            for rel_text in directory_summary["files_to_migrate"]:
                source_file = source_dir / Path(rel_text)
                target_file = target_dir / Path(rel_text)
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)
                if not _verify_copy(source_file, target_file):
                    target_file.unlink(missing_ok=True)
                    operations.append(
                        {
                            "action": "verify_failed",
                            "path": rel_text,
                            "source": str(source_file),
                            "target": str(target_file),
                        }
                    )
                    continue

                source_file.unlink()
                operations.append(
                    {
                        "action": "migrated_file",
                        "path": rel_text,
                        "source": str(source_file),
                        "target": str(target_file),
                    }
                )

            for removed_dir in _remove_empty_directories(source_dir):
                operations.append(
                    {
                        "action": "removed_empty_dir",
                        "path": removed_dir,
                    }
                )

    cleanup = summary["cleanup"]
    if cleanup_tools_plugin and cleanup["exists"]:
        tools_plugin_path = Path(cleanup["path"])
        if not _is_within_root(tools_plugin_path, primary_root):
            raise RuntimeError(f"Refusing to delete path outside primary root: {tools_plugin_path}")
        shutil.rmtree(tools_plugin_path)
        operations.append(
            {
                "action": "removed_tools_plugin",
                "path": str(tools_plugin_path),
            }
        )

    summary["operations"] = operations
    summary["totals"] = {
        **summary["totals"],
        "migrated_files": sum(1 for item in operations if item["action"] == "migrated_file"),
        "verify_failed": sum(1 for item in operations if item["action"] == "verify_failed"),
        "removed_empty_dirs": sum(1 for item in operations if item["action"] == "removed_empty_dir"),
        "removed_tools_plugin": sum(1 for item in operations if item["action"] == "removed_tools_plugin"),
    }
    return summary


def _json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or safely migrate SparkAI storage into the canonical layout.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned migration work without changing files (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Perform verified file-by-file migration for missing data.",
    )
    parser.add_argument(
        "--cleanup-tools-plugin",
        action="store_true",
        help="Also remove stale AppData tools_plugin content after migration.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = migrate_storage_layout(
        apply=bool(args.apply),
        cleanup_tools_plugin=bool(args.cleanup_tools_plugin),
    )
    sys.stdout.write(_json_dump(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
