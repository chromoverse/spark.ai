import os
import sys
import subprocess
import webbrowser
import asyncio
import logging
from typing import Dict, Any, Optional
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
        # Use the singleton/facade SystemSearcher
        self.searcher = SystemSearcher()
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Find and open an application, tool, or URL."""
        target = inputs.get("target", "")
        args = inputs.get("args", [])
        
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name or URL is required")
            
        try:
            # 1. Search using SystemSearcher (Unified API)
            # include_icon=False for speed as we just need to launch it
            result = self.searcher.search_app(target, include_icon=False)
            
            if not result:
                return ToolOutput(
                    success=False, 
                    data={}, 
                    error=f"Could not find '{target}' (app, tool, or website)"
                )
            
            # 2. Extract launch details
            path = result.get("path", "")
            app_type = result.get("type", "unknown")
            launch_method = result.get("launch_method", "shell")
            
            self.logger.info(f"Opening '{target}' -> {path} ({app_type}) via {launch_method}")
            
            # 3. Launch based on method/type
            pid = 0
            status = "launched"
            
            # Case A: Browser URL
            if launch_method == "browser" or app_type in ("url", "website"):
                webbrowser.open(path)
                status = "opened_in_browser"
                
            # Case B: Shell Protocol / file-open / rundll
            elif launch_method == "shell" or app_type in ("protocol", "open_file", "rundll32", "cpl"):
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
                    
            # Case C: Executable / Command lines
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
                    "status": status
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to open '{target}': {e}")
            return ToolOutput(success=False, data={}, error=str(e))
    
    def _launch_executable(self, path: str, args: list, app_type: str) -> int:
        """Handle execution of binaries and command/argument strings."""
        try:
            cmd = []
            
            # Handle special types from AppSearcher
            if app_type == "uwp_shell":
                # UWP apps via explorer
                subprocess.Popen(["explorer.exe", path])
                return 0
                
            if app_type == "shell_guid":
                # Special shell folders
                subprocess.Popen(path, shell=True)
                return 0

            # Standard executables
            if path.endswith(".exe") or app_type == "exe":
                cmd = [path] + args
                # Use subprocess.Popen to not block
                proc = subprocess.Popen(cmd)
                return proc.pid
                
            # MSC / CPL (though usually handled by startfile/shell)
            if path.endswith(".msc") or path.endswith(".cpl"):
                 # msc usually needs shell=True or startfile
                 if sys.platform == "win32":
                     os.startfile(path)
                     return 0
            
            # Fallback for generic commands
            cmd = [path] + args
            proc = subprocess.Popen(cmd, shell=True)
            return proc.pid

        except Exception as e:
            self.logger.error(f"Error launching executable {path}: {e}")
            raise e


class AppCloseTool(BaseTool):
    """Close application tool using ProcessManager."""
    
    def get_tool_name(self) -> str:
        return "app_close"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Close/Kill an application."""
        target = inputs.get("target", "")
        # force = inputs.get("force", False)
        
        if not target:
            return ToolOutput(success=False, data={}, error="Target app name is required")
            
        try:
            self.logger.info(f"Closing app: {target}")
            
            # Using ProcessManager to close the process
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
                 # Try to find if process exists to give better error
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
        # Uses AppOpenTool which now uses SystemSearcher
        self.app_open_tool = AppOpenTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Restart an application."""
        target = inputs.get("target", "")
        if not target:
             return ToolOutput(success=False, data={}, error="Target app name is required")

        try:
            self.logger.info(f"Restarting app: {target}")

            # 1. Close the app
            self.pm.close_process(target)
            
            # Wait a bit for it to close completely
            await asyncio.sleep(2)

            # 2. Open the app
            # Reuse the AppOpenTool logic
            open_result = await self.app_open_tool._execute(inputs)

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
    def get_tool_name(self) -> str:
        return "app_minimize"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
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
    def get_tool_name(self) -> str:
        return "app_maximize"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
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
    def get_tool_name(self) -> str:
        return "app_focus"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
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

