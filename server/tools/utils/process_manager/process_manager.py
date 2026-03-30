"""
ProcessManager Enhanced - Core Window Management
================================================

Core Functions Available:
------------------------
1. list_running_processes() 
   → Returns: List[dict] with {pid, app_name, icon, path, clean_name}

2. find_process(app_name: str)
   → Check if app is running, returns process data or None

3. bring_to_focus(identifier: str | int)
   → Focus any app by name/pid (e.g., "chrome", "vscode", 1234)

4. move(identifier: str | int, direction: str)
   → Move window to position: "left", "right", "top", "bottom", 
     "top_left", "top_right", "bottom_left", "bottom_right", "center"

5. close_process(identifier: str | int)
   → Close window/process

6. minimize_process(identifier: str | int)
   → Minimize window

7. maximize_process(identifier: str | int)
   → Maximize window

8. restore_process(identifier: str | int)
   → Restore window to normal state

9. set_always_on_top(identifier: str | int, enable: bool)
   → Pin window to stay on top

Quick Start:
-----------
    from process_manager_enhanced import ProcessManager

    pm = ProcessManager()
    
    # List running processes
    processes = pm.list_running_processes()
    for p in processes:
        print(f"{p['app_name']} (PID: {p['pid']})")
    
    # Check if app is running
    chrome = pm.find_process("chrome")
    if chrome:
        print(f"Chrome is running with PID: {chrome['pid']}")
    
    # Focus an app
    pm.bring_to_focus("chrome")
    
    # Move focused window
    pm.move("chrome", "left")
    pm.move("vscode", "right")
    
    # Window controls
    pm.minimize_process("spotify")
    pm.maximize_process("terminal")
    pm.close_process("notepad")

Platform Support: Windows · Linux (X11) · macOS
Python: 3.10+
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import re
import subprocess
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | ProcessManager | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ProcessManager")

# ---------------------------------------------------------------------------
# Platform Detection
# ---------------------------------------------------------------------------
_PLATFORM: str = platform.system()
IS_WIN: bool = _PLATFORM == "Windows"
IS_LIN: bool = _PLATFORM == "Linux"
IS_MAC: bool = _PLATFORM == "Darwin"

# ---------------------------------------------------------------------------
# Optional Dependencies
# ---------------------------------------------------------------------------

try:
    import psutil as _psutil
    HAS_PSUTIL: bool = True
except ImportError:
    HAS_PSUTIL = False
    log.warning("psutil not installed: pip install psutil")

HAS_WIN32: bool = False
if IS_WIN:
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
        HAS_WIN32 = True
        log.info("✓ Windows backend: pywin32 OK")
    except ImportError:
        log.warning("pywin32 not found - using ctypes fallback")

if IS_WIN:
    import ctypes.wintypes as _wt

HAS_OBJC: bool = False
if IS_MAC:
    try:
        from AppKit import ( #type:ignore
            NSApplicationActivateAllWindows,
            NSApplicationActivateIgnoringOtherApps,
            NSWorkspace,
        )
        from Quartz import ( #type:ignore
            CGDisplayBounds,
            CGDisplayIsMain,
            CGGetActiveDisplayList,
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )
        HAS_OBJC = True
        log.info("✓ macOS backend: AppKit + Quartz OK")
    except ImportError:
        log.warning("pyobjc not installed")

HAS_WMCTRL: bool = False
HAS_XDOTOOL: bool = False
if IS_LIN:
    def _bin_exists(name: str) -> bool:
        return subprocess.run(["which", name], capture_output=True).returncode == 0

    HAS_WMCTRL  = _bin_exists("wmctrl")
    HAS_XDOTOOL = _bin_exists("xdotool")
    if HAS_WMCTRL:  log.info("✓ Linux backend: wmctrl OK")
    if HAS_XDOTOOL: log.info("✓ Linux backend: xdotool OK")


# ===========================================================================
# Enums
# ===========================================================================

class Direction(str, Enum):
    """Snap directions."""
    LEFT         = "left"
    RIGHT        = "right"
    CENTER       = "center"
    TOP          = "top"
    BOTTOM       = "bottom"
    TOP_LEFT     = "top_left"
    TOP_RIGHT    = "top_right"
    BOTTOM_LEFT  = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class WindowState(str, Enum):
    """Window state."""
    NORMAL    = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    HIDDEN    = "hidden"
    UNKNOWN   = "unknown"


# ===========================================================================
# Data Classes
# ===========================================================================

@dataclass
class ScreenInfo:
    """Monitor information."""
    monitor_index: int
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = True
    name: str = ""

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass
class WindowInfo:
    """Window information."""
    window_id: Any
    title: str
    app_name: str = ""
    pid: int = -1
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    state: WindowState = WindowState.UNKNOWN
    is_visible: bool = True
    monitor: int = 0


# ===========================================================================
# Exceptions
# ===========================================================================

class ProcessManagerError(Exception):
    """Base exception."""

class WindowNotFoundError(ProcessManagerError):
    """Window not found."""

class PlatformNotSupportedError(ProcessManagerError):
    """Platform not supported."""

class BackendNotAvailableError(ProcessManagerError):
    """Backend not available."""


# ===========================================================================
# Geometry Engine
# ===========================================================================

_Rect = Tuple[int, int, int, int]


def direction_to_rect(direction: Union[Direction, str], screen: ScreenInfo, gap: int = 0) -> _Rect:
    """Map direction to rectangle."""
    d = Direction(direction) if isinstance(direction, str) else direction
    W, H, SX, SY = screen.width, screen.height, screen.x, screen.y
    
    half_w = (W - gap) // 2
    half_h = (H - gap) // 2
    
    mapping: Dict[Direction, _Rect] = {
        Direction.LEFT:         (SX, SY, half_w, H),
        Direction.RIGHT:        (SX + half_w + gap, SY, half_w, H),
        Direction.TOP:          (SX, SY, W, half_h),
        Direction.BOTTOM:       (SX, SY + half_h + gap, W, half_h),
        Direction.TOP_LEFT:     (SX, SY, half_w, half_h),
        Direction.TOP_RIGHT:    (SX + half_w + gap, SY, half_w, half_h),
        Direction.BOTTOM_LEFT:  (SX, SY + half_h + gap, half_w, half_h),
        Direction.BOTTOM_RIGHT: (SX + half_w + gap, SY + half_h + gap, half_w, half_h),
        Direction.CENTER:       (SX + W//4, SY + H//4, W//2, H//2),
    }
    return mapping.get(d, (SX, SY, W, H))


# ===========================================================================
# Windows Backend
# ===========================================================================

class _WindowsBackend(ABC):
    """Windows backend."""

    _SW_HIDE     = 0
    _SW_NORMAL   = 1
    _SW_MAXIMIZE = 3
    _SW_MINIMIZE = 6
    _SW_RESTORE  = 9
    _HWND_TOP      = 0
    _HWND_BOTTOM   = 1
    _HWND_TOPMOST  = -1
    _HWND_NOTOPMOST = -2
    _SWP_NOSIZE        = 0x0001
    _SWP_NOMOVE        = 0x0002
    _SWP_NOACTIVATE    = 0x0010
    _SWP_SHOWWINDOW    = 0x0040
    _SWP_ASYNCWINDOWPOS = 0x4000
    _WM_CLOSE      = 0x0010
    _DWMWA_EXTENDED_FRAME_BOUNDS: int = 9

    def __init__(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            log.debug("✓ DPI awareness: Per-Monitor V2")
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                log.debug("✓ DPI awareness: System DPI")
            except (AttributeError, OSError):
                log.debug("DPI awareness: fallback mode")

    def _u32(self) -> ctypes.WinDLL:
        return ctypes.windll.user32

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left",   ctypes.c_long),
            ("top",    ctypes.c_long),
            ("right",  ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    def _dwm_border(self, hwnd: int) -> Tuple[int, int, int, int]:
        """Get DWM invisible border sizes."""
        try:
            if HAS_WIN32:
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] == win32con.SW_SHOWMAXIMIZED:
                    return (0, 0, 0, 0)
            else:
                if self._u32().IsZoomed(hwnd):
                    return (0, 0, 0, 0)
            
            visible = self._RECT()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd,
                self._DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(visible),
                ctypes.sizeof(self._RECT),
            )
            if result != 0:
                return (0, 0, 0, 0)

            if HAS_WIN32:
                wr = win32gui.GetWindowRect(hwnd)
                full_left, full_top, full_right, full_bottom = wr
            else:
                rc = self._RECT()
                self._u32().GetWindowRect(hwnd, ctypes.byref(rc))
                full_left, full_top, full_right, full_bottom = rc.left, rc.top, rc.right, rc.bottom

            bl = visible.left  - full_left
            bt = visible.top   - full_top
            br = full_right    - visible.right
            bb = full_bottom   - visible.bottom
            
            if any(b > 20 or b < -5 for b in [bl, bt, br, bb]):
                log.debug(f"DWM border values out of range ({bl},{bt},{br},{bb}), using fallback")
                return (0, 0, 0, 0)
            
            return (
                max(0, min(bl, 10)),
                max(0, min(bt, 10)),
                max(0, min(br, 10)),
                max(0, min(bb, 10))
            )
        except Exception as e:
            log.debug(f"DWM border query failed: {e}")
            return (0, 0, 0, 0)

    @abstractmethod
    def list_windows(self) -> List[WindowInfo]: ...
    
    @abstractmethod
    def get_focused_window(self) -> Optional[WindowInfo]: ...
    
    def set_window_geometry(self, wid: Any, x: int, y: int, w: int, h: int, animate: bool = False) -> bool:
        """Set window geometry with DWM compensation."""
        hwnd = int(wid)
        try:
            if HAS_WIN32:
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] in (win32con.SW_SHOWMINIMIZED, win32con.SW_SHOWMAXIMIZED):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    if animate:
                        time.sleep(0.05)
            else:
                if self._u32().IsIconic(hwnd) or self._u32().IsZoomed(hwnd):
                    self._u32().ShowWindow(hwnd, self._SW_RESTORE)
                    if animate:
                        time.sleep(0.05)

            bl, bt, br, bb = self._dwm_border(hwnd)

            if w < 100 or h < 100:
                log.warning(f"Target dimensions too small: {w}x{h}, using minimum 400x300")
                w = max(w, 400)
                h = max(h, 300)

            adj_x = x - bl
            adj_y = y - bt
            adj_w = w + bl + br
            adj_h = h + bt + bb

            if HAS_WIN32:
                flags = win32con.SWP_SHOWWINDOW
                if animate:
                    flags |= win32con.SWP_ASYNCWINDOWPOS
                
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOP,
                    adj_x, adj_y, adj_w, adj_h,
                    flags
                )
            else:
                self._u32().MoveWindow(hwnd, adj_x, adj_y, adj_w, adj_h, True)

            if animate:
                time.sleep(0.05)
                
            return True
        except Exception as e:
            log.error(f"set_window_geometry({wid}): {e}")
            return False

    @abstractmethod
    def set_window_state(self, wid: Any, state: WindowState) -> bool: ...
    
    @abstractmethod
    def bring_to_front(self, wid: Any) -> bool: ...
    
    @abstractmethod
    def set_always_on_top(self, wid: Any, enable: bool) -> bool: ...
    
    @abstractmethod
    def list_monitors(self) -> List[ScreenInfo]: ...
    
    @abstractmethod
    def close_window(self, wid: Any) -> bool: ...


class _WindowsBackendImpl(_WindowsBackend):
    """Full Windows implementation."""
    
    def _text(self, hwnd: int) -> str:
        if HAS_WIN32:
            return win32gui.GetWindowText(hwnd)
        n = self._u32().GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        self._u32().GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _visible(self, hwnd: int) -> bool:
        return bool(self._u32().IsWindowVisible(hwnd))

    def _pid(self, hwnd: int) -> int:
        pid_c = ctypes.c_ulong(0)
        if HAS_WIN32:
            _, v = win32process.GetWindowThreadProcessId(hwnd)
            return int(v)
        self._u32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid_c))
        return pid_c.value

    def _rect(self, hwnd: int) -> _Rect:
        if HAS_WIN32:
            r = win32gui.GetWindowRect(hwnd)
            return (r[0], r[1], r[2] - r[0], r[3] - r[1])
        rc = _wt.RECT()
        self._u32().GetWindowRect(hwnd, ctypes.byref(rc))
        return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)

    def _state(self, hwnd: int) -> WindowState:
        if HAS_WIN32:
            cmd = win32gui.GetWindowPlacement(hwnd)[1]
            if cmd == win32con.SW_SHOWMINIMIZED: return WindowState.MINIMIZED
            if cmd == win32con.SW_SHOWMAXIMIZED: return WindowState.MAXIMIZED
            return WindowState.NORMAL
        if self._u32().IsIconic(hwnd): return WindowState.MINIMIZED
        if self._u32().IsZoomed(hwnd): return WindowState.MAXIMIZED
        return WindowState.NORMAL

    def list_windows(self) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        
        _WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_size_t, ctypes.c_int
        )

        def _cb(hwnd: int, _lparam: int) -> bool:
            if not self._visible(hwnd):
                return True
            title = self._text(hwnd)
            if not title:
                return True
            x, y, w, h = self._rect(hwnd)
            pid = self._pid(hwnd)
            app = ""
            with suppress(Exception):
                if HAS_WIN32:
                    import win32api as _wa
                    import win32process as _wp
                    handle = _wa.OpenProcess(0x0410, False, pid)
                    if handle:
                        app = os.path.basename(_wp.GetModuleFileNameEx(handle, 0))
                        _wa.CloseHandle(handle)
            windows.append(WindowInfo(
                window_id=hwnd, title=title, app_name=app, pid=pid,
                x=x, y=y, width=w, height=h, state=self._state(hwnd),
            ))
            return True

        self._u32().EnumWindows(_WNDENUMPROC(_cb), 0)
        return windows

    def get_focused_window(self) -> Optional[WindowInfo]:
        hwnd: int = (
            win32gui.GetForegroundWindow()
            if HAS_WIN32 else self._u32().GetForegroundWindow()
        )
        if not hwnd:
            return None
        x, y, w, h = self._rect(hwnd)
        return WindowInfo(
            window_id=hwnd, title=self._text(hwnd), pid=self._pid(hwnd),
            x=x, y=y, width=w, height=h, state=self._state(hwnd),
        )

    def set_window_state(self, wid: Any, state: WindowState) -> bool:
        hwnd = int(wid)
        _map: Dict[WindowState, int] = {
            WindowState.MINIMIZED: self._SW_MINIMIZE,
            WindowState.MAXIMIZED: self._SW_MAXIMIZE,
            WindowState.NORMAL:    self._SW_RESTORE,
            WindowState.HIDDEN:    self._SW_HIDE,
        }
        cmd = _map.get(state, self._SW_NORMAL)
        if HAS_WIN32:
            win32gui.ShowWindow(hwnd, cmd)
        else:
            self._u32().ShowWindow(hwnd, cmd)
        return True

    def bring_to_front(self, wid: Any) -> bool:
        hwnd = int(wid)
        try:
            if HAS_WIN32:
                # CRITICAL FIX: Check if already foreground window
                fg = win32gui.GetForegroundWindow()
                if fg == hwnd:
                    log.debug(f"Window {hwnd} already in foreground, skipping")
                    return True
                
                # Only restore if minimized - don't move normal windows!
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] == win32con.SW_SHOWMINIMIZED:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                
                # Attach thread input for reliable focus
                fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
                my_tid = win32api.GetCurrentThreadId()
                attached = fg_tid != my_tid
                if attached:
                    win32process.AttachThreadInput(fg_tid, my_tid, True)
                
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
                
                if attached:
                    win32process.AttachThreadInput(fg_tid, my_tid, False)
            else:
                # ctypes fallback
                fg_hwnd = self._u32().GetForegroundWindow()
                
                # CRITICAL FIX: Check if already foreground
                if fg_hwnd == hwnd:
                    log.debug(f"Window {hwnd} already in foreground, skipping")
                    return True
                
                # Only restore if minimized
                if self._u32().IsIconic(hwnd):
                    self._u32().ShowWindow(hwnd, self._SW_RESTORE)
                
                my_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                fg_tid  = ctypes.c_ulong(0)
                self._u32().GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_tid))
                attached = fg_tid.value != my_tid
                if attached:
                    self._u32().AttachThreadInput(fg_tid.value, my_tid, True)
                self._u32().SetForegroundWindow(hwnd)
                if attached:
                    self._u32().AttachThreadInput(fg_tid.value, my_tid, False)
            return True
        except Exception as e:
            log.error(f"bring_to_front({wid}): {e}")
            return False

    def set_always_on_top(self, wid: Any, enable: bool) -> bool:
        hwnd = int(wid)
        z    = self._HWND_TOPMOST if enable else self._HWND_NOTOPMOST
        flags = self._SWP_NOMOVE | self._SWP_NOSIZE
        try:
            if HAS_WIN32:
                flag = win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST
                win32gui.SetWindowPos(hwnd, flag, 0, 0, 0, 0, flags)
            else:
                self._u32().SetWindowPos(hwnd, z, 0, 0, 0, 0, flags)
            return True
        except Exception as e:
            log.error(f"set_always_on_top({wid}): {e}")
            return False

    def close_window(self, wid: Any) -> bool:
        hwnd = int(wid)
        try:
            if HAS_WIN32:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            else:
                self._u32().PostMessageW(hwnd, self._WM_CLOSE, 0, 0)
            return True
        except Exception as e:
            log.error(f"close_window({wid}): {e}")
            return False

    def list_monitors(self) -> List[ScreenInfo]:
        """Get monitor info using work area (excludes taskbar)."""
        monitors: List[ScreenInfo] = []

        _MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_long),
            ctypes.c_int,
        )

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize",    ctypes.c_ulong),
                ("rcMonitor", ctypes.c_long * 4),
                ("rcWork",    ctypes.c_long * 4),
                ("dwFlags",   ctypes.c_ulong),
            ]

        def _mon_cb(h_mon: int, _hdc: int, _lp: Any, _param: int) -> bool:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(h_mon, ctypes.byref(info))
            
            rc = info.rcWork
            
            x, y, right, bottom = rc[0], rc[1], rc[2], rc[3]
            monitors.append(ScreenInfo(
                monitor_index=len(monitors),
                x=x, y=y, width=right - x, height=bottom - y,
                is_primary=bool(info.dwFlags & 1),
            ))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, _MONITORENUMPROC(_mon_cb), 0
        )

        if not monitors:
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            monitors.append(ScreenInfo(0, 0, 0, sw, sh, True))
        return monitors


# ===========================================================================
# Linux Backend
# ===========================================================================

class _LinuxBackend:
    """Linux backend."""

    def _run(self, cmd: List[str]) -> str:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()

    def _xdo(self, *args: str) -> str:
        if not HAS_XDOTOOL:
            raise BackendNotAvailableError("xdotool not installed")
        return self._run(["xdotool", *args])

    def _wmc(self, *args: str) -> str:
        if not HAS_WMCTRL:
            raise BackendNotAvailableError("wmctrl not installed")
        return self._run(["wmctrl", *args])

    def _geometry(self, wid: str) -> _Rect:
        try:
            raw = self._xdo("getwindowgeometry", "--shell", wid)
            props: Dict[str, int] = {}
            for line in raw.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    with suppress(ValueError):
                        props[k.strip()] = int(v.strip())
            return props.get("X",0), props.get("Y",0), props.get("WIDTH",0), props.get("HEIGHT",0)
        except Exception:
            return 0, 0, 0, 0

    def list_windows(self) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        if HAS_WMCTRL:
            for line in self._wmc("-l", "-p").splitlines():
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue
                wid, _desk, pid_str, _host, title = parts
                pid = int(pid_str) if pid_str.lstrip("-").isdigit() else -1
                x, y, w, h = self._geometry(wid) if HAS_XDOTOOL else (0, 0, 0, 0)
                windows.append(WindowInfo(window_id=wid, title=title, pid=pid, x=x, y=y, width=w, height=h))
        return windows

    def get_focused_window(self) -> Optional[WindowInfo]:
        try:
            wid = self._xdo("getactivewindow")
            title = self._xdo("getwindowname", wid)
            x, y, w, h = self._geometry(wid)
            return WindowInfo(window_id=wid, title=title, x=x, y=y, width=w, height=h)
        except Exception:
            return None

    def set_window_geometry(self, wid: Any, x: int, y: int, w: int, h: int, animate: bool = False) -> bool:
        wid_s = str(wid)
        try:
            with suppress(Exception):
                self._wmc("-r", wid_s, "-b", "remove,maximized_vert,maximized_horz")
            
            if animate:
                time.sleep(0.02)
                
            if HAS_XDOTOOL:
                self._xdo("windowmove", wid_s, str(x), str(y))
                self._xdo("windowsize", wid_s, str(w), str(h))
            elif HAS_WMCTRL:
                self._wmc("-r", wid_s, "-e", f"0,{x},{y},{w},{h}")
            
            if animate:
                time.sleep(0.02)
                
            return True
        except Exception as e:
            log.error(f"set_window_geometry({wid}): {e}")
            return False

    def set_window_state(self, wid: Any, state: WindowState) -> bool:
        wid_s = str(wid)
        try:
            if state == WindowState.MINIMIZED:
                if HAS_XDOTOOL: self._xdo("windowminimize", wid_s)
            elif state == WindowState.MAXIMIZED:
                if HAS_WMCTRL: self._wmc("-r", wid_s, "-b", "add,maximized_vert,maximized_horz")
            elif state == WindowState.NORMAL:
                if HAS_WMCTRL: self._wmc("-r", wid_s, "-b", "remove,maximized_vert,maximized_horz")
            return True
        except Exception as e:
            log.error(f"set_window_state({wid}): {e}")
            return False

    def bring_to_front(self, wid: Any) -> bool:
        wid_s = str(wid)
        try:
            if HAS_XDOTOOL:
                self._xdo("windowactivate", "--sync", wid_s)
                self._xdo("windowraise", wid_s)
            elif HAS_WMCTRL:
                self._wmc("-ia", wid_s)
            return True
        except Exception as e:
            log.error(f"bring_to_front({wid}): {e}")
            return False

    def set_always_on_top(self, wid: Any, enable: bool) -> bool:
        try:
            action = "add" if enable else "remove"
            if HAS_WMCTRL:
                self._wmc("-r", str(wid), "-b", f"{action},above")
            return True
        except Exception as e:
            log.error(f"set_always_on_top({wid}): {e}")
            return False

    def close_window(self, wid: Any) -> bool:
        wid_s = str(wid)
        try:
            if HAS_WMCTRL: self._wmc("-ic", wid_s)
            return True
        except Exception as e:
            log.error(f"close_window({wid}): {e}")
            return False

    def list_monitors(self) -> List[ScreenInfo]:
        monitors: List[ScreenInfo] = []
        try:
            raw = self._run(["xrandr", "--query"])
            pat = re.compile(r"(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)", re.I)
            for m in pat.finditer(raw):
                monitors.append(ScreenInfo(
                    monitor_index=len(monitors),
                    x=int(m.group(5)), y=int(m.group(6)),
                    width=int(m.group(3)), height=int(m.group(4)),
                    is_primary=bool(m.group(2)), name=m.group(1),
                ))
        except Exception:
            pass
        return monitors or [ScreenInfo(0, 0, 0, 1920, 1080, True)]


# ===========================================================================
# macOS Backend
# ===========================================================================

class _MacBackend:
    """macOS backend."""

    def _as(self, script: str) -> str:
        return subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        ).stdout.strip()

    def list_windows(self) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        if HAS_OBJC:
            for entry in (CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []):
                layer = int(entry.get("kCGWindowLayer", 99))
                if layer >= 25:
                    continue
                b = entry.get("kCGWindowBounds", {})
                ww, wh = int(b.get("Width", 0)), int(b.get("Height", 0))
                if ww < 2 or wh < 2:
                    continue
                pid = int(entry.get("kCGWindowOwnerPID", -1))
                app = str(entry.get("kCGWindowOwnerName", ""))
                title = str(entry.get("kCGWindowName", "") or app)
                windows.append(WindowInfo(
                    window_id=app, title=title, app_name=app, pid=pid,
                    x=int(b.get("X", 0)), y=int(b.get("Y", 0)), width=ww, height=wh,
                ))
        return windows

    def get_focused_window(self) -> Optional[WindowInfo]:
        try:
            app = self._as('tell application "System Events" to get name of first process whose frontmost is true')
            return next((w for w in self.list_windows() if w.app_name == app), None)
        except Exception:
            return None

    def set_window_geometry(self, wid: Any, x: int, y: int, w: int, h: int, animate: bool = False) -> bool:
        app = str(wid)
        self._as(f'tell application "{app}" to set bounds of window 1 to {{{x}, {y}, {x+w}, {y+h}}}')
        return True

    def set_window_state(self, wid: Any, state: WindowState) -> bool:
        app = str(wid)
        if state == WindowState.MINIMIZED:
            self._as(f'tell application "{app}" to set miniaturized of window 1 to true')
        elif state == WindowState.NORMAL:
            self._as(f'tell application "{app}" to set miniaturized of window 1 to false')
        return True

    def bring_to_front(self, wid: Any) -> bool:
        app = str(wid)
        if HAS_OBJC:
            for a in NSWorkspace.sharedWorkspace().runningApplications():
                if (a.localizedName() or "").lower() == app.lower():
                    a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows) #type:ignore
                    return True
        self._as(f'tell application "{app}" to activate')
        return True

    def set_always_on_top(self, wid: Any, enable: bool) -> bool:
        log.warning("set_always_on_top not supported on macOS")
        return False

    def close_window(self, wid: Any) -> bool:
        app = str(wid)
        self._as(f'tell application "System Events" to tell process "{app}" to click button 1 of window 1')
        return True

    def list_monitors(self) -> List[ScreenInfo]:
        monitors: List[ScreenInfo] = []
        if HAS_OBJC:
            try:
                max_d = 8
                active = (ctypes.c_uint32 * max_d)()
                count  = ctypes.c_uint32(0)
                CGGetActiveDisplayList(max_d, active, ctypes.byref(count))
                for i in range(count.value):
                    did = active[i]
                    b   = CGDisplayBounds(did)
                    monitors.append(ScreenInfo(
                        monitor_index=i,
                        x=int(b.origin.x), y=int(b.origin.y),
                        width=int(b.size.width), height=int(b.size.height),
                        is_primary=bool(CGDisplayIsMain(did)),
                    ))
            except Exception:
                pass
        return monitors or [ScreenInfo(0, 0, 0, 1920, 1080, True)]


# ===========================================================================
# ProcessManager - Simplified Core Functions
# ===========================================================================

class ProcessManager:
    """
    Core window management - simplified API.
    
    Main Functions:
    - list_running_processes() → Get all processes with clean data
    - find_process(name) → Check if app is running
    - bring_to_focus(name/pid) → Focus any window
    - move(name/pid, direction) → Move window to screen position
    - close_process() → Close window
    - minimize_process() → Minimize window
    - maximize_process() → Maximize window
    - restore_process() → Restore window
    - set_always_on_top() → Pin window on top
    """

    # Common app aliases for better matching
    _ALIASES: Dict[str, List[str]] = {
        "chrome":   ["google chrome", "chrome"],
        "vscode":   ["visual studio code", "code", "vscode"],
        "code":     ["visual studio code", "code", "vscode"],
        "terminal": ["windows terminal", "powershell", "cmd", "terminal", "wt"],
        "brave":    ["brave"],
        "edge":     ["microsoft edge", "edge"],
        "firefox":  ["firefox"],
        "excel":    ["excel"],
        "word":     ["word"],
        "outlook":  ["outlook"],
        "teams":    ["microsoft teams", "teams"],
        "slack":    ["slack"],
        "spotify":  ["spotify"],
        "notepad":  ["notepad"],
        "explorer": ["file explorer", "explorer"],
        "discord":  ["discord"],
        "zoom":     ["zoom"],
    }

    def __init__(self, default_monitor: int = 0, default_gap: int = 6) -> None:
        self._default_monitor = default_monitor
        self._default_gap     = default_gap
        self._backend: Any = self._make_backend()
        log.info(f"✨ ProcessManager ready | OS={_PLATFORM}")

    @staticmethod
    def _make_backend() -> Any:
        if IS_WIN: return _WindowsBackendImpl()
        if IS_LIN: return _LinuxBackend()
        if IS_MAC: return _MacBackend()
        raise PlatformNotSupportedError(f"Unsupported OS: {_PLATFORM}")

    # === Core Function 1: List Running Processes ===

    def list_running_processes(self) -> List[Dict[str, Any]]:
        """
        Get all running processes with clean data.
        
        Returns:
            List[dict]: Each dict contains:
                - pid (int): Process ID
                - app_name (str): Clean application name
                - path (str): Full executable path
                - clean_name (str): Name without extension
                - icon (str): Path to icon (empty if unavailable)
                
        Example:
            processes = pm.list_running_processes()
            for p in processes:
                print(f"{p['clean_name']} (PID: {p['pid']})")
        """
        if not HAS_PSUTIL:
            raise BackendNotAvailableError("psutil required: pip install psutil")

        results: List[Dict[str, Any]] = []
        
        for proc in _psutil.process_iter(attrs=['pid', 'name', 'exe']):
            try:
                info = proc.info
                pid = info.get('pid', 0)
                name = info.get('name', '')
                exe = info.get('exe', '')
                
                if not name or pid < 10:  # Skip system processes
                    continue
                
                # Clean name (remove extension)
                clean_name = os.path.splitext(name)[0]
                
                # Try to get icon path (platform-specific)
                icon = ""
                if IS_WIN and exe:
                    icon = exe  # On Windows, exe contains icon
                
                results.append({
                    'pid': pid,
                    'app_name': name,
                    'path': exe or '',
                    'clean_name': clean_name,
                    'icon': icon,
                })
            except Exception:
                continue
        
        # Sort by clean name
        results.sort(key=lambda x: x['clean_name'].lower())
        return results

    # === Core Function 2: Find Process ===

    def find_process(self, app_name: str) -> Optional[Dict[str, Any]]:
        """
        Check if a process is running and return its data.
        
        Args:
            app_name: Application name to search for (e.g., "chrome", "vscode")
            
        Returns:
            dict: Process data if found, None otherwise
                  Contains: pid, app_name, path, clean_name, icon
                  
        Example:
            process = pm.find_process("chrome")
            if process:
                print(f"Chrome is running with PID: {process['pid']}")
            else:
                print("Chrome is not running")
        """
        all_processes = self.list_running_processes()
        search_str = app_name.lower()
        
        # Try exact match first
        for proc in all_processes:
            if proc['clean_name'].lower() == search_str:
                return proc
            if proc['app_name'].lower() == search_str:
                return proc
        
        # Try alias expansion
        terms = self._expand_aliases(search_str)
        for proc in all_processes:
            for term in terms:
                if term in proc['clean_name'].lower():
                    return proc
                if term in proc['app_name'].lower():
                    return proc
        
        # Fallback: partial match
        for proc in all_processes:
            if search_str in proc['clean_name'].lower():
                return proc
            if search_str in proc['app_name'].lower():
                return proc
        
        return None

    # === Core Function 3: Bring to Focus ===

    def bring_to_focus(self, identifier: Union[str, int]) -> bool:
        """
        Focus any window by name or PID.
        
        Args:
            identifier: App name (e.g., "chrome", "vscode") or PID (e.g., 1234)
            
        Returns:
            bool: True if successful
            
        Example:
            pm.bring_to_focus("chrome")
            pm.bring_to_focus("vscode")
            pm.bring_to_focus(1234)  # By PID
        """
        # Find the target window
        target_win = self._find_window(identifier)
        if target_win is None:
            log.warning(f"Window not found: {identifier}")
            return False
        
        # Check if already focused (FIXED: prevents unwanted window movement)
        focused = self._backend.get_focused_window()
        if focused and focused.window_id == target_win.window_id:
            log.debug(f"✓ Already focused: {identifier}")
            return True
        
        # Get window ID
        wid = target_win.app_name if IS_MAC and target_win.app_name else target_win.window_id
        
        # Bring to front
        success = self._backend.bring_to_front(wid)
        if success:
            log.info(f"✓ Focused: {identifier}")
        return success

    # === Core Function 4: Move Window ===

    def move(
        self,
        identifier: Union[str, int],
        direction: str,
        monitor: Optional[int] = None,
    ) -> bool:
        """
        Move window to screen position.
        
        Args:
            identifier: App name or PID
            direction: Position - "left", "right", "top", "bottom", "center",
                      "top_left", "top_right", "bottom_left", "bottom_right"
            monitor: Monitor index (default: 0)
            
        Returns:
            bool: True if successful
            
        Example:
            pm.move("chrome", "left")
            pm.move("vscode", "right")
            pm.move("spotify", "top_right")
            pm.move(1234, "center")  # By PID
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            log.warning(f"Window not found: {identifier}")
            return False
        
        screen = self.get_screen_info(monitor if monitor is not None else self._default_monitor)
        x, y, w, h = direction_to_rect(direction, screen, gap=self._default_gap)
        
        success = self._backend.set_window_geometry(wid, x, y, w, h, animate=True)
        if success:
            log.info(f"✓ Moved '{identifier}' to {direction}")
        return success

    # === Core Function 5: Close Process ===

    def close_process(self, identifier: Union[str, int]) -> bool:
        """
        Close window/process.
        
        Args:
            identifier: App name or PID
            
        Returns:
            bool: True if successful
            
        Example:
            pm.close_process("notepad")
            pm.close_process(1234)
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            return False
        
        success = self._backend.close_window(wid)
        if success:
            log.info(f"✓ Closed: {identifier}")
        return success

    # === Core Function 6: Minimize Process ===

    def minimize_process(self, identifier: Union[str, int]) -> bool:
        """
        Minimize window.
        
        Args:
            identifier: App name or PID
            
        Returns:
            bool: True if successful
            
        Example:
            pm.minimize_process("chrome")
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            return False
        
        success = self._backend.set_window_state(wid, WindowState.MINIMIZED)
        if success:
            log.info(f"✓ Minimized: {identifier}")
        return success

    # === Core Function 7: Maximize Process ===

    def maximize_process(self, identifier: Union[str, int]) -> bool:
        """
        Maximize window.
        
        Args:
            identifier: App name or PID
            
        Returns:
            bool: True if successful
            
        Example:
            pm.maximize_process("vscode")
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            return False
        
        success = self._backend.set_window_state(wid, WindowState.MAXIMIZED)
        if success:
            log.info(f"✓ Maximized: {identifier}")
        return success

    # === Core Function 8: Restore Process ===

    def restore_process(self, identifier: Union[str, int]) -> bool:
        """
        Restore window to normal state.
        
        Args:
            identifier: App name or PID
            
        Returns:
            bool: True if successful
            
        Example:
            pm.restore_process("chrome")
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            return False
        
        success = self._backend.set_window_state(wid, WindowState.NORMAL)
        if success:
            log.info(f"✓ Restored: {identifier}")
        return success

    # === Core Function 9: Always On Top ===

    def set_always_on_top(self, identifier: Union[str, int], enable: bool = True) -> bool:
        """
        Pin window to stay on top.
        
        Args:
            identifier: App name or PID
            enable: True to pin, False to unpin
            
        Returns:
            bool: True if successful
            
        Example:
            pm.set_always_on_top("spotify", True)
            pm.set_always_on_top("calculator", False)
        """
        wid = self._wid_safe(identifier)
        if wid is None:
            return False
        
        success = self._backend.set_always_on_top(wid, enable)
        if success:
            action = "pinned" if enable else "unpinned"
            log.info(f"✓ {action.capitalize()}: {identifier}")
        return success

    # === Helper Methods ===

    def _expand_aliases(self, identifier: str) -> List[str]:
        """Expand app aliases for better matching."""
        lower = identifier.lower()
        return self._ALIASES.get(lower, [lower])

    def _find_window(self, identifier: Union[str, int]) -> Optional[WindowInfo]:
        """Find window by identifier."""
        all_wins = self._backend.list_windows()
        
        if isinstance(identifier, int):
            return next((w for w in all_wins if w.pid == identifier), None)
        
        search_str = str(identifier).lower()
        
        # Try exact app name match
        for w in all_wins:
            if w.app_name.lower() == search_str:
                return w
            app_base = os.path.splitext(w.app_name)[0].lower()
            if app_base == search_str:
                return w
        
        # Try alias expansion
        terms = self._expand_aliases(search_str)
        for w in all_wins:
            app_lower = w.app_name.lower()
            for term in terms:
                if term in app_lower:
                    return w
        
        # Fallback: fuzzy match in title
        for w in all_wins:
            if search_str in (w.title + " " + w.app_name).lower():
                return w
        
        return None

    def _wid_safe(self, identifier: Union[str, int]) -> Optional[Any]:
        """Safe window ID resolution."""
        try:
            win = self._find_window(identifier)
            if win is None:
                return None
            return win.app_name if IS_MAC and win.app_name else win.window_id
        except Exception as e:
            log.warning(f"Failed to resolve window: {e}")
            return None

    def get_screen_info(self, monitor: int = 0) -> ScreenInfo:
        """Get screen info for monitor."""
        monitors = self._backend.list_monitors()
        if 0 <= monitor < len(monitors):
            return monitors[monitor]
        if monitors:
            return monitors[0]
        return ScreenInfo(0, 0, 0, 1920, 1080, True)

    def __repr__(self) -> str:
        return f"<ProcessManager OS={_PLATFORM} monitors={len(self._backend.list_monitors())}>"


