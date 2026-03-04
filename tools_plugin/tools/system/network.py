"""
Network status and connectivity tools.
"""

import socket
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class NetworkStatusTool(BaseTool):
    """Get network connectivity and IP information."""

    def get_tool_name(self) -> str:
        return "network_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get network status including connectivity, IPs, and network name."""
        check_internet = self.get_input(inputs, "check_internet", True)
        
        try:
            network_info = self._get_network_info(check_internet)
            
            return ToolOutput(
                success=True,
                data={
                    "connected": network_info.get("connected", False),
                    "local_ip": network_info.get("local_ip", "N/A"),
                    "public_ip": network_info.get("public_ip", "N/A"),
                    "network_name": network_info.get("network_name", "N/A"),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to get network status: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_network_info(self, check_internet: bool) -> Dict[str, Any]:
        """Get network information."""
        info = {
            "connected": False,
            "local_ip": "N/A",
            "public_ip": "N/A",
            "network_name": "N/A",
        }
        
        # Get local IP
        try:
            # Create a socket to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            info["local_ip"] = s.getsockname()[0]
            s.close()
        except Exception as e:
            self.logger.warning(f"Failed to get local IP: {e}")
        
        # Check internet connectivity
        if check_internet:
            info["connected"] = self._check_internet_connectivity()
            
            # Get public IP if connected
            if info["connected"]:
                info["public_ip"] = self._get_public_ip()
        
        # Get network name
        info["network_name"] = self._get_network_name()
        
        return info

    def _check_internet_connectivity(self) -> bool:
        """Check if we have internet connectivity."""
        import socket as s
        
        # Try multiple reliable hosts
        hosts = [
            ("8.8.8.8", 53),      # Google DNS
            ("1.1.1.1", 53),      # Cloudflare DNS
            ("9.9.9.9", 53),      # Quad9 DNS
        ]
        
        for host, port in hosts:
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
        """Get public IP address using external services."""
        import urllib.request
        
        services = [
            "https://api.ipify.org?format=text",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
        ]
        
        for service in services:
            try:
                req = urllib.request.Request(
                    service,
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read().decode('utf-8').strip()
            except Exception as e:
                self.logger.warning(f"Failed to get public IP from {service}: {e}")
                continue
        
        return "N/A"

    def _get_network_name(self) -> str:
        """Get the name of the connected network (SSID)."""
        import subprocess
        import sys
        
        try:
            if sys.platform == "win32":
                # Windows: use netsh
                result = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'SSID' in line and 'BSSID' not in line:
                            # Parse SSID
                            parts = line.split(':')
                            if len(parts) > 1:
                                return parts[1].strip()
                
                # Check if on Ethernet
                result = subprocess.run(
                    ["netsh", "interface", "show", "interface"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if "Ethernet" in result.stdout and "Connected" in result.stdout:
                    return "Ethernet"
                    
            elif sys.platform == "darwin":
                # macOS: use airport or networksetup
                result = subprocess.run(
                    ["networksetup", "-getairportnetwork", "en0"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and "Wi-Fi" not in result.stdout:
                    # Parse SSID
                    if ":" in result.stdout:
                        return result.stdout.split(":")[1].strip()
                        
            else:
                # Linux: use nmcli or iwconfig
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith("yes:"):
                            return line.split(":")[1].strip()
        except FileNotFoundError:
            self.logger.warning("Network tools not found")
        except Exception as e:
            self.logger.warning(f"Failed to get network name: {e}")
        
        return "N/A"


# Export all tools for registration
__all__ = ["NetworkStatusTool"]