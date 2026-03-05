from __future__ import annotations

from fastapi import APIRouter

from . import auth, chat, kernel, ml_test, openrouter_debug, stt, system, tts

ROUTE_MODULES = (
    system,
    chat,
    tts,
    stt,
    auth,
    ml_test,
    openrouter_debug,
    kernel,
)


def build_api_router() -> APIRouter:
    router = APIRouter()
    for module in ROUTE_MODULES:
        router.include_router(module.router)
    return router


__all__ = ["ROUTE_MODULES", "build_api_router"]
