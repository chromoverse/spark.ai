"""
Application management tools for opening, closing, and controlling apps.
"""

import os
import sys
import subprocess
import webbrowser
import asyncio
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput
from ...utils.searcher.system_searcher import SystemSearcher
from ...utils.process_manager.process_manager import ProcessManager


class AppOpenTool(BaseTool):
    """Open application, system tool, or URL using SystemSearcher."""

    def get_tool_name(self) -> str:
        return "app_open"

    def __init__(self):
        super().__init__()
        self.searcher = SystemSearcher()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Find and open an application, tool, or URL."""
        target: str = inputs.get("target", "")
        args: list = inputs.get("args", [])

        if not target:
            return ToolOutput(
                success=False, data={},
                error="Target app name or URL is required",
            )

        try:
            # SystemSearcher rebuilds cache via AppSearcher which takes ~4s
            # BaseTool handles wrapping this sync execution in a thread!
            result = self.searcher.search_app(target, False)

            if not result:
                return ToolOutput(
                    success=False, data={},
                    error=f"Could not find '{target}' (app, tool, or website)",
                )

            path = result.get("path", "")
            app_type = result.get("type", "unknown")
            launch_method = result.get("launch_method", "shell")
            
            self.logger.info(
                f"Opening '{target}' -> {path} ({app_type}) via {launch_method}"
            )

            # Dispatch based on type
            pid = 0
            status = "launched"

            if launch_method == "browser" or app_type in ("url", "website"):
                webbrowser.open(path)
                status = "opened_in_browser"

            elif launch_method in ("shell", "run") or app_type in (
                "protocol", "open_file", "rundll32", "cpl", "lnk",
            ):
                self._shell_open(path)

            elif launch_method == "run_admin":
                pid = self._run_admin(path)

            else:
                pid = self._launch_executable(path, args, app_type)

            return ToolOutput(
                success=True,
                data={
                    "target": target,
                    "resolved_name": result.get("name"),
                    "resolved_path": path,
                    "type": app_type,
                    "process_id": pid,
                    "launch_time": datetime.now().isoformat(),
                    "status": status,
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to open '{target}': {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    @staticmethod
    def _shell_open(path: str) -> None:
        """Open path via the OS shell."""
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _launch_executable(self, path: str, args: list, app_type: str) -> int:
        """Execute a binary, optionally with CLI arguments."""
        try:
            # UWP apps via shell:AppsFolder path
            if app_type == "uwp_shell":
                subprocess.Popen(["explorer.exe", path])
                return 0

            # Special shell GUIDs (God Mode, etc.)
            if app_type == "shell_guid":
                subprocess.Popen(path, shell=True)
                return 0

            # MSC snap-ins
            if path.lower().endswith(".msc") or app_type == "msc":
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # CPL applets
            if path.lower().endswith(".cpl") or app_type == "cpl":
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # Windows shortcuts
            if path.lower().endswith(".lnk"):
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # macOS .app bundles
            if path.endswith(".app") or app_type == "app":
                subprocess.Popen(["open", path])
                return 0

            # Linux .desktop entries
            if path.endswith(".desktop") or app_type == "desktop":
                app_name = os.path.basename(path).replace(".desktop", "")
                try:
                    proc = subprocess.Popen(["gtk-launch", app_name])
                except FileNotFoundError:
                    proc = subprocess.Popen(["xdg-open", path])
                return proc.pid

            # .exe / generic executables
            if sys.platform == "win32" and not args:
                os.startfile(path)
                return 0

            proc = subprocess.Popen([path] + args)
            return proc.pid

        except Exception as e:
            self.logger.error(f"Error launching executable {path}: {e}")
            raise

    @staticmethod
    def _run_admin(cmd: str) -> int:
        """Run an admin command elevated."""
        if sys.platform == "win32":
            import ctypes
            parts = cmd.split(None, 1)
            exe = parts[0]
            params = parts[1] if len(parts) > 1 else ""
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, None, 1
            )
            return 0
        else:
            proc = subprocess.Popen(["sudo"] + cmd.split())
            return proc.pid


class AppCloseTool(BaseTool):
    """Close application tool using ProcessManager."""
    
    def get_tool_name(self) -> str:
        return "app_close"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()
    
    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Close/Kill an application."""
        target = inputs.get("target", "")
        
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")
            
        try:
            self.logger.info(f"Closing app: {target}")
            
            success = self.pm.close_process(target)
            
            if success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "status": "closed",
                        "closed_at": datetime.now().isoformat(),
                    }
                )
            else:
                proc = self.pm.find_process(target)
                if not proc:
                    return ToolOutput(
                        success=False,
                        data={},
                        error=f"Process '{target}' not found or not running"
                    )
                else:
                    return ToolOutput(
                        success=False, 
                        data={}, 
                        error=f"Failed to close app '{target}'"
                    )
                
        except Exception as e:
            self.logger.error(f"Failed to close app: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class AppRestartTool(BaseTool):
    """Restart application tool."""

    def get_tool_name(self) -> str:
        return "app_restart"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()
        self.app_open_tool = AppOpenTool()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Restart an application."""
        target = inputs.get("target", "")
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")

        try:
            self.logger.info(f"Restarting app: {target}")

            # Close the app
            self.pm.close_process(target)
            
            # Since this is now completely synchronous inside to_thread, using sleep isn't strictly necessary,
            # but we can use time.sleep to stall the thread safely.
            import time
            time.sleep(2)

            # Open the app
            open_result = self.app_open_tool._execute(inputs)

            if open_result.success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "status": "restarted",
                        "restarted_at": datetime.now().isoformat(),
                        "open_data": open_result.data
                    }
                )
            else:
                return ToolOutput(
                    success=False,
                    data={"close_status": "attempted"},
                    error=f"Failed to restart (open failed): {open_result.error}"
                )

        except Exception as e:
            self.logger.error(f"Failed to restart app: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class AppMinimizeTool(BaseTool):
    """Minimize application window."""
    
    def get_tool_name(self) -> str:
        return "app_minimize"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        target = inputs.get("target", "")
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")
        
        try:
            success = self.pm.minimize_process(target)
            if success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "minimized": True,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            else:
                return ToolOutput(success=False, data={}, error=f"Failed to minimize '{target}' or not found")
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))


class AppMaximizeTool(BaseTool):
    """Maximize application window."""
    
    def get_tool_name(self) -> str:
        return "app_maximize"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        target = inputs.get("target", "")
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")
        
        try:
            success = self.pm.maximize_process(target)
            if success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "maximized": True,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            else:
                return ToolOutput(success=False, data={}, error=f"Failed to maximize '{target}' or not found")
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))


class AppFocusTool(BaseTool):
    """Bring application to front and focus."""
    
    def get_tool_name(self) -> str:
        return "app_focus"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        target = inputs.get("target", "")
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")
        
        try:
            success = self.pm.bring_to_focus(target)
            if success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "focused": True,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            else:
                return ToolOutput(success=False, data={}, error=f"Failed to focus '{target}' or not found")
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))


# Export all tools for registration
__all__ = [
    "AppOpenTool", 
    "AppCloseTool", 
    "AppRestartTool",
    "AppMinimizeTool", 
    "AppMaximizeTool", 
    "AppFocusTool"
]
