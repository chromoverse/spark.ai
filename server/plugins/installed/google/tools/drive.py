"""
Google Drive tools — list, search, read, upload, download, move, delete files.

Every tool accepts `user_id` in its inputs to automatically fetch the Drive service.
Upload/move/delete tools are marked as confidential and require approval via the
in-app modal before execution.
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional

from app.connectors.clients.drive import get_drive_service
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)

_SPARK_FOLDER_NAME = "Spark"


async def _emit_progress(user_id: str, task_id: str, tool_name: str, stage: str, message: str) -> None:
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name=tool_name,
            payload={"stage": stage, "message": message},
        )
    except Exception:
        pass


async def _svc(inputs: Dict[str, Any]):
    """Extract or auto-fetch the Drive service object from inputs."""
    service = inputs.get("service")
    if service is not None:
        return service
    user_id = inputs.get("user_id")
    if not user_id:
        raise ValueError("inputs['service'] or inputs['user_id'] is required to authenticate Drive API.")
    account_email = inputs.get("account_email")
    return await get_drive_service(user_id=user_id, account_email=account_email)


async def _ensure_spark_folder(service: Any, folder_name: str = _SPARK_FOLDER_NAME) -> str:
    """Find or create the Spark folder in Drive root. Returns folder ID."""
    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        "and 'root' in parents and trashed=false"
    )
    result = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


# ===========================================================================
# Tool 1 — drive_list
# ===========================================================================

class DriveListTool(BaseTool):
    """
    List files and folders in Google Drive.

    Inputs:
    - query (str, optional): Search query (Drive search syntax)
    - folder_id (str, optional): List contents of a specific folder
    - max_results (int, optional): Max files to return (default 20)

    Outputs:
    - files (list): File entries with id, name, mimeType, size, modifiedTime
    - total (int): Number of files returned
    """

    TOOL_DESCRIPTION = "List files and folders in Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "query": {"type": "string", "required": False, "default": "", "description": "Drive search query (e.g. 'name contains report')"},
        "folder_id": {"type": "string", "required": False, "default": "", "description": "Folder ID to list (empty = root)"},
        "max_results": {"type": "number", "required": False, "default": 20},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"files": {"type": "array"}, "total": {"type": "number"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "what files are in my google drive", "inputs": {}},
        {"user_utterance": "search drive for project report", "inputs": {"query": "name contains 'project report'"}},
    ]
    SEMANTIC_TAGS = ["drive", "google drive", "files", "list", "search", "folders"]
    TOOL_CATEGORY = "storage"

    def get_tool_name(self) -> str:
        return "drive_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            service = await _svc(inputs)

            query = str(inputs.get("query", "")).strip()
            folder_id = str(inputs.get("folder_id", "")).strip()
            max_results = int(inputs.get("max_results", 20))

            await _emit_progress(user_id, task_id, "drive_list", "listing", "Scanning Google Drive...")

            parts = ["trashed=false"]
            if folder_id:
                parts.append(f"'{folder_id}' in parents")
            if query:
                parts.append(query)

            q = " and ".join(parts)
            result = service.files().list(
                q=q,
                spaces="drive",
                fields="files(id, name, mimeType, size, modifiedTime, parents, webViewLink)",
                pageSize=min(max_results, 100),
                orderBy="modifiedTime desc",
            ).execute()

            files = result.get("files", [])
            entries = []
            for f in files:
                entry: Dict[str, Any] = {
                    "id": f["id"],
                    "name": f["name"],
                    "type": "folder" if f["mimeType"] == "application/vnd.google-apps.folder" else "file",
                    "mime_type": f["mimeType"],
                    "modified": f.get("modifiedTime", ""),
                }
                if f.get("size"):
                    entry["size_bytes"] = int(f["size"])
                if f.get("webViewLink"):
                    entry["link"] = f["webViewLink"]
                entries.append(entry)

            return ToolOutput(success=True, data={"files": entries, "total": len(entries)})
        except Exception as exc:
            self.logger.error("drive_list error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 2 — drive_read
# ===========================================================================

class DriveReadTool(BaseTool):
    """
    Read/download content from a Google Drive file.

    Inputs:
    - file_id (str, required): The Drive file ID
    - file_name (str, optional): Search by name instead of ID

    Outputs:
    - content (str): File content (text files) or download info
    - name (str), mime_type (str), size_bytes (int)
    """

    TOOL_DESCRIPTION = "Read or download a file from Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "file_id": {"type": "string", "required": False, "default": "", "description": "Drive file ID"},
        "file_name": {"type": "string", "required": False, "default": "", "description": "Search by file name"},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "content": {"type": "string"},
            "name": {"type": "string"},
            "mime_type": {"type": "string"},
            "size_bytes": {"type": "number"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "read my notes.txt from drive", "inputs": {"file_name": "notes.txt"}},
    ]
    SEMANTIC_TAGS = ["drive", "read", "download", "file", "content"]
    TOOL_CATEGORY = "storage"

    def get_tool_name(self) -> str:
        return "drive_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            service = await _svc(inputs)

            file_id = str(inputs.get("file_id", "")).strip()
            file_name = str(inputs.get("file_name", "")).strip()

            if not file_id and not file_name:
                return ToolOutput(success=False, data={}, error="file_id or file_name is required")

            await _emit_progress(user_id, task_id, "drive_read", "locating", "Finding file...")

            if not file_id and file_name:
                q = f"name='{file_name}' and trashed=false"
                result = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=1).execute()
                files = result.get("files", [])
                if not files:
                    return ToolOutput(success=False, data={}, error=f"File '{file_name}' not found in Drive")
                file_id = files[0]["id"]

            meta = service.files().get(fileId=file_id, fields="id, name, mimeType, size").execute()
            mime = meta.get("mimeType", "")
            name = meta.get("name", "")
            size = int(meta.get("size", 0))

            await _emit_progress(user_id, task_id, "drive_read", "reading", f"Reading {name}...")

            # Google Docs/Sheets/Slides: export as plain text
            _EXPORT_MAP = {
                "application/vnd.google-apps.document": "text/plain",
                "application/vnd.google-apps.spreadsheet": "text/csv",
                "application/vnd.google-apps.presentation": "text/plain",
            }

            content = ""
            if mime in _EXPORT_MAP:
                export_mime = _EXPORT_MAP[mime]
                resp = service.files().export(fileId=file_id, mimeType=export_mime).execute()
                content = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)
            elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
                resp = service.files().get_media(fileId=file_id).execute()
                content = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)
            else:
                content = f"[Binary file: {name} ({mime}, {size} bytes). Use drive_download to save locally.]"

            return ToolOutput(success=True, data={
                "content": content[:10000],
                "name": name,
                "mime_type": mime,
                "size_bytes": size,
            })
        except Exception as exc:
            self.logger.error("drive_read error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 3 — drive_upload (CONFIDENTIAL — requires approval)
# ===========================================================================

class DriveUploadTool(BaseTool):
    """
    Upload content or a local file to Google Drive.

    Inputs:
    - file_name (str, required): Name for the uploaded file
    - content (str, optional): Text content to upload
    - local_path (str, optional): Local file path to upload
    - folder_name (str, optional): Target folder name (default: "Spark")
    - folder_id (str, optional): Target folder ID (overrides folder_name)
    - mime_type (str, optional): MIME type (auto-detected if omitted)

    Outputs:
    - file_id (str), name (str), folder (str), link (str)
    """

    TOOL_DESCRIPTION = "Upload a file or content to Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "file_name": {"type": "string", "required": True, "description": "Name for the file in Drive"},
        "content": {"type": "string", "required": False, "default": "", "description": "Text content to upload"},
        "local_path": {"type": "string", "required": False, "default": "", "description": "Local file path to upload"},
        "folder_name": {"type": "string", "required": False, "default": "Spark", "description": "Target folder name in Drive"},
        "folder_id": {"type": "string", "required": False, "default": ""},
        "mime_type": {"type": "string", "required": False, "default": ""},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "file_id": {"type": "string"},
            "name": {"type": "string"},
            "folder": {"type": "string"},
            "link": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "save this to my google drive", "inputs": {"file_name": "notes.txt", "content": "Hello world"}},
        {"user_utterance": "upload report.pdf to drive", "inputs": {"file_name": "report.pdf", "local_path": "C:/Users/me/report.pdf"}},
    ]
    SEMANTIC_TAGS = ["drive", "upload", "save", "google drive", "cloud", "backup"]
    TOOL_CATEGORY = "storage"
    METADATA: Dict[str, Any] = {"summary_tts": True}

    def get_tool_name(self) -> str:
        return "drive_upload"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            service = await _svc(inputs)

            file_name = str(inputs.get("file_name", "")).strip()
            content = str(inputs.get("content", "")).strip()
            local_path = str(inputs.get("local_path", "")).strip()
            folder_name = str(inputs.get("folder_name", _SPARK_FOLDER_NAME)).strip()
            folder_id = str(inputs.get("folder_id", "")).strip()
            mime_type = str(inputs.get("mime_type", "")).strip()

            if not file_name:
                return ToolOutput(success=False, data={}, error="file_name is required")
            if not content and not local_path:
                return ToolOutput(success=False, data={}, error="Either content or local_path is required")

            await _emit_progress(user_id, task_id, "drive_upload", "preparing", f"Preparing to upload {file_name}...")

            # Resolve target folder
            if not folder_id:
                folder_id = await _ensure_spark_folder(service, folder_name)

            # Detect MIME type
            if not mime_type:
                mime_type = mimetypes.guess_type(file_name)[0] or "text/plain"

            from googleapiclient.http import MediaIoBaseUpload

            if local_path:
                if not os.path.isfile(local_path):
                    return ToolOutput(success=False, data={}, error=f"Local file not found: {local_path}")
                with open(local_path, "rb") as fh:
                    file_bytes = fh.read()
                media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
            else:
                media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=mime_type, resumable=True)

            file_meta = {
                "name": file_name,
                "parents": [folder_id],
            }

            await _emit_progress(user_id, task_id, "drive_upload", "uploading", f"Uploading {file_name} to Drive...")

            uploaded = service.files().create(
                body=file_meta,
                media_body=media,
                fields="id, name, webViewLink",
            ).execute()

            return ToolOutput(success=True, data={
                "file_id": uploaded["id"],
                "name": uploaded["name"],
                "folder": folder_name,
                "link": uploaded.get("webViewLink", ""),
            })
        except Exception as exc:
            self.logger.error("drive_upload error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 4 — drive_move (CONFIDENTIAL — requires approval)
# ===========================================================================

class DriveMoveTool(BaseTool):
    """
    Move a file to a different folder in Google Drive.

    Inputs:
    - file_id (str, required): File to move
    - destination (str, optional): Destination folder name
    - destination_id (str, optional): Destination folder ID

    Outputs:
    - file_id (str), name (str), destination (str)
    """

    TOOL_DESCRIPTION = "Move a file to a different folder in Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "file_id": {"type": "string", "required": True},
        "destination": {"type": "string", "required": False, "default": "", "description": "Destination folder name"},
        "destination_id": {"type": "string", "required": False, "default": "", "description": "Destination folder ID"},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"file_id": {"type": "string"}, "name": {"type": "string"}, "destination": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "move file to Spark folder in drive", "inputs": {"file_id": "abc123"}}]
    SEMANTIC_TAGS = ["drive", "move", "organize"]
    TOOL_CATEGORY = "storage"

    def get_tool_name(self) -> str:
        return "drive_move"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            service = await _svc(inputs)

            file_id = str(inputs.get("file_id", "")).strip()
            destination = str(inputs.get("destination", _SPARK_FOLDER_NAME)).strip()
            destination_id = str(inputs.get("destination_id", "")).strip()

            if not file_id:
                return ToolOutput(success=False, data={}, error="file_id is required")

            if not destination_id:
                destination_id = await _ensure_spark_folder(service, destination)

            current = service.files().get(fileId=file_id, fields="parents, name").execute()
            prev_parents = ",".join(current.get("parents", []))

            updated = service.files().update(
                fileId=file_id,
                addParents=destination_id,
                removeParents=prev_parents,
                fields="id, name",
            ).execute()

            return ToolOutput(success=True, data={
                "file_id": updated["id"],
                "name": updated["name"],
                "destination": destination,
            })
        except Exception as exc:
            self.logger.error("drive_move error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 5 — drive_delete (CONFIDENTIAL — requires approval)
# ===========================================================================

class DriveDeleteTool(BaseTool):
    """
    Move a file to trash in Google Drive (soft delete).

    Inputs:
    - file_id (str, required): File to trash
    - file_name (str, optional): Search by name

    Outputs:
    - file_id (str), name (str), trashed (bool)
    """

    TOOL_DESCRIPTION = "Move a file to trash in Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "file_id": {"type": "string", "required": False, "default": ""},
        "file_name": {"type": "string", "required": False, "default": "", "description": "Search by name to delete"},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"file_id": {"type": "string"}, "name": {"type": "string"}, "trashed": {"type": "boolean"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "delete old notes from drive", "inputs": {"file_name": "old_notes.txt"}}]
    SEMANTIC_TAGS = ["drive", "delete", "trash", "remove"]
    TOOL_CATEGORY = "storage"

    def get_tool_name(self) -> str:
        return "drive_delete"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            service = await _svc(inputs)

            file_id = str(inputs.get("file_id", "")).strip()
            file_name = str(inputs.get("file_name", "")).strip()

            if not file_id and not file_name:
                return ToolOutput(success=False, data={}, error="file_id or file_name is required")

            if not file_id and file_name:
                q = f"name='{file_name}' and trashed=false"
                result = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=1).execute()
                files = result.get("files", [])
                if not files:
                    return ToolOutput(success=False, data={}, error=f"File '{file_name}' not found")
                file_id = files[0]["id"]
                file_name = files[0]["name"]

            if not file_name:
                meta = service.files().get(fileId=file_id, fields="name").execute()
                file_name = meta.get("name", "")

            service.files().update(fileId=file_id, body={"trashed": True}).execute()

            return ToolOutput(success=True, data={
                "file_id": file_id,
                "name": file_name,
                "trashed": True,
            })
        except Exception as exc:
            self.logger.error("drive_delete error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 6 — drive_search
# ===========================================================================

class DriveSearchTool(BaseTool):
    """
    Search for files in Google Drive by name, type, or content.

    Inputs:
    - query (str, required): What to search for
    - file_type (str, optional): Filter by type (document, spreadsheet, image, pdf, folder)
    - max_results (int, optional): Max results (default 10)

    Outputs:
    - files (list), total (int)
    """

    TOOL_DESCRIPTION = "Search for files in Google Drive"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "query": {"type": "string", "required": True, "description": "Search term"},
        "file_type": {"type": "string", "required": False, "default": "", "description": "document, spreadsheet, image, pdf, folder"},
        "max_results": {"type": "number", "required": False, "default": 10},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"files": {"type": "array"}, "total": {"type": "number"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "find my resume in drive", "inputs": {"query": "resume"}},
        {"user_utterance": "find spreadsheets in drive", "inputs": {"query": "", "file_type": "spreadsheet"}},
    ]
    SEMANTIC_TAGS = ["drive", "search", "find", "google drive"]
    TOOL_CATEGORY = "storage"

    _TYPE_MAP = {
        "document": "application/vnd.google-apps.document",
        "spreadsheet": "application/vnd.google-apps.spreadsheet",
        "presentation": "application/vnd.google-apps.presentation",
        "image": "image/",
        "pdf": "application/pdf",
        "folder": "application/vnd.google-apps.folder",
    }

    def get_tool_name(self) -> str:
        return "drive_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            service = await _svc(inputs)

            query = str(inputs.get("query", "")).strip()
            file_type = str(inputs.get("file_type", "")).strip().lower()
            max_results = int(inputs.get("max_results", 10))

            await _emit_progress(user_id, task_id, "drive_search", "searching", f"Searching Drive for '{query}'...")

            parts = ["trashed=false"]
            if query:
                parts.append(f"fullText contains '{query}'")
            if file_type and file_type in self._TYPE_MAP:
                mime = self._TYPE_MAP[file_type]
                if mime.endswith("/"):
                    parts.append(f"mimeType contains '{mime}'")
                else:
                    parts.append(f"mimeType='{mime}'")

            q = " and ".join(parts)
            result = service.files().list(
                q=q,
                spaces="drive",
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink)",
                pageSize=min(max_results, 50),
                orderBy="modifiedTime desc",
            ).execute()

            files = result.get("files", [])
            entries = []
            for f in files:
                entry: Dict[str, Any] = {
                    "id": f["id"],
                    "name": f["name"],
                    "type": "folder" if f["mimeType"] == "application/vnd.google-apps.folder" else "file",
                    "mime_type": f["mimeType"],
                    "modified": f.get("modifiedTime", ""),
                }
                if f.get("size"):
                    entry["size_bytes"] = int(f["size"])
                if f.get("webViewLink"):
                    entry["link"] = f["webViewLink"]
                entries.append(entry)

            return ToolOutput(success=True, data={"files": entries, "total": len(entries)})
        except Exception as exc:
            self.logger.error("drive_search error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))
