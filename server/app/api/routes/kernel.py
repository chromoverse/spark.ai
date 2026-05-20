from fastapi import APIRouter, Query

from app.kernel.persistence.services import get_kernel_log_service, get_kernel_stats_service

router = APIRouter(prefix="/kernel", tags=["kernel"])


@router.get("/user-metrics")
async def get_user_metrics(
    user_id: str = Query(...),
    window: str = Query("30d"),
):
    return await get_kernel_stats_service().get_user_metrics(user_id=user_id, window=window)


@router.get("/user-history")
async def get_user_history(
    user_id: str = Query(...),
    window: str = Query("90d"),
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return await get_kernel_stats_service().get_user_task_history(
        user_id=user_id,
        window=window,
        cursor=cursor,
        limit=limit,
    )


@router.get("/user-logs")
async def get_user_logs(
    user_id: str = Query(...),
    startup_id: str | None = Query(default=None),
    level: str | None = Query(default=None),
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    return await get_kernel_log_service().query_user_logs(
        user_id=user_id,
        startup_id=startup_id,
        level=level,
        cursor=cursor,
        limit=limit,
    )


@router.get("/tools/runtime-summary")
async def get_runtime_tools_summary():
    return await get_kernel_stats_service().get_runtime_summary()


@router.get("/tools")
async def list_tools(
    category: str | None = Query(default=None),
    execution_target: str | None = Query(default=None),
):
    """List all registered tools with optional filtering."""
    from app.plugins.tools.catalog_service import get_tool_catalog_service
    return get_tool_catalog_service().summary(
        category=category,
        execution_target=execution_target,
    )


@router.get("/plugins")
async def list_plugins():
    """List all installed plugins and their status."""
    from plugins.manager import get_plugin_manager
    return {"plugins": get_plugin_manager().list_plugins()}


@router.get("/skills")
async def list_skills():
    """List all registered skills."""
    from plugins.skills.skill_engine import get_skill_engine
    return {"skills": get_skill_engine().list_skills()}


@router.get("/permissions")
async def get_permissions(user_id: str = Query(...)):
    """Get all permissions granted by a user."""
    from app.services.shell.user_permissions import get_user_permission_store
    store = get_user_permission_store()
    data = store._data.get(user_id, {"full_access": False, "allowed_commands": []})
    return {
        "full_access": data.get("full_access", False),
        "allowed_commands": data.get("allowed_commands", []),
    }


@router.post("/permissions/revoke")
async def revoke_permission(user_id: str = Query(...), command: str = Query(default=None)):
    """Revoke a specific command permission or full access."""
    from app.services.shell.user_permissions import get_user_permission_store
    store = get_user_permission_store()
    if command:
        user_data = store._data.get(user_id, {})
        cmds = user_data.get("allowed_commands", [])
        if command in cmds:
            cmds.remove(command)
            store._save()
        return {"revoked": command}
    else:
        store.revoke_full_access(user_id)
        return {"revoked": "full_access"}

