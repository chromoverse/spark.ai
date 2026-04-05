"""
Screenshot capture tools for capturing screen or window.
"""

import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, Tuple

from app.path.artifacts import get_artifact_store
from app.path.manager import PathManager

from ..base import BaseTool, ToolOutput


class ScreenshotCaptureTool(BaseTool):
    """Capture a screenshot and persist it in the managed artifact store.

    Inputs:
    - target (string, optional): "full" (default), "window", or "region"
    - save_path (string, optional): explicit destination path

    Outputs:
    - artifact_id (string)
    - artifact_kind (string): "screenshot"
    - file_path (string)
    - in_clipboard (boolean)
    - resolution (string)
    - captured_at (string)
    """

    def get_tool_name(self) -> str:
        return "screenshot_capture"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        target = self.get_input(inputs, "target", "full")
        save_path = self.get_input(inputs, "save_path", None)
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        task_id = str(inputs.get("_task_id") or "").strip()

        try:
            resolved_save_path = save_path or self._default_save_path(user_id=user_id)
            result_path, resolution = self._capture_screenshot(target, resolved_save_path)

            artifact = get_artifact_store().register_file(
                kind="screenshot",
                tool_name=self.get_tool_name(),
                file_path=result_path,
                user_id=user_id,
                task_id=task_id,
                metadata={
                    "target": target,
                    "resolution": resolution,
                },
            )

            return ToolOutput(
                success=True,
                data={
                    "artifact_id": artifact.artifact_id,
                    "artifact_kind": artifact.kind,
                    "file_path": result_path,
                    "in_clipboard": False,
                    "resolution": resolution,
                    "captured_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to capture screenshot: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _default_save_path(self, *, user_id: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshots_dir = PathManager().get_artifact_dir("screenshots", user_id=user_id)
        return str((screenshots_dir / f"spark_screenshot_{timestamp}.png").resolve())

    def _capture_screenshot(self, target: str, save_path: str) -> Tuple[str, str]:
        if sys.platform == "win32":
            return self._capture_screenshot_windows(target, save_path)
        if sys.platform == "darwin":
            return self._capture_screenshot_macos(target, save_path)
        return self._capture_screenshot_linux(target, save_path)

    def _capture_screenshot_windows(self, target: str, save_path: str) -> Tuple[str, str]:
        del target  # Windows implementation currently captures the primary screen.
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$width = $bounds.Width
$height = $bounds.Height
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save("{save_path.replace(os.sep, '/')}")
Write-Output "$width`x$height"
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and os.path.exists(save_path):
            return save_path, result.stdout.strip() or self._get_image_resolution(save_path)
        raise RuntimeError(result.stderr.strip() or "Failed to capture screenshot on Windows")

    def _capture_screenshot_macos(self, target: str, save_path: str) -> Tuple[str, str]:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        cmd = ["screencapture", "-x"]
        if target in {"window", "region"}:
            cmd.append("-i")
        cmd.append(save_path)
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.exists(save_path):
            return save_path, self._get_image_resolution(save_path)
        raise RuntimeError("Failed to capture screenshot on macOS")

    def _capture_screenshot_linux(self, target: str, save_path: str) -> Tuple[str, str]:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        for cmd in self._linux_candidate_commands(target, save_path):
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
            except FileNotFoundError:
                continue
            if result.returncode == 0 and os.path.exists(save_path):
                return save_path, self._get_image_resolution(save_path)
        raise RuntimeError("Failed to capture screenshot on Linux - no suitable tool found")

    @staticmethod
    def _linux_candidate_commands(target: str, save_path: str) -> list[list[str]]:
        commands = [["gnome-screenshot"]]
        if target == "window":
            commands[0].append("-w")
        elif target == "region":
            commands[0].append("-a")
        commands[0].extend(["-f", save_path])

        scrot_cmd = ["scrot"]
        if target == "window":
            scrot_cmd.append("-u")
        elif target == "region":
            scrot_cmd.append("-s")
        scrot_cmd.append(save_path)

        import_cmd = ["import"]
        if target == "window":
            import_cmd.extend(["-window", "root"])
        elif target != "region":
            import_cmd.extend(["-window", "root"])
        import_cmd.append(save_path)

        return [commands[0], scrot_cmd, import_cmd]

    def _get_image_resolution(self, file_path: str) -> str:
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                return f"{img.width}x{img.height}"
        except Exception:
            return "Unknown"


__all__ = ["ScreenshotCaptureTool"]