# ===========================================================================
# CLI
# ===========================================================================

def main() -> None:
    """Simple CLI interface."""
    import argparse
    parser = argparse.ArgumentParser(description="ProcessManager - Core Window Management")
    parser.add_argument("--list",     action="store_true", help="List running processes")
    parser.add_argument("--focus",    metavar="NAME", help="Focus window")
    parser.add_argument("--move",     nargs=2, metavar=("NAME", "DIR"), help="Move window")
    parser.add_argument("--close",    metavar="NAME", help="Close window")
    parser.add_argument("--minimize", metavar="NAME", help="Minimize window")
    parser.add_argument("--maximize", metavar="NAME", help="Maximize window")
    args = parser.parse_args()

    pm = ProcessManager()

    if args.list:
        processes = pm.list_running_processes()
        print(f"\n{'PID':<8} {'App Name':<30} {'Clean Name':<20}")
        print("=" * 60)
        for p in processes[:30]:
            print(f"{p['pid']:<8} {p['app_name']:<30} {p['clean_name']:<20}")
    elif args.focus:
        pm.bring_to_focus(args.focus)
    elif args.move:
        pm.move(args.move[0], args.move[1])
    elif args.close:
        pm.close_process(args.close)
    elif args.minimize:
        pm.minimize_process(args.minimize)
    elif args.maximize:
        pm.maximize_process(args.maximize)
    else:
        print(repr(pm))
        print("\n💡 Use --help for available commands")


if __name__ == "__main__":
    main()