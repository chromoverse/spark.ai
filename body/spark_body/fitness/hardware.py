"""Hardware and power state (REDESIGN §18.2) with stdlib only: ctypes on Windows."""

from __future__ import annotations

import os
import platform
import sys
from typing import Any


def power() -> dict[str, Any]:
    """{plugged, battery_pct, saver}. Unknown values are None (desktops, other platforms)."""
    if sys.platform != "win32":
        return {"plugged": None, "battery_pct": None, "saver": None}
    import ctypes
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    st = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return {"plugged": None, "battery_pct": None, "saver": None}
    ac = st.ACLineStatus & 0xFF
    pct = st.BatteryLifePercent & 0xFF
    return {
        "plugged": None if ac == 255 else ac == 1,
        "battery_pct": None if pct == 255 else pct,
        "saver": bool(st.SystemStatusFlag & 1),
    }


def ram_gb() -> float | None:
    if sys.platform == "win32":
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = Mem()
        m.dwLength = ctypes.sizeof(Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(float(m.ullTotalPhys) / 2**30, 1)
        return None
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return None


def scan() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "cpu": platform.processor() or platform.machine(),
        "cores": os.cpu_count(),
        "ram_gb": ram_gb(),
        "power": power(),
    }
