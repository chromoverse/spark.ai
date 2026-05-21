"""Clipboard operations tools."""
import asyncio
import sys
import subprocess
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class ClipboardReadTool(BaseTool):
    """Read clipboard content."""

    TOOL_DESCRIPTION = "Read clipboard content"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"content": {"type": "string"}, "content_type": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "what's in my clipboard"}]
    SEMANTIC_TAGS = ["system", "clipboard", "read"]
    TOOL_CATEGORY = "clipboard_notify"

    def get_tool_name(self) -> str:
        return "clipboard_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            content, content_type = await asyncio.to_thread(self._read_clipboard)
            return ToolOutput(success=True, data={"content": content, "content_type": content_type, "timestamp": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    def _read_clipboard(self) -> tuple:
        if sys.platform == "win32":
            try:
                ps_script = 'Add-Type -AssemblyName System.Windows.Forms; $t = [System.Windows.Forms.Clipboard]::GetText(); if($t){Write-Output "text:$t"}else{Write-Output "empty:"}'
                result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    output = result.stdout.strip()
                    if output.startswith("text:"):
                        return (output[5:], "text")
                    return ("", "empty")
            except Exception:
                pass
            return ("", "unknown")
        elif sys.platform == "darwin":
            try:
                result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return (result.stdout, "text") if result.stdout.strip() else ("", "empty")
            except Exception:
                pass
            return ("", "unknown")
        else:
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return (result.stdout, "text")
                except FileNotFoundError:
                    continue
            return ("", "unknown")


class ClipboardWriteTool(BaseTool):
    """Write to clipboard."""

    TOOL_DESCRIPTION = "Write to clipboard"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {"content": {"type": "string", "required": True}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"content_length": {"type": "integer"}, "copied_at": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "copy this to clipboard"}]
    SEMANTIC_TAGS = ["system", "clipboard", "write"]
    TOOL_CATEGORY = "clipboard_notify"

    def get_tool_name(self) -> str:
        return "clipboard_write"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        content = inputs.get("content", "")
        if not content:
            return ToolOutput(success=False, data={}, error="Content is required")
        try:
            await asyncio.to_thread(self._write_clipboard, content)
            return ToolOutput(success=True, data={"content_length": len(content), "copied_at": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    def _write_clipboard(self, content: str) -> None:
        if sys.platform == "win32":
            escaped = content.replace("'", "''")
            ps_script = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText('{escaped}')"
            result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=5)
            if result.returncode != 0:
                raise Exception("Failed to set clipboard text")
        elif sys.platform == "darwin":
            result = subprocess.run(["pbcopy"], input=content, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise Exception("Failed to copy to clipboard")
        else:
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    result = subprocess.run(cmd, input=content, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return
                except FileNotFoundError:
                    continue
            raise Exception("Neither xclip nor xsel found")


__all__ = ["ClipboardReadTool", "ClipboardWriteTool"]
