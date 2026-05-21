"""Network status and connectivity tools."""
import asyncio
import socket
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class NetworkStatusTool(BaseTool):
    """Get network connectivity and IP information."""

    TOOL_DESCRIPTION = "Internet connectivity and IP info"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {"check_internet": {"type": "boolean", "required": False, "default": True}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"connected": {"type": "boolean"}, "local_ip": {"type": "string"}, "public_ip": {"type": "string"}, "network_name": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "am I connected to the internet"}]
    SEMANTIC_TAGS = ["system", "network", "status"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "network_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        check_internet = self.get_input(inputs, "check_internet", True)
        try:
            network_info = await asyncio.to_thread(self._get_network_info, check_internet)
            return ToolOutput(success=True, data={**network_info, "timestamp": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_network_info(self, check_internet: bool) -> Dict[str, Any]:
        info = {"connected": False, "local_ip": "N/A", "public_ip": "N/A", "network_name": "N/A"}
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            info["local_ip"] = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        if check_internet:
            info["connected"] = self._check_internet()
            if info["connected"]:
                info["public_ip"] = self._get_public_ip()
        info["network_name"] = self._get_network_name()
        return info

    def _check_internet(self) -> bool:
        import socket as s
        for host, port in [("8.8.8.8", 53), ("1.1.1.1", 53), ("9.9.9.9", 53)]:
            try:
                sock = s.socket(s.AF_INET, s.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    return True
            except Exception:
                continue
        return False

    def _get_public_ip(self) -> str:
        import urllib.request
        for service in ["https://api.ipify.org?format=text", "https://icanhazip.com", "https://ifconfig.me/ip"]:
            try:
                req = urllib.request.Request(service, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read().decode('utf-8').strip()
            except Exception:
                continue
        return "N/A"

    def _get_network_name(self) -> str:
        import sys
        try:
            if sys.platform == "win32":
                result = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'SSID' in line and 'BSSID' not in line:
                            parts = line.split(':')
                            if len(parts) > 1:
                                return parts[1].strip()
                result = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True, timeout=5)
                if "Ethernet" in result.stdout and "Connected" in result.stdout:
                    return "Ethernet"
            elif sys.platform == "darwin":
                result = subprocess.run(["networksetup", "-getairportnetwork", "en0"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and ":" in result.stdout:
                    return result.stdout.split(":")[1].strip()
            else:
                result = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith("yes:"):
                            return line.split(":")[1].strip()
        except Exception:
            pass
        return "N/A"


__all__ = ["NetworkStatusTool"]
