"""
Application management tools for opening, closing, and controlling apps.
"""

import os
import sys
import subprocess
import webbrowser
import asyncio
import logging
import uuid
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

import httpx

from ..base import BaseTool, ToolOutput
from app.kernel.execution.approval_coordinator import get_approval_coordinator
from tools.utils.process_manager.process_manager import ProcessManager
from tools.utils.searcher.system_searcher import SystemSearcher


class AppOpenTool(BaseTool):
    """Open application, system tool, or URL using SystemSearcher.

    Inputs:
    - target (string, required)
    - args (array, optional)

    Outputs:
    - process_id (integer)
    - launch_time (string)
    """

    def get_tool_name(self) -> str:
        return "app_open"

    def __init__(self):
        super().__init__()
        self.searcher = SystemSearcher()
        self.app_focus_tool = AppFocusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Open a local app or website based on the requested destination intent."""
        raw_target: str = str(inputs.get("target", "")).strip()
        raw_args = inputs.get("args", [])
        args: list = raw_args if isinstance(raw_args, list) else []
        raw_destination = inputs.get("destination", "auto")
        destination = self._normalize_destination(raw_destination)
        raw_web_fallback_policy = inputs.get("web_fallback_policy", "validate_then_ask")
        web_fallback_policy = self._normalize_web_fallback_policy(raw_web_fallback_policy)
        user_id_raw = inputs.get("_user_id")
        user_id = str(user_id_raw).strip() if user_id_raw else ""
        task_id_raw = inputs.get("_task_id")
        task_id = str(task_id_raw).strip() if task_id_raw else ""
        execution_id_raw = inputs.get("_execution_id") or inputs.get("execution_id")
        execution_id = str(execution_id_raw).strip() if execution_id_raw else "standalone"

        target, destination = self._normalize_target_and_destination(raw_target, destination)

        if not target:
            return ToolOutput(
                success=False, data={},
                error="Target app name or URL is required",
            )

        try:
            if destination == "browser":
                website_result = await asyncio.to_thread(
                    lambda: self.searcher.resolve_website(
                        target,
                        include_icon=False,
                        allow_guess=True,
                    )
                )
                if not website_result:
                    return ToolOutput(
                        success=False,
                        data={
                            "target": target,
                            "status": "website_not_valid",
                        },
                        error=f"Could not find a reliable website for '{target}'.",
                    )

                validated_url = await self._validate_website_result(website_result)
                if not validated_url:
                    return ToolOutput(
                        success=False,
                        data={
                            "target": target,
                            "resolved_path": website_result.get("path"),
                            "status": "website_not_valid",
                        },
                        error=f"Could not verify a reliable website for '{target}'.",
                    )

                await asyncio.to_thread(webbrowser.open, validated_url)
                return ToolOutput(
                    success=True,
                    data={
                        "target": target,
                        "resolved_name": website_result.get("name"),
                        "resolved_path": validated_url,
                        "type": website_result.get("type", "website"),
                        "process_id": 0,
                        "launch_time": datetime.now().isoformat(),
                        "status": "opened_in_browser",
                    },
                )

            local_result = await asyncio.to_thread(self.searcher.search_local_app, target, False)
            if local_result:
                return await self._launch_result(target=target, result=local_result, args=args)

            if destination == "app":
                return ToolOutput(
                    success=False,
                    data={"target": target},
                    error=f"Could not find '{target}' on this system.",
                )

            if web_fallback_policy == "disabled":
                return ToolOutput(
                    success=False,
                    data={"target": target},
                    error=f"Could not find '{target}' on this system.",
                )

            if not user_id:
                return ToolOutput(
                    success=False,
                    data={"target": target},
                    error=f"'{target}' app was not found locally and no user context was provided for website fallback.",
                )

            self._speak_web_fallback_check_started(target=target, user_id=user_id)
            self._schedule_background_web_fallback(
                target=target,
                user_id=user_id,
                task_id=task_id,
                execution_id=execution_id,
            )
            return ToolOutput(
                success=True,
                data={
                    "target": target,
                    "resolved_name": None,
                    "resolved_path": "",
                    "type": "website",
                    "process_id": 0,
                    "launch_time": datetime.now().isoformat(),
                    "status": "web_fallback_check_started",
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to open '{target}': {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    @staticmethod
    def _normalize_destination(value: Any) -> str:
        destination = str(value or "auto").strip().lower()
        return destination if destination in {"auto", "app", "browser"} else "auto"

    @staticmethod
    def _normalize_web_fallback_policy(value: Any) -> str:
        policy = str(value or "validate_then_ask").strip().lower()
        return policy if policy in {"disabled", "validate_then_ask"} else "validate_then_ask"

    def _normalize_target_and_destination(self, target: str, destination: str) -> Tuple[str, str]:
        cleaned_target = str(target or "").strip()
        if not cleaned_target:
            return "", destination

        lowered = cleaned_target.lower()
        explicit_browser = any(
            token in lowered
            for token in (" in browser", " browser", " website", " web", " online")
        )
        normalized_target = re.sub(
            r"\b(in browser|browser|website|web|online)\b",
            "",
            cleaned_target,
            flags=re.IGNORECASE,
        )
        normalized_target = re.sub(r"\s+", " ", normalized_target).strip() or cleaned_target

        if destination == "auto" and (explicit_browser or self._is_explicit_web_target(cleaned_target)):
            destination = "browser"
        return normalized_target, destination

    async def _launch_result(self, *, target: str, result: Dict[str, Any], args: list) -> ToolOutput:
        path = result.get("path", "")
        app_type = result.get("type", "unknown")
        launch_method = result.get("launch_method", "shell")

        self.logger.info("Opening '%s' -> %s (%s) via %s", target, path, app_type, launch_method)

        pid = 0
        status = "launched"

        if launch_method == "browser" or app_type in ("url", "website"):
            await asyncio.to_thread(webbrowser.open, path)
            status = "opened_in_browser"
        elif launch_method in ("shell", "run") or app_type in (
            "protocol", "open_file", "rundll32", "cpl", "lnk",
        ):
            await asyncio.to_thread(self._shell_open, path)
        elif launch_method == "run_admin":
            pid = await asyncio.to_thread(self._run_admin, path)
        else:
            pid = await asyncio.to_thread(self._launch_executable, path, args, app_type)

        focused = False
        if status == "launched":
            focused = await self._focus_opened_app(
                target=target,
                resolved_name=result.get("name"),
                path=path,
                process_id=pid,
            )

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
                "focused": focused,
            },
        )

    async def _focus_opened_app(
        self,
        *,
        target: str,
        resolved_name: Optional[str],
        path: str,
        process_id: int,
    ) -> bool:
        focus_inputs = self._build_focus_inputs(
            target=target,
            resolved_name=resolved_name,
            path=path,
            process_id=process_id,
        )
        if not focus_inputs:
            return False

        max_attempts = 6
        for attempt in range(max_attempts):
            for focus_input in focus_inputs:
                focus_result = await self.app_focus_tool.execute(focus_input)
                if focus_result.success:
                    return True
            if attempt < max_attempts - 1:
                await asyncio.sleep(0.25)

        self.logger.warning("Opened '%s' but could not focus its window", target)
        return False

    @staticmethod
    def _build_focus_inputs(
        *,
        target: str,
        resolved_name: Optional[str],
        path: str,
        process_id: int,
    ) -> list[Dict[str, Any]]:
        focus_inputs: list[Dict[str, Any]] = []
        seen_text_targets: set[str] = set()

        if isinstance(process_id, int) and process_id > 0:
            seed_target = str(resolved_name or target or process_id).strip()
            focus_inputs.append({"target": seed_target, "process_id": process_id})

        for candidate in (
            resolved_name,
            target,
            AppOpenTool._focus_name_from_path(path),
        ):
            text_candidate = str(candidate or "").strip()
            if not text_candidate:
                continue
            lowered = text_candidate.lower()
            if lowered in seen_text_targets:
                continue
            seen_text_targets.add(lowered)
            focus_inputs.append({"target": text_candidate})

        return focus_inputs

    @staticmethod
    def _focus_name_from_path(path: str) -> str:
        cleaned = str(path or "").strip().strip('"')
        if not cleaned:
            return ""
        if cleaned.lower().startswith(("http://", "https://", "www.")):
            return ""
        if cleaned.lower().startswith(("shell:", "ms-", "steam://")):
            return ""

        basename = os.path.basename(cleaned.split(" ", 1)[0].rstrip("\\/"))
        if not basename:
            return ""
        return os.path.splitext(basename)[0]

    async def _validate_website_result(self, result: Dict[str, Any]) -> Optional[str]:
        candidate_url = str(result.get("path", "")).strip()
        if not candidate_url:
            return None
        return await self._validate_url(candidate_url)

    async def _validate_url(self, url: str) -> Optional[str]:
        headers = {"User-Agent": "SparkAI/1.0"}
        timeout = httpx.Timeout(3.0, connect=1.5)

        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            try:
                response = await client.head(url)
                if self._looks_like_valid_website_status(response.status_code):
                    return str(response.url)
                if response.status_code not in {401, 403, 405}:
                    return None
            except Exception:
                pass

            try:
                response = await client.get(url)
                if self._looks_like_valid_website_status(response.status_code):
                    return str(response.url)
            except Exception:
                return None

        return None

    @staticmethod
    def _looks_like_valid_website_status(status_code: int) -> bool:
        return 200 <= status_code < 400 or status_code in {401, 403}

    def _schedule_background_web_fallback(
        self,
        *,
        target: str,
        user_id: str,
        task_id: str,
        execution_id: str,
    ) -> None:
        background_task = asyncio.create_task(
            self._run_background_web_fallback(
                target=target,
                user_id=user_id,
                task_id=task_id,
                execution_id=execution_id or "standalone",
            )
        )
        get_approval_coordinator().track_background_task(
            user_id=user_id,
            execution_id=execution_id or "standalone",
            task=background_task,
        )

    async def _run_background_web_fallback(
        self,
        *,
        target: str,
        user_id: str,
        task_id: str,
        execution_id: str,
    ) -> None:
        try:
            website_result = await asyncio.to_thread(
                lambda: self.searcher.resolve_website(
                    target,
                    include_icon=False,
                    allow_guess=True,
                )
            )
            if not website_result:
                self._speak_website_not_valid(target=target, user_id=user_id)
                return

            validated_url = await self._validate_website_result(website_result)
            if not validated_url:
                self._speak_website_not_valid(target=target, user_id=user_id)
                return

            request_id = (
                f"{task_id}::web_fallback::{uuid.uuid4().hex[:8]}"
                if task_id
                else f"app_open_web_fallback::{uuid.uuid4().hex[:12]}"
            )
            question = (
                f"'{target}' is not installed locally. "
                "Do you want me to open its website in your browser?"
            )

            from app.agent.execution_gateway import get_task_emitter

            async def _handle_response(_user_id: str, _task_id: str, approved: bool) -> None:
                if not approved:
                    return
                await asyncio.to_thread(webbrowser.open, validated_url)

            submitted = await get_task_emitter().submit_approval_request(
                user_id=user_id,
                task_id=request_id,
                question=question,
                execution_id=execution_id,
                on_response_callback=_handle_response,
            )
            if not submitted:
                self.logger.warning("Could not submit browser fallback approval for '%s'", target)
        except asyncio.CancelledError:
            self.logger.info("Cancelled background website validation for '%s'", target)
            raise
        except Exception as exc:
            self.logger.error("Background website validation failed for '%s': %s", target, exc)

    @staticmethod
    def _is_explicit_web_target(target: str) -> bool:
        normalized = target.strip().lower()
        return (
            normalized.startswith("http://")
            or normalized.startswith("https://")
            or normalized.startswith("www.")
        )

    @staticmethod
    def _speak_web_fallback_check_started(*, target: str, user_id: str) -> None:
        from app.socket.utils import fire_tts

        fire_tts(
            f"I could not find {target} installed. I am checking whether there is a reliable website instead.",
            user_id=user_id,
        )

    @staticmethod
    def _speak_website_not_valid(*, target: str, user_id: str) -> None:
        from app.socket.utils import fire_tts

        fire_tts(
            f"I could not find a reliable website for {target}.",
            user_id=user_id,
        )

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
    """Close application tool using ProcessManager.

    Inputs:
    - target (string, required)
    - force (boolean, optional)

    Outputs:
    - exit_code (integer)
    - closed_at (string)
    """
    
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
    """Restart application tool.

    Inputs:
    - target (string, required)
    - save_state (boolean, optional)

    Outputs:
    - old_process_id (integer)
    - new_process_id (integer)
    - restart_time (string)
    """

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

            # Open the app (AppOpenTool is async).
            open_result = asyncio.run(self.app_open_tool.execute(inputs))

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
    """Minimize application window.

    Inputs:
    - target (string, required)

    Outputs:
    - target (string)
    - minimized (boolean)
    - timestamp (string)
    """
    
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
    """Maximize application window.

    Inputs:
    - target (string, required)

    Outputs:
    - target (string)
    - maximized (boolean)
    - timestamp (string)
    """
    
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
    """Bring application to front and focus.

    Inputs:
    - target (string, required)
    - process_id (integer, optional)

    Outputs:
    - target (string)
    - focused (boolean)
    - timestamp (string)
    """
    
    def get_tool_name(self) -> str:
        return "app_focus"

    def __init__(self):
        super().__init__()
        self.pm = ProcessManager()

    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        target = inputs.get("target", "")
        process_id = inputs.get("process_id")
        if isinstance(process_id, bool):
            process_id = None

        identifier: Any = process_id if isinstance(process_id, int) and process_id > 0 else target
        if not identifier:
            return ToolOutput(success=False, data={}, error="Target app name is required")
        
        try:
            success = self.pm.bring_to_focus(identifier)
            if success:
                return ToolOutput(
                    success=True,
                    data={
                        "target": str(target or identifier),
                        "focused": True,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            else:
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"Failed to focus '{target or identifier}' or not found",
                )
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
