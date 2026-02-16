"""
Clipboard operations tools for reading and writing clipboard content.
"""

import sys
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class ClipboardReadTool(BaseTool):
    """Read clipboard content."""

    def get_tool_name(self) -> str:
        return "clipboard_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Read content from the system clipboard."""
        try:
            content, content_type = self._read_clipboard()
            
            return ToolOutput(
                success=True,
                data={
                    "content": content,
                    "content_type": content_type,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to read clipboard: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _read_clipboard(self) -> tuple:
        """Read clipboard content based on OS."""
        if sys.platform == "win32":
            return self._read_clipboard_windows()
        elif sys.platform == "darwin":
            return self._read_clipboard_macos()
        else:
            return self._read_clipboard_linux()

    def _read_clipboard_windows(self) -> tuple:
        """Read clipboard on Windows using PowerShell."""
        try:
            # Try to get text content first
            ps_script = '''
Add-Type -AssemblyName System.Windows.Forms
$text = [System.Windows.Forms.Clipboard]::GetText()
if ($text) {
    Write-Output "text:$text"
} else {
    $image = [System.Windows.Forms.Clipboard]::GetImage()
    if ($image) {
        Write-Output "image:[Image data - dimensions: $($image.Width)x$($image.Height)]"
    } else {
        Write-Output "empty:"
    }
}
'''
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if output.startswith("text:"):
                    return (output[5:], "text")
                elif output.startswith("image:"):
                    return (output[6:], "image")
                elif output.startswith("empty:"):
                    return ("", "empty")
                    
        except Exception as e:
            self.logger.warning(f"Windows clipboard read failed: {e}")
        
        return ("", "unknown")

    def _read_clipboard_macos(self) -> tuple:
        """Read clipboard on macOS using pbpaste."""
        try:
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                content = result.stdout
                # Detect content type
                if content.strip():
                    return (content, "text")
                return ("", "empty")
                
        except FileNotFoundError:
            self.logger.warning("pbpaste not found on macOS")
        except Exception as e:
            self.logger.warning(f"macOS clipboard read failed: {e}")
        
        return ("", "unknown")

    def _read_clipboard_linux(self) -> tuple:
        """Read clipboard on Linux using xclip or xsel."""
        # Try xclip first
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return (result.stdout, "text")
                
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"xclip clipboard read failed: {e}")
        
        # Try xsel
        try:
            result = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return (result.stdout, "text")
                
        except FileNotFoundError:
            self.logger.warning("Neither xclip nor xsel found on Linux")
        except Exception as e:
            self.logger.warning(f"xsel clipboard read failed: {e}")
        
        return ("", "unknown")


class ClipboardWriteTool(BaseTool):
    """Write content to clipboard."""

    def get_tool_name(self) -> str:
        return "clipboard_write"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Write content to the system clipboard."""
        content = inputs.get("content", "")
        
        if not content:
            return ToolOutput(
                success=False, 
                data={}, 
                error="Content is required for clipboard write"
            )
        
        try:
            self._write_clipboard(content)
            
            return ToolOutput(
                success=True,
                data={
                    "content_length": len(content),
                    "copied_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to write clipboard: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _write_clipboard(self, content: str) -> None:
        """Write content to clipboard based on OS."""
        if sys.platform == "win32":
            self._write_clipboard_windows(content)
        elif sys.platform == "darwin":
            self._write_clipboard_macos(content)
        else:
            self._write_clipboard_linux(content)

    def _write_clipboard_windows(self, content: str) -> None:
        """Write to clipboard on Windows using PowerShell."""
        # Escape the content for PowerShell
        escaped_content = content.replace("'", "''")
        
        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Clipboard]::SetText('{escaped_content}')
'''
        
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode != 0:
            raise Exception("Failed to set clipboard text")

    def _write_clipboard_macos(self, content: str) -> None:
        """Write to clipboard on macOS using pbcopy."""
        result = subprocess.run(
            ["pbcopy"],
            input=content,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            raise Exception("Failed to copy to clipboard")

    def _write_clipboard_linux(self, content: str) -> None:
        """Write to clipboard on Linux using xclip or xsel."""
        # Try xclip first
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=content,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return
                
        except FileNotFoundError:
            pass
        
        # Try xsel
        try:
            result = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=content,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return
                
        except FileNotFoundError:
            raise Exception("Neither xclip nor xsel found on Linux")
        
        raise Exception("Failed to copy to clipboard")


# Export all tools for registration
__all__ = ["ClipboardReadTool", "ClipboardWriteTool"]