"""
Folder Organize Tool

Uses LLM to categorize files, builds PowerShell commands locally,
and drops a double-clickable restore.bat in the folder for one-click rollback.
"""

import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, List

from ..base import BaseTool, ToolOutput
from app.ai.providers.manager import llm_chat


def _build_restore_bat(
    folder_path: str,
    move_map: Dict[str, str],       # { "SubFolder/file.ext": "file.ext" }
    created_dirs: List[str],
) -> str:
    """
    Generate a Windows .bat file that:
      - Prompts the user for confirmation
      - Moves every file back to the folder root
      - Removes any empty subfolders that were created
    Double-click to run. No Python required.
    """
    lines = [
        "@echo off",
        f"rem  Auto-generated restore script — {datetime.now().isoformat()}",
        f"rem  Folder: {folder_path}",
        "",
        "echo ============================================",
        "echo  Folder Restore",
        f"echo  {folder_path}",
        "echo ============================================",
        "echo.",
        'choice /M "Undo the folder organization and restore all files?"',
        "if errorlevel 2 goto :cancel",
        "",
        "echo.",
        "echo Restoring files...",
        "echo.",
    ]

    # Move each file back to root
    for dest_rel, orig_name in move_map.items():
        src = os.path.join(folder_path, dest_rel.replace("/", "\\"))
        dst = os.path.join(folder_path, orig_name)
        lines += [
            f'if exist "{src}" (',
            f'    move /Y "{src}" "{dst}" >nul',
            f'    echo   [OK] {orig_name}',
            f') else (',
            f'    echo   [--] skipped ^(not found^): {orig_name}',
             ')',
        ]

    # Remove empty created dirs — longest path first so children go before parents
    lines += ["", "echo.", "echo Removing empty folders..."]
    for d in sorted(created_dirs, key=lambda x: x.count(os.sep), reverse=True):
        abs_d = os.path.join(folder_path, d)
        # `rd` without /s only removes empty dirs — inherently safe
        lines.append(
            f'rd "{abs_d}" 2>nul && echo   [OK] Removed: {d} || echo   [--] Not empty or missing: {d}'
        )

    lines += [
        "",
        "echo.",
        "echo ============================================",
        "echo  Restore complete! You can close this window.",
        "echo ============================================",
        "echo.",
        "cmd /k",   # keeps the window OPEN until user manually closes it
        "goto :eof",
        "",
        ":cancel",
        "echo.",
        "echo Restore cancelled. Nothing was changed.",
        "echo.",
        "cmd /k",   # keep open here too so user can read the message
    ]

    return "\r\n".join(lines)   # Windows line endings so Notepad is happy


