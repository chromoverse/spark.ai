from fastapi import APIRouter

from app.agent.execution_gateway import get_orchestrator
from app.bootstrap.runtime_dependency_bootstrap import get_last_runtime_dependency_report
from app.plugins.tools.registry_loader import get_tool_registry

router = APIRouter(tags=["System"])


def _load_ml_runtime():
    from app.ml import MODELS_CONFIG, get_device, get_device_profile, model_loader

    return get_device(), get_device_profile(), MODELS_CONFIG, model_loader


@router.get("/")
def read_root():
    device = "unknown"
    try:
        device, _, _, _ = _load_ml_runtime()
    except Exception:
        pass
    return {
        "message": "Your AI assistant is ready!",
        "device": device,
        "socket": "/socket.io",
        "docs": "/docs",
    }


@router.get("/health")
def health_check():
    """Health check endpoint."""
    orchestrator = get_orchestrator()
    registry = get_tool_registry()
    device = "unknown"
    device_profile = {}
    models_loaded = []
    try:
        device, profile, _, model_loader = _load_ml_runtime()
        device_profile = profile.to_dict()
        models_loaded = list(model_loader._models.keys())
    except Exception as exc:
        device_profile = {"status": "unavailable", "reason": str(exc)}

    dep_report = get_last_runtime_dependency_report()
    dep_status = dep_report.to_dict() if dep_report else {"status": "not_run"}
    overall_status = "healthy"
    if dep_report and not dep_report.ok:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "device": device,
        "device_profile": device_profile,
        "models_loaded": models_loaded,
        "tools_loaded": len(registry.tools),
        "active_users": len(orchestrator.states),
        "runtime_dependencies": dep_status,
    }


@router.get("/ml/status")
def ml_status():
    """Check ML models status."""
    try:
        device, device_profile, models_config, model_loader = _load_ml_runtime()
    except Exception as exc:
        return {
            "device": "unknown",
            "device_profile": {"status": "unavailable", "reason": str(exc)},
            "models_loaded": [],
            "models_available": [],
        }

    return {
        "device": device,
        "device_profile": device_profile.to_dict(),
        "models_loaded": list(model_loader._models.keys()),
        "models_available": list(models_config.keys()),
    }


@router.get("/orchestration/status")
def orchestration_status():
    """Check orchestration system status."""
    registry = get_tool_registry()
    orchestrator = get_orchestrator()

    return {
        "registry": {
            "total_tools": len(registry.tools),
            "server_tools": len(registry.server_tools),
            "client_tools": len(registry.client_tools),
            "categories": list(registry.categories.keys()),
        },
        "orchestrator": {
            "active_users": len(orchestrator.states),
            "total_tasks": sum(len(state.tasks) for state in orchestrator.states.values()),
        },
    }


@router.get("/runtime/dependencies")
def runtime_dependencies_status():
    """Show device profile and runtime dependency bootstrap status."""
    report = get_last_runtime_dependency_report()
    if report is None:
        return {
            "status": "not_run",
            "message": "Runtime dependency bootstrap has not run yet.",
        }
    return report.to_dict()
