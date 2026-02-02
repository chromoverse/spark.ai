# app/utils/response_helpers.py
from typing import Any, Optional
from fastapi.responses import JSONResponse
from fastapi import Request

def send_response(
    request: Request,
    data: Any = None,
    message: str = "Success",
    status_code: int = 200,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None
) -> JSONResponse:
    """Secure response handler with Electron detection"""

    user_agent = request.headers.get("user-agent", "").lower()
    is_electron = "electron" in user_agent

    payload = {
        "success": True,
        "message": message,
        "data": data
    }

    if access_token:
        # ✅ only include in body for Electron
        if is_electron:
            payload["access_token"] = access_token

    if refresh_token:
        # ✅ only include in body for Electron
        if is_electron:
            payload["refresh_token"] = refresh_token

    response = JSONResponse(status_code=status_code, content=payload)

    if access_token:
        # ✅ always set cookie for browsers
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=30 * 60
        )

    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=7 * 24 * 60 * 60
        )

    return response

def send_error(
    message: str = "An error occurred",
    status_code: int = 400,
    errors: Optional[Any] = None
) -> JSONResponse:
    """Send an error response"""
    content = {
        "success": False,
        "message": message
    }
    if errors is not None:
        content["errors"] = errors
    
    return JSONResponse(
        status_code=status_code,
        content=content
    )