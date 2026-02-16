

# System info tool (kept here as it's simple)
import psutil
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class SystemInfoTool(BaseTool):
    """Get CPU, RAM, Disk usage."""

    def get_tool_name(self) -> str:
        return "system_info"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get system metrics."""
        metrics = self.get_input(inputs, "metrics", ["cpu", "ram", "disk"])
        
        try:
            data = {}
            
            if "cpu" in metrics:
                data["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            
            if "ram" in metrics:
                ram = psutil.virtual_memory()
                data["ram_percent"] = ram.percent
                data["ram_used_gb"] = round(ram.used / (1024**3), 2)
                data["ram_total_gb"] = round(ram.total / (1024**3), 2)
            
            if "disk" in metrics:
                disk = psutil.disk_usage('/')
                data["disk_percent"] = disk.percent
                data["disk_used_gb"] = round(disk.used / (1024**3), 2)
                data["disk_total_gb"] = round(disk.total / (1024**3), 2)
            
            data["timestamp"] = datetime.now().isoformat()
            
            return ToolOutput(success=True, data=data)
            
        except Exception as e:
            self.logger.error(f"Failed to get system info: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

