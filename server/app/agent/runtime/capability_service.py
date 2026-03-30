from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings
from app.kernel.persistence.services import get_kernel_stats_service
from app.ml.model_loader import model_loader


class CapabilityService:
    """
    Section 2 capability snapshot:
    - runtime tools state
    - environment
    - loaded models
    - explicit limitation hints
    """

    async def get_capability_snapshot(self, user_id: str) -> Dict[str, Any]:
        runtime_summary = await get_kernel_stats_service().get_runtime_summary()
        loaded_models = list(model_loader._models.keys())
        limitations = self._derive_limitations(runtime_summary, loaded_models)

        return {
            "user_id": user_id,
            "environment": settings.environment,
            "runtime": runtime_summary,
            "models_loaded": loaded_models,
            "safe_auto_tools": [
                "get_user_task_history",
                "get_user_metrics",
                "get_user_tool_metrics",
                "get_user_log_window",
                "get_runtime_tool_summary",
                "repo_search",
                "repo_read_snippet",
            ],
            "limitations": limitations,
        }

    @staticmethod
    def _derive_limitations(runtime_summary: Dict[str, Any], loaded_models: List[str]) -> List[str]:
        limitations: List[str] = []
        if not runtime_summary.get("runtime_healthy", False):
            limitations.append("Direct tools runtime is unhealthy.")
        if not loaded_models:
            limitations.append("No ML models loaded in memory yet.")
        if runtime_summary.get("total_tools", 0) == 0:
            limitations.append("No tools are currently registered in runtime.")
        if not limitations:
            limitations.append("No critical runtime limitations detected.")
        return limitations


_capability_service: CapabilityService | None = None


def get_capability_service() -> CapabilityService:
    global _capability_service
    if _capability_service is None:
        _capability_service = CapabilityService()
    return _capability_service

