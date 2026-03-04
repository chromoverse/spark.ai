from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class CodeMatch:
    path: str
    line: int
    snippet: str


class CodeContextService:
    """
    Read-only codebase context provider with strict allowlist roots and caps.
    """

    def __init__(self):
        server_root = Path(__file__).resolve().parents[2]
        repo_root = server_root.parent

        allowed = [
            (server_root / "app").resolve(),
            (server_root / "scripts").resolve(),
        ]
        electron_src = (repo_root / "electron" / "src").resolve()
        if electron_src.exists():
            allowed.append(electron_src)

        self.server_root = server_root.resolve()
        self.repo_root = repo_root.resolve()
        self.allowed_roots = allowed
        self.allowed_suffixes = {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
            ".md",
            ".txt",
            ".yaml",
            ".yml",
        }

    def repo_search(
        self,
        query: str,
        limit: int = 5,
        max_files: int = 60,
        max_bytes: int = 10_000,
    ) -> Dict[str, Any]:
        token = query.strip()
        if not token:
            return {"items": [], "trimmed": False, "summary": "Empty repo search query."}

        token_lower = token.lower()
        found: List[CodeMatch] = []
        visited_files = 0
        consumed_bytes = 0
        trimmed = False

        for root in self.allowed_roots:
            for file_path in root.rglob("*"):
                if visited_files >= max_files or len(found) >= limit:
                    trimmed = True
                    break
                if not file_path.is_file() or file_path.suffix.lower() not in self.allowed_suffixes:
                    continue
                visited_files += 1

                try:
                    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue

                for idx, line in enumerate(lines, start=1):
                    if token_lower not in line.lower():
                        continue
                    snippet = line.strip()
                    snippet_size = len(snippet.encode("utf-8"))
                    if consumed_bytes + snippet_size > max_bytes:
                        trimmed = True
                        break
                    consumed_bytes += snippet_size
                    found.append(
                        CodeMatch(
                            path=str(file_path.resolve()),
                            line=idx,
                            snippet=snippet[:220],
                        )
                    )
                    break
            if visited_files >= max_files or len(found) >= limit:
                break

        summary = (
            f"Repo search found {len(found)} match(es) for '{token}' across "
            f"{min(visited_files, max_files)} scanned file(s)."
        )
        if trimmed:
            summary += " Results were trimmed by safety caps."

        return {
            "items": [match.__dict__ for match in found],
            "trimmed": trimmed,
            "summary": summary,
            "scanned_files": min(visited_files, max_files),
        }

    def repo_read_snippet(
        self,
        file_path: str,
        start_line: int = 1,
        line_count: int = 80,
        max_bytes: int = 10_000,
    ) -> Dict[str, Any]:
        path = self._resolve_allowed_path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Requested file not found: {path}")

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        safe_start = max(1, start_line)
        safe_count = max(1, min(line_count, 300))
        end_line = min(len(lines), safe_start + safe_count - 1)
        selected = lines[safe_start - 1 : end_line]

        payload: List[str] = []
        consumed = 0
        truncated = False
        for idx, line in enumerate(selected, start=safe_start):
            numbered = f"{idx}: {line}"
            size = len(numbered.encode("utf-8"))
            if consumed + size > max_bytes:
                truncated = True
                break
            consumed += size
            payload.append(numbered)

        return {
            "path": str(path),
            "start_line": safe_start,
            "end_line": safe_start + len(payload) - 1,
            "snippet": "\n".join(payload),
            "truncated": truncated,
        }

    def _resolve_allowed_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (self.repo_root / raw_path).resolve()
        else:
            candidate = candidate.resolve()

        for root in self.allowed_roots:
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue
        raise PermissionError(f"Path is outside allowed roots: {candidate}")


_code_context_service: CodeContextService | None = None


def get_code_context_service() -> CodeContextService:
    global _code_context_service
    if _code_context_service is None:
        _code_context_service = CodeContextService()
    return _code_context_service
