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