class FolderOrganizeTool(BaseTool):
    """
    Organizes a folder intelligently:
      1. Lists files, sends ONLY filenames to LLM.
      2. LLM returns a compact { filename: subfolder } map.
      3. PowerShell commands are built locally (no truncation risk).
      4. restore.bat is written BEFORE any files are moved.
      5. PowerShell executes the move commands.
    """

    def get_tool_name(self) -> str:
        return "folder_organize"

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ps_path(path: str) -> str:
        """Safely quote a Windows path for PowerShell."""
        return '"' + path.replace('"', '`"') + '"'

    def _build_ps_commands(
        self,
        folder: str,
        category_map: Dict[str, str],
    ) -> tuple:
        """
        Build mkdir + Move-Item commands from the LLM category map.
        Returns (commands, move_map, created_dirs).
        """
        subfolders = sorted(set(category_map.values()))
        commands   : List[str]       = []
        move_map   : Dict[str, str]  = {}

        for sf in subfolders:
            commands.append(
                f"New-Item -ItemType Directory -Force -Path {self._ps_path(os.path.join(folder, sf))} | Out-Null"
            )

        for filename, subfolder in category_map.items():
            src = os.path.join(folder, filename)
            dst = os.path.join(folder, subfolder, filename)
            commands.append(
                f"Move-Item -Force -Path {self._ps_path(src)} -Destination {self._ps_path(dst)}"
            )
            move_map[f"{subfolder}/{filename}"] = filename

        return commands, move_map, subfolders

    # ── main execute ──────────────────────────────────────────────────────────

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        folder_path = self.get_input(inputs, "path", "")

        if not folder_path:
            return ToolOutput(success=False, data={}, error="Path is required")

        folder_path = os.path.normpath(os.path.expanduser(folder_path))

        if not os.path.isdir(folder_path):
            return ToolOutput(success=False, data={}, error=f"Directory not found: {folder_path}")

        # ── 1. List files ─────────────────────────────────────────────────────
        try:
            files = [
                e for e in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, e))
                and e not in ("restore.bat",)   # never touch the restore script itself
            ]
        except Exception as e:
            return ToolOutput(success=False, data={}, error=f"Cannot read folder: {e}")

        if not files:
            return ToolOutput(
                success=True,
                data={
                    "files_affected"  : 0,
                    "action_performed": "No files to organize",
                    "organized_at"    : datetime.now().isoformat(),
                },
            )

        # ── 2. Ask LLM for ONLY { filename: subfolder } ───────────────────────
        #    No paths, no commands — keeps the response tiny (no truncation).
        prompt = f"""You are a file organization assistant. Assign each file below to the most appropriate subfolder.

FILES:
{chr(10).join(files)}

SUBFOLDER OPTIONS (use these or create sensible new ones):
Images, Videos, Audio, PDFs, Documents, Archives, Executables

RULES:
- Assign EVERY file to exactly one subfolder.
- Use the EXACT filename as the JSON key (copy character-for-character).
- Output ONLY raw JSON — no markdown fences, no explanation.

OUTPUT FORMAT:
{{
  "categories": {{
    "<exact filename>": "<SubfolderName>",
    ...
  }},
  "summary": "One sentence describing what was organized."
}}"""

        try:
            response_text, _ = await llm_chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
        except Exception as e:
            return ToolOutput(success=False, data={}, error=f"LLM call failed: {e}")

        # ── 3. Parse LLM response ─────────────────────────────────────────────
        try:
            clean = response_text.strip()
            for fence in ("```json", "```"):
                if clean.startswith(fence):
                    clean = clean[len(fence):]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            start, end = clean.find("{"), clean.rfind("}")
            if start == -1 or end <= start:
                raise ValueError("No JSON object found")
            llm_data     = json.loads(clean[start : end + 1])
            category_map : Dict[str, str] = llm_data.get("categories", {})
            summary      : str            = llm_data.get("summary", "Folder organized")
        except Exception as e:
            self.logger.error(f"LLM parse error: {e}\nRaw: {response_text!r}")
            return ToolOutput(success=False, data={}, error=f"LLM returned invalid JSON: {e}")

        if not category_map:
            return ToolOutput(success=False, data={}, error="LLM returned empty categories")

        # Guard: only keep files that actually exist (drop LLM hallucinations)
        category_map = {
            fname: sf
            for fname, sf in category_map.items()
            if os.path.isfile(os.path.join(folder_path, fname))
        }

        # ── 4. Build PS commands locally ──────────────────────────────────────
        commands, move_map, created_dirs = self._build_ps_commands(folder_path, category_map)

        # ── 5. Write restore.bat BEFORE touching any files ────────────────────
        restore_path = os.path.join(folder_path, "restore.bat")
        try:
            bat_content = _build_restore_bat(folder_path, move_map, created_dirs)
            with open(restore_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
            self.logger.info(f"restore.bat written: {restore_path}")
        except Exception as e:
            return ToolOutput(success=False, data={}, error=f"Failed to write restore.bat: {e}")

        # ── 6. Execute PowerShell ─────────────────────────────────────────────
        self.logger.info(f"Running {len(commands)} PowerShell command(s)…")
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "\n".join(commands)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return ToolOutput(success=False, data={}, error="PowerShell timed out after 60s")
        except FileNotFoundError:
            return ToolOutput(success=False, data={}, error="PowerShell not found on PATH")
        except Exception as e:
            return ToolOutput(success=False, data={}, error=f"Subprocess error: {e}")

        if result.returncode != 0:
            stderr = result.stderr.strip()
            self.logger.warning(f"PS stderr (code {result.returncode}): {stderr}")
            if stderr and not result.stdout.strip():
                return ToolOutput(
                    success=False, data={},
                    error=f"PowerShell error (exit {result.returncode}): {stderr}",
                )

        files_affected = len(category_map)
        self.logger.info(f"Organized {files_affected} file(s). Restore: {restore_path}")

        return ToolOutput(
            success=True,
            data={
                "files_affected"   : files_affected,
                "action_performed" : summary,
                "organized_at"     : datetime.now().isoformat(),
                "restore_script"   : restore_path,
                "created_dirs"     : created_dirs,
                "powershell_output": result.stdout.strip() or None,
            },
            error=None,
        )