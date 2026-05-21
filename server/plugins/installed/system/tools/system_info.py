"""System info tool."""
import psutil
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SystemInfoTool(BaseTool):
    """Get CPU, RAM, Disk usage."""

    TOOL_DESCRIPTION = "Get CPU, RAM, Disk usage"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {"metrics": {"type": "array", "required": False, "default": ["cpu", "ram", "disk"]}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"cpu_percent": {"type": "number"}, "ram_percent": {"type": "number"}, "disk_percent": {"type": "number"}, "timestamp": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "how much RAM am I using"}]
    SEMANTIC_TAGS = ["system", "system", "info"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "system_info"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        metrics = self.get_input(inputs, "metrics", ["cpu", "ram", "disk"])
        try:
            data: Dict[str, Any] = {}
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
            return ToolOutput(success=False, data={}, error=str(e))


__all__ = ["SystemInfoTool"]
