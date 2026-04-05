"""Artifact kind configuration.

Maps tool names to their artifact storage kind. Only tools that produce data
the user may later retrieve are listed here. Ephemeral tools (app_open,
battery_status, etc.) intentionally omit artifact storage.

This module is currently descriptive policy only. In this pass, artifacts are
persisted only by tools that explicitly call `ArtifactStore.register_file()`
or similar storage helpers themselves. The execution engine does not yet apply
this mapping automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ArtifactKindConfig:
    """Describes how a tool's output should be stored as an artifact."""

    kind: str                    # artifact subdirectory name (e.g. "documents")
    persist_file: bool = True    # whether the tool produces a file to persist
    persist_data: bool = False   # whether to persist the output data dict as JSON
    label_field: str = ""        # metadata/input field to use as human-readable label


# ─── Tool → Artifact Kind Mapping ────────────────────────────────────────────
#
# Tools listed here are expected to persist retrievable output eventually.
# Today, only tools with explicit artifact registration in their implementation
# actually write records into `ArtifactStore`.
#
# DOES store artifacts (user may ask for these later):
#   - file_create    → documents (created text files, plans, notes)
#   - screenshot     → screenshots (screen captures)
#   - web_research   → research (search results, summaries)
#   - ai_summarize   → summaries (text summaries)
#   - file_read      → documents (read file content, for context)
#   - shell_agent    → shell_output (command run results)
#   - folder_organize → scripts (restore.bat, organization records)
#
# Does NOT store artifacts (ephemeral / action-only tools):
#   - app_open, app_close, app_restart, app_minimize, app_maximize, app_focus
#   - battery_status, network_status, system_info
#   - brightness_*, sound_*, mic_*
#   - clipboard_read, clipboard_write
#   - notification_push, lock_screen, current_location
#   - weather_current, weather_forecast
#   - music_*, message_*, call_*
#   - email_* (operates on Gmail, not local files)
#   - agent_status, tool_catalog
#   - file_search, file_open, file_delete, file_move, file_copy, folder_create
#   - folder_cleanup (alias of folder_organize, inherits behavior)

TOOL_ARTIFACT_MAP: Dict[str, ArtifactKindConfig] = {
    "file_create": ArtifactKindConfig(
        kind="documents",
        persist_file=True,
        label_field="path",
    ),
    "screenshot_capture": ArtifactKindConfig(
        kind="screenshots",
        persist_file=True,
        label_field="target",
    ),
    "web_research": ArtifactKindConfig(
        kind="research",
        persist_file=False,
        persist_data=True,
        label_field="query",
    ),
    "ai_summarize": ArtifactKindConfig(
        kind="summaries",
        persist_file=False,
        persist_data=True,
        label_field="query",
    ),
    "shell_agent": ArtifactKindConfig(
        kind="shell_output",
        persist_file=False,
        persist_data=True,
        label_field="goal",
    ),
    "folder_organize": ArtifactKindConfig(
        kind="scripts",
        persist_file=True,
        label_field="path",
    ),
}


def get_artifact_kind_for_tool(tool_name: str) -> Optional[ArtifactKindConfig]:
    """Return descriptive artifact policy for a tool, or None if it is ephemeral."""
    return TOOL_ARTIFACT_MAP.get(tool_name)


def should_persist_artifact(tool_name: str) -> bool:
    """Check whether a tool is classified as artifact-producing in policy."""
    return tool_name in TOOL_ARTIFACT_MAP


__all__ = [
    "ArtifactKindConfig",
    "TOOL_ARTIFACT_MAP",
    "get_artifact_kind_for_tool",
    "should_persist_artifact",
]
