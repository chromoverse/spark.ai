# client_core/tools/file_system/operations.py
"""
File System Operations Tools for Client

Real file system tools that execute on the client machine.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput
from app.path.manager import PathManager
from tools.utils.path_resolver import get_path_resolver


def _expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _shell_open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _normalize_open_query(path: str) -> str:
    query = str(path or "").strip().strip('"\'')
    query = re.sub(r"\s+", " ", query)
    cleaned = re.sub(r"\b(folder|directory|file)\b$", "", query, flags=re.IGNORECASE).strip()
    return cleaned or query


def _normalized_name_variants(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if not normalized:
        return set()

    variants = {normalized}
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular:
            variants.add(singular)
    else:
        variants.add(f"{normalized}s")
    return variants


def _name_matches(candidate_name: str, query: str, *, exact_only: bool) -> bool:
    candidate_variants = _normalized_name_variants(candidate_name)
    query_variants = _normalized_name_variants(query)
    if not candidate_variants or not query_variants:
        return False

    if candidate_variants & query_variants:
        return True
    if exact_only:
        return False

    return any(
        query_variant in candidate_variant or candidate_variant in query_variant
        for candidate_variant in candidate_variants
        for query_variant in query_variants
    )


def _looks_like_explicit_path(path: str) -> bool:
    drive, _ = os.path.splitdrive(path)
    return bool(drive) or path.startswith(("~", ".", "..")) or "/" in path or "\\" in path


def _is_user_anchored_path(path: str) -> bool:
    """Return True when a create target is anchored outside the server cwd."""
    candidate = str(path or "").strip().strip('"\'')
    if not candidate:
        return False
    if candidate.startswith("~"):
        return True
    return os.path.isabs(os.path.expanduser(candidate))


def _is_special_open_target(path: str) -> bool:
    lowered = str(path or "").strip().lower()
    return lowered.startswith("shell:") or lowered.startswith("ms-settings:") or lowered.startswith("::{")


def _get_open_search_roots() -> list[Path]:
    resolver = get_path_resolver()
    ordered_roots: list[Path] = []
    seen: set[str] = set()

    for folder_name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        candidate = resolver.known_folders.get(folder_name)
        if candidate is None:
            continue
        candidate_text = str(candidate)
        if candidate_text.lower() in seen or not os.path.isdir(candidate_text):
            continue
        ordered_roots.append(candidate)
        seen.add(candidate_text.lower())

    home_text = str(resolver.home)
    if home_text.lower() not in seen and os.path.isdir(home_text):
        ordered_roots.append(resolver.home)

    return ordered_roots


def _walk_for_named_match(root: Path, query: str, *, want_dirs: bool, exact_only: bool, max_depth: int = 6) -> str | None:
    root_text = str(root)
    if want_dirs and _name_matches(root.name, query, exact_only=exact_only):
        return root_text

    for current_root, dirnames, filenames in os.walk(root_text):
        relative_path = os.path.relpath(current_root, root_text)
        depth = 0 if relative_path == "." else relative_path.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []

        names = dirnames if want_dirs else filenames
        for name in names:
            if _name_matches(name, query, exact_only=exact_only):
                return os.path.join(current_root, name)

    return None


def _candidate_open_queries(path: str) -> list[str]:
    query = _normalize_open_query(path)
    if not query:
        return []

    resolver = get_path_resolver()
    candidates: list[str] = []

    def add(value: str) -> None:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    add(query)
    alias_target = resolver.FOLDER_ALIASES.get(query.lower())
    if alias_target:
        add(alias_target)

    normalized = query.strip()
    if normalized.lower().endswith("s") and len(normalized) > 1:
        add(normalized[:-1])
    elif normalized.isalpha():
        add(f"{normalized}s")

    return candidates


def _search_user_paths(path: str) -> str | None:
    query_candidates = _candidate_open_queries(path)
    if not query_candidates:
        return None

    roots = _get_open_search_roots()
    if not roots:
        return None

    search_dirs_first = not (Path(query_candidates[0]).suffix or any(ch in query_candidates[0] for ch in "*?"))
    search_order = [True, False] if search_dirs_first else [False, True]

    for exact_only in (True, False):
        for query in query_candidates:
            for want_dirs in search_order:
                for root in roots:
                    match = _walk_for_named_match(
                        root,
                        query,
                        want_dirs=want_dirs,
                        exact_only=exact_only,
                    )
                    if match:
                        return match

    return None


def _resolve_open_target_path(path: str) -> tuple[str, bool, str | None]:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return "", False, "Path is required"

    cleaned_path = normalized_path.strip('"\'')
    if _is_special_open_target(cleaned_path):
        return cleaned_path, True, None

    resolver = get_path_resolver()
    resolved_path, success, error = resolver.resolve(cleaned_path, must_exist=False)

    if success and os.path.exists(resolved_path):
        return resolved_path, True, None

    if not _looks_like_explicit_path(cleaned_path):
        search_hit = _search_user_paths(cleaned_path)
        if search_hit:
            return search_hit, True, None

    fallback_path = resolved_path if success else _expand_path(cleaned_path)
    return fallback_path, False, error or f"Path not found: {path}"


class FileCreateTool(BaseTool):
    """Create file tool.

    Inputs:
    - path (string, required)
    - content (string, optional)
    - overwrite (boolean, optional)

    Outputs:
    - file_path (string)
    - absolute_path (string)
    - size_bytes (integer)
    - created_at (string)
    - artifact_id (string): artifact record ID for later retrieval
    - artifact_kind (string): "documents"
    """

    def get_tool_name(self) -> str:
        return "file_create"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Create a file with content, storing it as a managed artifact."""
        path = inputs.get("path", "")
        content = inputs.get("content", "")
        overwrite = inputs.get("overwrite", False)
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        task_id = str(inputs.get("_task_id") or "").strip()

        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")

        try:
            requested_path = str(path).strip().strip('"\'')
            expanded_path = os.path.expanduser(requested_path)
            resolved_path = os.path.abspath(expanded_path)

            # Redirect ambiguous paths and any target inside the server tree
            # into the managed artifact store.
            if self._should_redirect(requested_path, resolved_path):
                from app.path.manager import PathManager as _PM
                filename = os.path.basename(resolved_path) or "untitled.txt"
                artifact_dir = _PM().get_artifact_dir("documents", user_id)
                resolved_path = str(artifact_dir / filename)
                self.logger.info(
                    "Redirected '%s' -> '%s' (artifact store)", path, resolved_path
                )

            if os.path.exists(resolved_path) and not overwrite:
                return ToolOutput(
                    success=False, data={},
                    error=f"File already exists: {resolved_path}"
                )

            parent_dir = os.path.dirname(resolved_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(resolved_path, 'w', encoding='utf-8') as f:
                f.write(content)

            file_stat = os.stat(resolved_path)

            # Register as artifact for later retrieval
            from app.path.artifacts import get_artifact_store
            label = Path(resolved_path).stem.replace("_", " ").replace("-", " ")
            artifact = get_artifact_store().register_file(
                kind="document",
                tool_name=self.get_tool_name(),
                file_path=resolved_path,
                user_id=user_id,
                task_id=task_id,
                label=label,
                metadata={
                    "original_path": requested_path,
                    "title": label,
                    "content_length": len(content),
                },
            )

            self.logger.info(
                "Created file: %s (%d bytes) -> artifact %s",
                resolved_path, file_stat.st_size, artifact.artifact_id,
            )

            return ToolOutput(
                success=True,
                data={
                    "file_path": requested_path,
                    "path": requested_path,
                    "absolute_path": resolved_path,
                    "size_bytes": file_stat.st_size,
                    "created_at": datetime.now().isoformat(),
                    "content_length": len(content),
                    "artifact_id": artifact.artifact_id,
                    "artifact_kind": artifact.kind,
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to create file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    @staticmethod
    def _should_redirect(requested_path: str, resolved_path: str) -> bool:
        """Return True for ambiguous paths or writes that would land inside the server tree."""
        from app.path.manager import PathManager as _PM
        path_manager = _PM()
        server_dir = path_manager.get_server_dir().resolve()
        resolved = Path(resolved_path).resolve()

        try:
            resolved.relative_to(server_dir)
            is_inside_server = True
        except ValueError:
            is_inside_server = False

        is_ambiguous = not _is_user_anchored_path(requested_path)
        return is_inside_server or is_ambiguous


class FolderCreateTool(BaseTool):
    """Create folder tool.

    Inputs:
    - path (string, required)
    - title (string, optional)
    - recursive (boolean, optional)

    Outputs:
    - folder_path (string)
    - created_at (string)
    """

    def get_tool_name(self) -> str:
        return "folder_create"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Create a folder/directory."""
        path = inputs.get("path", "")
        recursive = inputs.get("recursive", True)

        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")

        try:
            expanded_path = os.path.expanduser(path)

            if recursive:
                os.makedirs(expanded_path, exist_ok=True)
            else:
                os.mkdir(expanded_path)

            self.logger.info(f"Created folder: {path}")

            return ToolOutput(
                success=True,
                data={
                    "folder_path": path,
                    "absolute_path": expanded_path,
                    "created_at": datetime.now().isoformat(),
                    "exists": os.path.exists(expanded_path)
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to create folder: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileCopyTool(BaseTool):
    """Copy file tool.

    Inputs:
    - source (string, required)
    - destination (string, required)
    - overwrite (boolean, optional)

    Outputs:
    - source_path (string)
    - destination_path (string)
    - size_bytes (integer)
    - copied_at (string)
    """

    def get_tool_name(self) -> str:
        return "file_copy"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Copy a file."""
        source = inputs.get("source", "")
        destination = inputs.get("destination", "")
        overwrite = inputs.get("overwrite", False)

        if not source or not destination:
            return ToolOutput(
                success=False, data={},
                error="Both source and destination are required"
            )

        try:
            source_path = os.path.expanduser(source)
            dest_path = os.path.expanduser(destination)

            if not os.path.exists(source_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"Source file not found: {source}"
                )

            if os.path.exists(dest_path) and not overwrite:
                return ToolOutput(
                    success=False, data={},
                    error=f"Destination already exists: {destination}"
                )

            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)

            shutil.copy2(source_path, dest_path)

            file_stat = os.stat(dest_path)

            self.logger.info(f"Copied: {source} -> {destination}")

            return ToolOutput(
                success=True,
                data={
                    "source_path": source,
                    "destination_path": destination,
                    "size_bytes": file_stat.st_size,
                    "copied_at": datetime.now().isoformat()
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to copy file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileSearchTool(BaseTool):
    """File search tool.

    Inputs:
    - query (string, required)
    - path (string, optional)
    - max_results (integer, optional)

    Outputs:
    - results (array)
    - total_found (integer)
    - search_time_ms (number)
    """

    def get_tool_name(self) -> str:
        return "file_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Search for files."""
        query = inputs.get("query", "")
        search_path = inputs.get("path", ".")
        max_results = inputs.get("max_results", 50)

        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")

        try:
            expanded_path = os.path.expanduser(search_path)

            if not os.path.exists(expanded_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"Path not found: {search_path}"
                )

            self.logger.info(f"Searching for '{query}' in {search_path}")

            results = []
            query_lower = query.lower()

            for root, dirs, files in os.walk(expanded_path):
                for file in files:
                    if query_lower in file.lower():
                        full_path = os.path.join(root, file)
                        file_stat = os.stat(full_path)

                        results.append({
                            "filename": file,
                            "path": full_path,
                            "size_bytes": file_stat.st_size,
                            "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                        })

                        if len(results) >= max_results:
                            break

                if len(results) >= max_results:
                    break

            self.logger.info(f"Found {len(results)} files")

            return ToolOutput(
                success=True,
                data={
                    "results": results,
                    "total_found": len(results),
                    "search_time_ms": 100,
                    "query": query,
                    "search_path": search_path
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to search files: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileReadTool(BaseTool):
    """Read file tool.

    Inputs:
    - path (string, required)

    Outputs:
    - content (string)
    - size_bytes (integer)
    - path (string)
    """

    def get_tool_name(self) -> str:
        return "file_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Read a file."""
        path = inputs.get("path", "")

        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")

        try:
            expanded_path = os.path.expanduser(path)

            if not os.path.exists(expanded_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"File not found: {path}"
                )

            with open(expanded_path, 'r', encoding='utf-8') as f:
                content = f.read()

            file_stat = os.stat(expanded_path)

            self.logger.info(f"Read file: {path} ({len(content)} bytes)")

            return ToolOutput(
                success=True,
                data={
                    "path": path,
                    "absolute_path": expanded_path,
                    "content": content,
                    "size_bytes": file_stat.st_size,
                    "bytes_read": len(content)
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to read file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileOpenTool(BaseTool):
    """Open a file, folder, or Windows shell target with the default app.

    Inputs:
    - path (string, required)
    - app (string, optional): explicit app to open with

    Outputs:
    - file_path (string)
    - absolute_path (string)
    - opened_with (string)
    - opened_at (string)
    """

    def get_tool_name(self) -> str:
        return "file_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        path = inputs.get("path", "")
        app = inputs.get("app", "")

        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")

        try:
            resolved_path, success, error = _resolve_open_target_path(path)

            if not success:
                return ToolOutput(success=False, data={}, error=error or f"Path not found: {path}")

            if app:
                subprocess.Popen([str(app), resolved_path])
                opened_with = str(app)
            else:
                _shell_open_path(resolved_path)
                opened_with = "default"

            return ToolOutput(
                success=True,
                data={
                    "file_path": path,
                    "absolute_path": resolved_path,
                    "opened_with": opened_with,
                    "opened_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to open file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileDeleteTool(BaseTool):
    """Delete a file or directory, optionally permanently.

    Inputs:
    - path (string, required)
    - permanent (boolean, optional): if false, moves to trash

    Outputs:
    - deleted_path (string)
    - resolved_deleted_path (string)
    - permanent (boolean)
    - deleted_at (string)
    """

    def get_tool_name(self) -> str:
        return "file_delete"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        path = inputs.get("path", "")
        permanent = bool(inputs.get("permanent", False))

        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")

        try:
            expanded_path = _expand_path(path)

            if not os.path.exists(expanded_path):
                return ToolOutput(success=False, data={}, error=f"Path not found: {path}")

            if permanent:
                if os.path.isdir(expanded_path):
                    shutil.rmtree(expanded_path)
                else:
                    os.remove(expanded_path)
                resolved_deleted_path = expanded_path
            else:
                trash_root = PathManager().get_user_data_dir() / "trash"
                trash_root.mkdir(parents=True, exist_ok=True)
                destination = trash_root / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{Path(expanded_path).name}"
                shutil.move(expanded_path, destination)
                resolved_deleted_path = str(destination)

            return ToolOutput(
                success=True,
                data={
                    "deleted_path": path,
                    "resolved_deleted_path": resolved_deleted_path,
                    "permanent": permanent,
                    "deleted_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to delete path: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileMoveTool(BaseTool):
    """Move a file or directory to a new location.

    Inputs:
    - source (string, required)
    - destination (string, required)
    - overwrite (boolean, optional)

    Outputs:
    - old_path (string)
    - new_path (string)
    - resolved_old_path (string)
    - resolved_new_path (string)
    - moved_at (string)
    """

    def get_tool_name(self) -> str:
        return "file_move"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        source = inputs.get("source", "")
        destination = inputs.get("destination", "")
        overwrite = bool(inputs.get("overwrite", False))

        if not source or not destination:
            return ToolOutput(
                success=False,
                data={},
                error="Both source and destination are required",
            )

        try:
            source_path = _expand_path(source)
            destination_path = _expand_path(destination)

            if not os.path.exists(source_path):
                return ToolOutput(success=False, data={}, error=f"Source path not found: {source}")

            if os.path.exists(destination_path):
                if not overwrite:
                    return ToolOutput(success=False, data={}, error=f"Destination already exists: {destination}")
                if os.path.isdir(destination_path):
                    shutil.rmtree(destination_path)
                else:
                    os.remove(destination_path)

            destination_parent = os.path.dirname(destination_path)
            if destination_parent:
                os.makedirs(destination_parent, exist_ok=True)

            shutil.move(source_path, destination_path)

            return ToolOutput(
                success=True,
                data={
                    "old_path": source,
                    "new_path": destination,
                    "resolved_old_path": source_path,
                    "resolved_new_path": destination_path,
                    "moved_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to move path: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


__all__ = [
    "FileCopyTool",
    "FileCreateTool",
    "FileDeleteTool",
    "FileMoveTool",
    "FileOpenTool",
    "FileReadTool",
    "FileSearchTool",
    "FolderCreateTool",
]
