"""
Screenshot capture tools for capturing screen or window.
"""

import os
import sys
import subprocess
import tempfile
import logging
from turtle import width
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class ScreenshotCaptureTool(BaseTool):
    """Capture screen or window screenshot."""

    def get_tool_name(self) -> str:
        return "screenshot_capture"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Capture a screenshot of the screen or window."""
        target = self.get_input(inputs, "target", "full")  # full, window, region
        save_path = self.get_input(inputs, "save_path", None)
        
        try:
            # Generate default save path if not provided
            if not save_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Base dir for screenshots
                base_dir = r"C:\Users\Aanand\OneDrive\Pictures\Screenshots\spark-ai-screenshot"

                screenshots_dir = os.path.join(base_dir)
                os.makedirs(screenshots_dir, exist_ok=True)  
                save_path = os.path.join(
                    screenshots_dir,
                    f"spark_screenshot_{timestamp}.png"
                )
            
            # Capture screenshot
            result_path, resolution = self._capture_screenshot(target, save_path)
            
            return ToolOutput(
                success=True,
                data={
                    "file_path": result_path,
                    "in_clipboard": False,  # Could be extended to copy to clipboard
                    "resolution": resolution,
                    "captured_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to capture screenshot: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _capture_screenshot(self, target: str, save_path: str) -> tuple:
        """Capture screenshot based on OS."""
        if sys.platform == "win32":
            return self._capture_screenshot_windows(target, save_path)
        elif sys.platform == "darwin":
            return self._capture_screenshot_macos(target, save_path)
        else:
            return self._capture_screenshot_linux(target, save_path)

    def _capture_screenshot_windows(self, target: str, save_path: str) -> tuple:
        """Capture screenshot on Windows using PowerShell or snipping tool."""
        try:
            # Use PowerShell with .NET for screenshot
            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Get screen dimensions
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$width = $bounds.Width
$height = $bounds.Height

# Create bitmap
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)

# Capture screen
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)

# Save
$bitmap.Save("{save_path.replace(os.sep, '/')}")

Write-Output "$width`x$height"

'''
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                resolution = result.stdout.strip()
                return (save_path, resolution)
            
        except Exception as e:
            self.logger.warning(f"PowerShell screenshot failed: {e}")
        
        # Fallback: Use snipping tool (Windows 11) or snip & sketch
        try:
            # Try Snip & Sketch (Windows 10/11)
            subprocess.run(
                ["ms-screenclip:", "edit"],
                capture_output=True,
                timeout=5
            )
            # This opens the snipping tool, user needs to manually save
            return (save_path, "Manual capture required")
            
        except Exception as e:
            self.logger.error(f"Snipping tool fallback failed: {e}")
        
        raise Exception("Failed to capture screenshot on Windows")

    def _capture_screenshot_macos(self, target: str, save_path: str) -> tuple:
        """Capture screenshot on macOS using screencapture."""
        try:
            cmd = ["screencapture", "-x"]  # -x for no sound
            
            if target == "window":
                # Interactive window selection
                cmd.append("-i")  # Interactive mode
            elif target == "region":
                # Interactive region selection
                cmd.append("-i")
            else:
                # Full screen
                cmd.append("-t")  # Target all displays
            
            cmd.append(save_path)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Get resolution from file
                resolution = self._get_image_resolution(save_path)
                return (save_path, resolution)
            
        except Exception as e:
            self.logger.error(f"macOS screencapture failed: {e}")
        
        raise Exception("Failed to capture screenshot on macOS")

    def _capture_screenshot_linux(self, target: str, save_path: str) -> tuple:
        """Capture screenshot on Linux using gnome-screenshot, scrot, or import."""
        # Try gnome-screenshot first (GNOME)
        try:
            cmd = ["gnome-screenshot"]
            
            if target == "window":
                cmd.append("-w")  # Window
            elif target == "region":
                cmd.append("-a")  # Area selection
            # else: full screen (default)
            
            cmd.extend(["-f", save_path])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and os.path.exists(save_path):
                resolution = self._get_image_resolution(save_path)
                return (save_path, resolution)
                
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"gnome-screenshot failed: {e}")
        
        # Try scrot
        try:
            cmd = ["scrot"]
            
            if target == "window":
                cmd.append("-u")  # Current window
            elif target == "region":
                cmd.append("-s")  # Select region
            
            cmd.append(save_path)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and os.path.exists(save_path):
                resolution = self._get_image_resolution(save_path)
                return (save_path, resolution)
                
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"scrot failed: {e}")
        
        # Try ImageMagick import
        try:
            cmd = ["import"]
            
            if target == "window":
                cmd.append("-window")  # Window
            elif target == "region":
                pass  # Interactive selection is default
            else:
                cmd.append("-window")  # root for full screen
                cmd.append("root")
            
            cmd.append(save_path)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and os.path.exists(save_path):
                resolution = self._get_image_resolution(save_path)
                return (save_path, resolution)
                
        except FileNotFoundError:
            self.logger.error("No screenshot tool found (gnome-screenshot, scrot, import)")
        except Exception as e:
            self.logger.error(f"ImageMagick import failed: {e}")
        
        raise Exception("Failed to capture screenshot on Linux - no suitable tool found")

    def _get_image_resolution(self, file_path: str) -> str:
        """Get image resolution using file command or Python PIL."""
        try:
            # Try using PIL/Pillow if available
            from PIL import Image
            with Image.open(file_path) as img:
                return f"{img.width}x{img.height}"
        except ImportError:
            pass
        except Exception as e:
            self.logger.warning(f"PIL resolution check failed: {e}")
        
        # Fallback: Use file command
        try:
            result = subprocess.run(
                ["file", file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                import re
                match = re.search(r'(\d+)\s*x\s*(\d+)', result.stdout)
                if match:
                    return f"{match.group(1)}x{match.group(2)}"
        except Exception as e:
            self.logger.warning(f"file command resolution check failed: {e}")
        
        return "Unknown"


# Export all tools for registration
__all__ = ["ScreenshotCaptureTool"]