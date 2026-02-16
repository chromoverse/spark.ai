import os
import sys
import subprocess
from unittest import result
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
    """
    AppOpenTool — opens applications, system tools, and URLs.

    Launch decision matrix
    ──────────────────────
    type/method          | Windows                    | macOS/Linux
    ─────────────────────┼────────────────────────────┼─────────────────────────
    browser / url        | webbrowser.open()          | webbrowser.open()
    protocol / cpl /     |                            |
        open_file /        | os.startfile()             | open / xdg-open
        rundll32           |                            |
    uwp_shell            | explorer.exe <path>        | N/A
    shell_guid           | Popen(shell=True)          | N/A
    exe (no args)        | os.startfile()  ← GUI win  | Popen()
    exe (with args)      | Popen([path]+args)  ← CLI  | Popen([path]+args)
    msc                  | os.startfile()             | N/A
    lnk                  | os.startfile()             | N/A
    app (macOS)          | N/A                        | open <path>
    desktop (Linux)      | N/A                        | xdg-open / gtk-launch
    fallback             | Popen(shell=True)          | Popen(shell=True)

    Key rule: os.startfile() is the Windows shell itself — identical to
    double-clicking in Explorer.  It handles GUI apps, shortcuts, documents,
    protocols, and MSC snap-ins natively and always opens a proper window.
    Popen() is only used when CLI args must be forwarded.
    """

    def get_tool_name(self) -> str:
        return "app_open"

    def __init__(self):
        super().__init__()
        self.searcher = SystemSearcher()

    # ─────────────────────────────────────────────────────────────────────────
    #  Public entry point
    # ─────────────────────────────────────────────────────────────────────────
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Find and open an application, tool, or URL."""
        target: str = inputs.get("target", "")
        args: list   = inputs.get("args", [])

        if not target:
            return ToolOutput(
                success=False, data={},
                error="Target app name or URL is required",
            )

        try:
            # ── 1. Resolve ────────────────────────────────────────────────────
            result = self.searcher.search_app(target, include_icon=False)

            if not result:
                return ToolOutput(
                    success=False, data={},
                    error=f"Could not find '{target}' (app, tool, or website)",
                )

            path          = result.get("path", "")
            app_type      = result.get("type", "unknown")
            launch_method = result.get("launch_method", "shell")
            icon1 = result["icon_b64"]   # → base64 PNG of Docker's whale icon
            icon2 = result["icon_url"]   # → None (only set for websites)
            self.logger.info(icon1, icon2)
            self.logger.info(
                f"Opening '{target}' -> {path} ({app_type}) via {launch_method}"
            )

            # ── 2. Dispatch ───────────────────────────────────────────────────
            pid    = 0
            status = "launched"

            if launch_method == "browser" or app_type in ("url", "website"):
                # ── A: Web / browser ──────────────────────────────────────────
                webbrowser.open(path)
                status = "opened_in_browser"

            elif launch_method in ("shell", "run") or app_type in (
                "protocol", "open_file", "rundll32", "cpl", "lnk",
            ):
                # ── B: Shell-dispatch (protocols, CPL, rundll32, .lnk, etc.) ──
                # os.startfile is the right call for all of these on Windows —
                # it delegates to the Windows shell exactly as Explorer does.
                self._shell_open(path)

            elif launch_method == "run_admin":
                # ── C: Admin command (e.g. ipconfig /flushdns) ────────────────
                pid = self._run_admin(path)

            else:
                # ── D: Executable / command-line ──────────────────────────────
                pid = self._launch_executable(path, args, app_type)

            return ToolOutput(
                success=True,
                data={
                    "target":         target,
                    "resolved_name":  result.get("name"),
                    "resolved_path":  path,
                    "type":           app_type,
                    "process_id":     pid,
                    "launch_time":    datetime.now().isoformat(),
                    "status":         status,
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to open '{target}': {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    # ─────────────────────────────────────────────────────────────────────────
    #  Internal launchers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _shell_open(path: str) -> None:
        """
        Open *path* via the OS shell — identical to double-clicking in Explorer.

        Works for: .exe, .lnk, .msc, .cpl, ms-settings:, shell:, URLs,
                   rundll32 strings, documents, and any other shell-registered type.
        Does NOT support extra CLI arguments — use _launch_executable() for that.
        """
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _launch_executable(self, path: str, args: list, app_type: str) -> int:
        """
        Execute a binary, optionally with CLI arguments.

        Decision logic
        ──────────────
        UWP shell paths   → explorer.exe <path>         (always)
        Shell GUIDs       → Popen(shell=True)            (always)
        MSC / CPL         → os.startfile()               (always — MMC/CPL host)
        .lnk shortcuts    → os.startfile()               (always)
        macOS .app        → open <path>                  (always)
        Linux .desktop    → gtk-launch / xdg-open        (always)

        .exe / generic — the critical split:
          • No args  → os.startfile()   ← GUI window, no console attachment
          • With args → Popen([path]+args)  ← CLI invocation with forwarded args

        This means "open docker" (no args) → Docker Desktop window ✅
        and "docker ps" (args present)     → docker CLI in Popen ✅
        """
        try:
            # ── UWP apps via shell:AppsFolder path ────────────────────────────
            if app_type == "uwp_shell":
                subprocess.Popen(["explorer.exe", path])
                return 0

            # ── Special shell GUIDs (God Mode, etc.) ─────────────────────────
            if app_type == "shell_guid":
                subprocess.Popen(path, shell=True)
                return 0

            # ── MSC snap-ins ─────────────────────────────────────────────────
            if path.lower().endswith(".msc") or app_type == "msc":
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # ── CPL applets ──────────────────────────────────────────────────
            if path.lower().endswith(".cpl") or app_type == "cpl":
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # ── Windows shortcuts ─────────────────────────────────────────────
            if path.lower().endswith(".lnk"):
                if sys.platform == "win32":
                    os.startfile(path)
                return 0

            # ── macOS .app bundles ────────────────────────────────────────────
            if path.endswith(".app") or app_type == "app":
                subprocess.Popen(["open", path])
                return 0

            # ── Linux .desktop entries ────────────────────────────────────────
            if path.endswith(".desktop") or app_type == "desktop":
                app_name = os.path.basename(path).replace(".desktop", "")
                try:
                    proc = subprocess.Popen(["gtk-launch", app_name])
                except FileNotFoundError:
                    proc = subprocess.Popen(["xdg-open", path])
                return proc.pid

            # ── .exe / generic executables ────────────────────────────────────
            #
            #   NO ARGS  → os.startfile()
            #   ─────────────────────────────────────────────────────────────────
            #   os.startfile hands the binary to the Windows shell — exactly
            #   what happens when you double-click it.  The shell creates a new
            #   process with its own window, console session, and UAC elevation
            #   if needed.  GUI apps (Docker Desktop, VS Code, Chrome, Figma,
            #   Grammarly, ...) all open correctly this way.
            #
            #   WITH ARGS  → subprocess.Popen([path] + args)
            #   ─────────────────────────────────────────────────────────────────
            #   When the caller passes CLI arguments we must forward them, which
            #   os.startfile() cannot do.  Popen is used here and the process
            #   inherits the current console (expected for CLI tools).
            #
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
        """
        Run an admin command (e.g. 'ipconfig /flushdns') elevated on Windows,
        or via sudo on Linux/macOS.
        """
        if sys.platform == "win32":
            # ShellExecuteW with 'runas' triggers UAC elevation
            import ctypes
            parts  = cmd.split(None, 1)
            exe    = parts[0]
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

