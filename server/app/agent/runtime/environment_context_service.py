"""Environment Context Service — live system state observation.

Provides a real-time snapshot of the user's environment:
- Active windows with titles (what the user sees)
- Running processes (including ones we spawned)
- System specs (CPU, RAM, GPU, temperatures, disk)
- Display / screen info
- Network interfaces
- Working directory contents

This context is injected into the shell_agent planner and can be
queried by any tool that needs environmental awareness.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EnvironmentContextService:
    """Observe the live system state for tool intelligence."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0
        self._cache_ttl: float = 5.0  # seconds

    # ── Full snapshot ────────────────────────────────────────────────────

    async def get_snapshot(
        self,
        *,
        include_windows: bool = True,
        include_processes: bool = True,
        include_system: bool = True,
        include_display: bool = False,
        include_network: bool = False,
        working_dir: Optional[str] = None,
        max_bytes: int = 3000,
    ) -> Dict[str, Any]:
        """Build a comprehensive environment snapshot (async, non-blocking)."""
        import time

        now = time.monotonic()
        if now - self._cache_ts < self._cache_ttl and self._cache:
            return self._cache

        snapshot: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform.system(),
            "platform_version": platform.version(),
            "hostname": platform.node(),
        }

        tasks = []
        keys = []

        if include_windows:
            tasks.append(asyncio.to_thread(self._get_active_windows))
            keys.append("active_windows")

        if include_processes:
            tasks.append(asyncio.to_thread(self._get_key_processes))
            keys.append("key_processes")

        if include_system:
            tasks.append(asyncio.to_thread(self._get_system_specs))
            keys.append("system")

        if include_display:
            tasks.append(asyncio.to_thread(self._get_display_info))
            keys.append("display")

        if include_network:
            tasks.append(asyncio.to_thread(self._get_network_info))
            keys.append("network")

        if working_dir:
            tasks.append(asyncio.to_thread(self._get_dir_tree, working_dir))
            keys.append("working_dir_tree")

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                snapshot[key] = {"error": str(result)}
            else:
                snapshot[key] = result

        self._cache = snapshot
        self._cache_ts = now
        return snapshot

    async def get_compact_context(
        self,
        working_dir: Optional[str] = None,
        max_bytes: int = 2000,
    ) -> str:
        """Return a compact text block for prompt injection."""
        snap = await self.get_snapshot(
            include_windows=True,
            include_processes=True,
            include_system=True,
            include_display=False,
            include_network=False,
            working_dir=working_dir,
        )

        lines = ["ENVIRONMENT CONTEXT:"]

        # System
        sys_info = snap.get("system", {})
        if sys_info and not sys_info.get("error"):
            cpu = sys_info.get("cpu_name", "unknown")
            ram_gb = sys_info.get("total_ram_gb", "?")
            cpu_pct = sys_info.get("cpu_percent", "?")
            ram_pct = sys_info.get("ram_percent", "?")
            lines.append(f"System: {cpu}, {ram_gb}GB RAM, CPU={cpu_pct}%, RAM={ram_pct}%")
            if sys_info.get("gpu_name"):
                lines.append(f"GPU: {sys_info['gpu_name']}")
            if sys_info.get("cpu_temp_c") is not None:
                lines.append(f"CPU Temp: {sys_info['cpu_temp_c']}°C")

        # Active windows
        windows = snap.get("active_windows", [])
        if windows and not isinstance(windows, dict):
            top_windows = windows[:6]
            win_labels = [f"{w.get('name', '?')}({w.get('title', '')[:40]})" for w in top_windows]
            lines.append(f"Active windows: {', '.join(win_labels)}")

        # Key processes
        procs = snap.get("key_processes", [])
        if procs and not isinstance(procs, dict):
            proc_labels = [f"{p.get('name', '?')}(pid={p.get('pid', '?')})" for p in procs[:8]]
            lines.append(f"Key processes: {', '.join(proc_labels)}")

        # Working dir tree
        tree = snap.get("working_dir_tree", {})
        if tree and not tree.get("error"):
            items = tree.get("entries", [])
            if items:
                entry_labels = [e.get("name", "") for e in items[:15]]
                lines.append(f"Working dir ({tree.get('path', '?')}): {', '.join(entry_labels)}")

        text = "\n".join(lines)
        return text[:max_bytes]

    # ── System queries (for arbitrary user questions) ────────────────────

    async def query_system(self, query: str) -> Dict[str, Any]:
        """Answer arbitrary system questions by running the right commands.

        Handles: CPU temp, GPU info, disk health, installed software,
        network adapters, running services, environment variables, etc.
        """
        query_lower = query.lower()

        # Route to the right query handler
        if any(kw in query_lower for kw in ("temp", "thermal", "heat")):
            return await asyncio.to_thread(self._query_temperatures)

        if any(kw in query_lower for kw in ("gpu", "graphics", "video card", "nvidia", "amd")):
            return await asyncio.to_thread(self._query_gpu)

        if any(kw in query_lower for kw in ("cpu", "processor", "cores", "threads")):
            return await asyncio.to_thread(self._query_cpu_detail)

        if any(kw in query_lower for kw in ("ram", "memory")):
            return await asyncio.to_thread(self._query_memory_detail)

        if any(kw in query_lower for kw in ("disk", "storage", "drive", "ssd", "hdd")):
            return await asyncio.to_thread(self._query_disk_detail)

        if any(kw in query_lower for kw in ("installed", "software", "programs", "apps")):
            return await asyncio.to_thread(self._query_installed_software)

        if any(kw in query_lower for kw in ("service", "daemon")):
            return await asyncio.to_thread(self._query_services)

        if any(kw in query_lower for kw in ("env", "environment variable", "path")):
            return await asyncio.to_thread(self._query_env_vars)

        if any(kw in query_lower for kw in ("uptime", "boot", "start")):
            return await asyncio.to_thread(self._query_uptime)

        if any(kw in query_lower for kw in ("screen", "display", "monitor", "resolution")):
            return await asyncio.to_thread(self._get_display_info)

        # Fallback — run a generic system info query
        return await asyncio.to_thread(self._get_system_specs)

    # ── Private: Windows/Process observation ─────────────────────────────

    def _get_active_windows(self) -> List[Dict[str, Any]]:
        """Get active windows with titles."""
        if sys.platform != "win32":
            return []

        try:
            ps = (
                'Get-Process | Where-Object {$_.MainWindowTitle -ne ""} '
                '| Select-Object -First 15 Id, ProcessName, MainWindowTitle '
                '| ConvertTo-Json -Compress'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                return [
                    {
                        "pid": item.get("Id"),
                        "name": item.get("ProcessName", ""),
                        "title": item.get("MainWindowTitle", ""),
                    }
                    for item in data
                ]
        except Exception as e:
            logger.warning("Failed to get active windows: %s", e)
        return []

    def _get_key_processes(self) -> List[Dict[str, Any]]:
        """Get noteworthy running processes (dev tools, servers, etc.)."""
        interesting = {
            "code", "node", "python", "python3", "dotnet", "java", "javaw",
            "npm", "npx", "cargo", "rustc", "go", "ruby", "php",
            "docker", "wsl", "git", "powershell", "pwsh", "cmd",
            "chrome", "firefox", "msedge", "brave",
            "devenv", "rider", "idea64", "pycharm64",
            "spotify", "discord", "slack", "teams",
        }

        if sys.platform != "win32":
            return []

        try:
            ps = (
                'Get-Process | Select-Object -First 60 Id, ProcessName, '
                '@{N="MemMB";E={[math]::Round($_.WorkingSet64/1MB,1)}} '
                '| ConvertTo-Json -Compress'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                return [
                    {
                        "pid": item.get("Id"),
                        "name": item.get("ProcessName", ""),
                        "mem_mb": item.get("MemMB", 0),
                    }
                    for item in data
                    if (item.get("ProcessName") or "").lower() in interesting
                ]
        except Exception as e:
            logger.warning("Failed to get key processes: %s", e)
        return []

    # ── Private: System specs ────────────────────────────────────────────

    def _get_system_specs(self) -> Dict[str, Any]:
        """Get CPU, RAM, disk basics."""
        specs: Dict[str, Any] = {}

        try:
            import psutil
            specs["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            specs["cpu_count"] = psutil.cpu_count()
            specs["cpu_count_logical"] = psutil.cpu_count(logical=True)
            mem = psutil.virtual_memory()
            specs["total_ram_gb"] = round(mem.total / (1024 ** 3), 1)
            specs["available_ram_gb"] = round(mem.available / (1024 ** 3), 1)
            specs["ram_percent"] = mem.percent
            disk = psutil.disk_usage("/") if sys.platform != "win32" else psutil.disk_usage("C:\\")
            specs["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
            specs["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
            specs["disk_percent"] = disk.percent
        except ImportError:
            specs["psutil_available"] = False

        # CPU name
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Processor).Name"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    specs["cpu_name"] = result.stdout.strip()
            except Exception:
                pass

        return specs

    def _query_temperatures(self) -> Dict[str, Any]:
        """Query CPU/system temperatures."""
        temps: Dict[str, Any] = {"source": "temperature_query"}

        if sys.platform == "win32":
            try:
                # Try Open Hardware Monitor / LibreHardwareMonitor WMI
                ps = (
                    'Get-CimInstance -Namespace "root/OpenHardwareMonitor" '
                    '-ClassName Sensor -ErrorAction SilentlyContinue '
                    '| Where-Object {$_.SensorType -eq "Temperature"} '
                    '| Select-Object -First 5 Name, Value '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    temps["sensors"] = [
                        {"name": s.get("Name", ""), "value_c": s.get("Value")}
                        for s in data
                    ]
                    return temps
            except Exception:
                pass

            # Fallback: WMIC thermal zone
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi "
                     "-ErrorAction SilentlyContinue | Select-Object InstanceName, CurrentTemperature "
                     "| ConvertTo-Json -Compress"],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    temps["thermal_zones"] = [
                        {
                            "zone": s.get("InstanceName", ""),
                            "temp_c": round((s.get("CurrentTemperature", 0) - 2732) / 10, 1),
                        }
                        for s in data
                    ]
                    return temps
            except Exception:
                pass

            temps["note"] = "Temperature monitoring requires admin privileges or Open Hardware Monitor running."
        else:
            try:
                import psutil
                sensor_temps = psutil.sensors_temperatures()
                if sensor_temps:
                    temps["sensors"] = {
                        name: [{"label": s.label, "current": s.current, "high": s.high, "critical": s.critical}
                               for s in sensors]
                        for name, sensors in sensor_temps.items()
                    }
                    return temps
            except Exception:
                pass
            temps["note"] = "No temperature data available."

        return temps

    def _query_gpu(self) -> Dict[str, Any]:
        """Query GPU information."""
        gpu: Dict[str, Any] = {"source": "gpu_query"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-CimInstance Win32_VideoController '
                    '| Select-Object Name, DriverVersion, AdapterRAM, VideoProcessor, Status '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    gpu["adapters"] = [
                        {
                            "name": g.get("Name", ""),
                            "driver": g.get("DriverVersion", ""),
                            "vram_mb": round(g.get("AdapterRAM", 0) / (1024 * 1024)) if g.get("AdapterRAM") else None,
                            "processor": g.get("VideoProcessor", ""),
                            "status": g.get("Status", ""),
                        }
                        for g in data
                    ]
                    if gpu["adapters"]:
                        gpu["gpu_name"] = gpu["adapters"][0].get("name", "")
            except Exception as e:
                gpu["error"] = str(e)

            # Try nvidia-smi for NVIDIA GPUs
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(",")
                    if len(parts) >= 5:
                        gpu["nvidia"] = {
                            "name": parts[0].strip(),
                            "temp_c": int(parts[1].strip()),
                            "utilization_pct": int(parts[2].strip()),
                            "vram_used_mb": int(parts[3].strip()),
                            "vram_total_mb": int(parts[4].strip()),
                        }
            except FileNotFoundError:
                pass
            except Exception:
                pass

        return gpu

    def _query_cpu_detail(self) -> Dict[str, Any]:
        """Detailed CPU information."""
        info: Dict[str, Any] = {"source": "cpu_detail"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-CimInstance Win32_Processor '
                    '| Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, '
                    'MaxClockSpeed, CurrentClockSpeed, L2CacheSize, L3CacheSize, Architecture '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        info.update(data)
            except Exception as e:
                info["error"] = str(e)

        try:
            import psutil
            info["cpu_percent_per_core"] = psutil.cpu_percent(interval=0.3, percpu=True)
            info["cpu_freq"] = psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
        except ImportError:
            pass

        return info

    def _query_memory_detail(self) -> Dict[str, Any]:
        """Detailed memory information."""
        info: Dict[str, Any] = {"source": "memory_detail"}
        try:
            import psutil
            vm = psutil.virtual_memory()
            info["total_gb"] = round(vm.total / (1024 ** 3), 2)
            info["available_gb"] = round(vm.available / (1024 ** 3), 2)
            info["used_gb"] = round(vm.used / (1024 ** 3), 2)
            info["percent"] = vm.percent
            sw = psutil.swap_memory()
            info["swap_total_gb"] = round(sw.total / (1024 ** 3), 2)
            info["swap_used_gb"] = round(sw.used / (1024 ** 3), 2)
            info["swap_percent"] = sw.percent
        except ImportError:
            info["note"] = "psutil not available"
        return info

    def _query_disk_detail(self) -> Dict[str, Any]:
        """Detailed disk/storage information."""
        info: Dict[str, Any] = {"source": "disk_detail"}
        try:
            import psutil
            partitions = psutil.disk_partitions()
            disks = []
            for p in partitions[:6]:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    disks.append({
                        "device": p.device,
                        "mountpoint": p.mountpoint,
                        "fstype": p.fstype,
                        "total_gb": round(usage.total / (1024 ** 3), 1),
                        "free_gb": round(usage.free / (1024 ** 3), 1),
                        "percent": usage.percent,
                    })
                except PermissionError:
                    pass
            info["partitions"] = disks
        except ImportError:
            info["note"] = "psutil not available"

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-PhysicalDisk | Select-Object FriendlyName, MediaType, Size, HealthStatus '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    info["physical_disks"] = [
                        {
                            "name": d.get("FriendlyName", ""),
                            "type": d.get("MediaType", ""),
                            "size_gb": round(d.get("Size", 0) / (1024 ** 3), 1) if d.get("Size") else None,
                            "health": d.get("HealthStatus", ""),
                        }
                        for d in data
                    ]
            except Exception:
                pass

        return info

    def _query_installed_software(self) -> Dict[str, Any]:
        """Query installed software/programs."""
        info: Dict[str, Any] = {"source": "installed_software"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* '
                    '| Where-Object {$_.DisplayName} '
                    '| Select-Object -First 30 DisplayName, DisplayVersion, Publisher '
                    '| Sort-Object DisplayName '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    info["programs"] = [
                        {
                            "name": p.get("DisplayName", ""),
                            "version": p.get("DisplayVersion", ""),
                            "publisher": p.get("Publisher", ""),
                        }
                        for p in data
                    ]
            except Exception as e:
                info["error"] = str(e)

        return info

    def _query_services(self) -> Dict[str, Any]:
        """Query running services."""
        info: Dict[str, Any] = {"source": "services"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-Service | Where-Object {$_.Status -eq "Running"} '
                    '| Select-Object -First 30 Name, DisplayName '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    info["running_services"] = [
                        {"name": s.get("Name", ""), "display": s.get("DisplayName", "")}
                        for s in data
                    ]
            except Exception as e:
                info["error"] = str(e)

        return info

    def _query_env_vars(self) -> Dict[str, Any]:
        """Query environment variables."""
        important_vars = [
            "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP",
            "HOME", "COMPUTERNAME", "USERNAME", "OS", "PROCESSOR_ARCHITECTURE",
            "ProgramFiles", "ProgramFiles(x86)", "SystemRoot",
            "JAVA_HOME", "PYTHON_HOME", "NODE_PATH", "GOPATH", "CARGO_HOME",
        ]
        return {
            "source": "environment_variables",
            "variables": {
                var: os.environ.get(var, "")
                for var in important_vars
                if os.environ.get(var)
            },
        }

    def _query_uptime(self) -> Dict[str, Any]:
        """Query system uptime."""
        info: Dict[str, Any] = {"source": "uptime"}
        try:
            import psutil
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            info["boot_time"] = boot_time.isoformat()
            info["uptime_hours"] = round(uptime.total_seconds() / 3600, 1)
            info["uptime_human"] = str(uptime).split(".")[0]
        except ImportError:
            if sys.platform == "win32":
                try:
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        info["last_boot"] = result.stdout.strip()
                except Exception:
                    pass
        return info

    def _get_display_info(self) -> Dict[str, Any]:
        """Get display/monitor information."""
        info: Dict[str, Any] = {"source": "display"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-CimInstance Win32_VideoController '
                    '| Select-Object CurrentHorizontalResolution, CurrentVerticalResolution, '
                    'CurrentRefreshRate, VideoModeDescription '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    info["monitors"] = [
                        {
                            "width": d.get("CurrentHorizontalResolution"),
                            "height": d.get("CurrentVerticalResolution"),
                            "refresh_hz": d.get("CurrentRefreshRate"),
                            "mode": d.get("VideoModeDescription", ""),
                        }
                        for d in data
                    ]
            except Exception as e:
                info["error"] = str(e)

        return info

    def _get_network_info(self) -> Dict[str, Any]:
        """Get network adapter information."""
        info: Dict[str, Any] = {"source": "network"}

        if sys.platform == "win32":
            try:
                ps = (
                    'Get-NetAdapter | Where-Object {$_.Status -eq "Up"} '
                    '| Select-Object Name, InterfaceDescription, LinkSpeed, MacAddress '
                    '| ConvertTo-Json -Compress'
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    info["adapters"] = [
                        {
                            "name": a.get("Name", ""),
                            "description": a.get("InterfaceDescription", ""),
                            "speed": a.get("LinkSpeed", ""),
                        }
                        for a in data
                    ]
            except Exception as e:
                info["error"] = str(e)

        return info

    def _get_dir_tree(self, working_dir: str, max_entries: int = 20) -> Dict[str, Any]:
        """Get a compact directory listing."""
        wd = Path(working_dir)
        if not wd.is_dir():
            return {"path": str(wd), "error": "Not a directory"}

        entries = []
        try:
            for item in sorted(wd.iterdir())[:max_entries]:
                entry = {"name": item.name, "is_dir": item.is_dir()}
                if item.is_file():
                    try:
                        entry["size_kb"] = round(item.stat().st_size / 1024, 1)
                    except OSError:
                        pass
                entries.append(entry)
        except PermissionError:
            return {"path": str(wd), "error": "Permission denied"}

        return {"path": str(wd), "entries": entries, "total_items": len(list(wd.iterdir()))}


# ── Singleton ────────────────────────────────────────────────────────────────

_env_context_service: Optional[EnvironmentContextService] = None


def get_environment_context_service() -> EnvironmentContextService:
    global _env_context_service
    if _env_context_service is None:
        _env_context_service = EnvironmentContextService()
    return _env_context_service
