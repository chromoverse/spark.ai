"""
Drive file read endpoint — serves file content to the Spark UI using
the user's already-stored OAuth credentials. No re-authentication needed.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/drive", tags=["Drive"])

_EXPORT_MAP: Dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document":     ("text/plain", "text"),
    "application/vnd.google-apps.spreadsheet":  ("text/csv",   "csv"),
    "application/vnd.google-apps.presentation": ("text/plain", "text"),
    "application/vnd.google-apps.drawing":      ("image/svg+xml", "text"),
}

_TEXT_MIMES = {
    "application/json", "application/xml", "application/javascript",
    "application/typescript",
}

_MAX_TEXT_BYTES = 80_000   # ~80 KB text cap
_MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB image cap


@router.get("/read")
async def read_drive_file(user_id: str, file_id: str) -> Dict[str, Any]:
    """
    Read a Google Drive file by ID using the user's stored OAuth token.
    Returns text content, base64 image, or a binary-only descriptor.
    """
    from app.connectors.clients.drive import get_drive_service

    try:
        service = await get_drive_service(user_id=user_id)
    except Exception as exc:
        logger.error("drive/read: could not get Drive service for user %s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=f"Drive not connected: {exc}")

    try:
        meta = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, webViewLink",
        ).execute()
    except Exception as exc:
        logger.error("drive/read: metadata fetch failed for file %s: %s", file_id, exc)
        raise HTTPException(status_code=404, detail=f"File not found: {exc}")

    mime: str = meta.get("mimeType", "")
    name: str = meta.get("name", "")
    size: int = int(meta.get("size") or 0)
    link: str = meta.get("webViewLink", "")

    # ── Google Workspace docs → export as text/CSV
    if mime in _EXPORT_MAP:
        export_mime, content_type = _EXPORT_MAP[mime]
        try:
            resp = service.files().export(fileId=file_id, mimeType=export_mime).execute()
            text = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)
            truncated = len(text) > _MAX_TEXT_BYTES
            return {
                "success": True,
                "name": name, "mime_type": mime, "size_bytes": size,
                "content_type": content_type,
                "content": text[:_MAX_TEXT_BYTES],
                "truncated": truncated,
            }
        except Exception as exc:
            logger.warning("drive/read: export failed for %s: %s", file_id, exc)
            return {"success": False, "name": name, "mime_type": mime, "size_bytes": size,
                    "content_type": "binary", "content": None, "link": link,
                    "error": str(exc)}

    # ── Plain text / JSON / XML / code files
    if mime.startswith("text/") or mime in _TEXT_MIMES:
        try:
            resp = service.files().get_media(fileId=file_id).execute()
            text = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)
            truncated = len(text) > _MAX_TEXT_BYTES
            ct = "csv" if mime == "text/csv" else "text"
            return {
                "success": True,
                "name": name, "mime_type": mime, "size_bytes": size,
                "content_type": ct,
                "content": text[:_MAX_TEXT_BYTES],
                "truncated": truncated,
            }
        except Exception as exc:
            logger.warning("drive/read: text read failed for %s: %s", file_id, exc)

    # ── Images → base64 inline
    if mime.startswith("image/"):
        if size > _MAX_IMAGE_BYTES:
            return {
                "success": True,
                "name": name, "mime_type": mime, "size_bytes": size,
                "content_type": "binary", "content": None, "link": link,
                "note": "Image too large to preview inline",
            }
        try:
            resp = service.files().get_media(fileId=file_id).execute()
            b64 = base64.b64encode(resp).decode("ascii") if isinstance(resp, bytes) else None
            return {
                "success": True,
                "name": name, "mime_type": mime, "size_bytes": size,
                "content_type": "image",
                "content": b64,
                "truncated": False,
            }
        except Exception as exc:
            logger.warning("drive/read: image fetch failed for %s: %s", file_id, exc)

    # ── Binary / unsupported — return descriptor only
    return {
        "success": True,
        "name": name, "mime_type": mime, "size_bytes": size,
        "content_type": "binary", "content": None, "link": link,
    }
