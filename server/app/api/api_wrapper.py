from fastapi import FastAPI

from app.api.routes import build_api_router


def include_api_routes(app: FastAPI) -> None:
    """Mount the unified API router on the FastAPI app."""
    app.include_router(build_api_router())
