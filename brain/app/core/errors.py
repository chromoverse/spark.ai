"""API.md §1 envelope. Messages follow PERSONA.md; raw errors never leave the brain."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

STATUS = {
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "invalid_input": 422,
    "rate_limited": 429,
    "quota_exceeded": 429,
    "provider_unavailable": 503,
    "internal": 500,
}

SIGN_IN_AGAIN = "You've been signed out. Sign in again and we're good."
NOT_FOUND = "Couldn't find that one."
BAD_INPUT = "That didn't look quite right. Check the details and try again."
INTERNAL = "Something broke on my side. Give it another go in a moment."


class ApiError(Exception):
    def __init__(self, code: str, message: str, retry_after_s: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after_s is not None:
            err["retry_after_s"] = self.retry_after_s
        return {"ok": False, "error": err}


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _json(err: ApiError) -> JSONResponse:
    headers = {"Retry-After": str(err.retry_after_s)} if err.retry_after_s is not None else None
    return JSONResponse(err.body(), status_code=STATUS[err.code], headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return _json(exc)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json(ApiError("invalid_input", BAD_INPUT))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 401:
            return _json(ApiError("unauthorized", SIGN_IN_AGAIN))
        if exc.status_code == 404:
            return _json(ApiError("not_found", NOT_FOUND))
        if exc.status_code == 405:
            return JSONResponse(ApiError("not_found", NOT_FOUND).body(), status_code=405)
        return _json(ApiError("invalid_input", BAD_INPUT))

    @app.exception_handler(Exception)
    async def _crash(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", exc_info=exc)
        return _json(ApiError("internal", INTERNAL))
