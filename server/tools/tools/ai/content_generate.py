"""
content_generate — High-token LLM tool for long-form content creation.

Uses a dedicated LLM call with high max_tokens (4096) to generate
properly structured content with markdown formatting then saves to file.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..base import BaseTool, ToolOutput
from app.ai.providers.router import routed_chat  # type: ignore


_SYSTEM_PROMPT = """You are a professional content writer. Generate well-structured, detailed content based on the user's request.

FORMATTING RULES:
- Use proper Markdown formatting throughout
- Use # headings for major sections, ## for subsections
- Use **bold** for emphasis and key terms
- Use *italic* for subtle emphasis
- Use bullet points (- ) for lists
- Use numbered lists (1. ) for sequential steps
- Use > blockquotes for important notes
- Use tables (| col | col |) when presenting comparative or tabular data
- Use `code` for technical terms or commands

CONTENT RULES:
- Be thorough and detailed — fill the requested length
- Write naturally, not robotically
- Include relevant examples, explanations, and context
- Structure content logically with clear sections
- Never truncate or cut short — complete the full content
- If a specific line count is requested, meet or exceed it
"""


class ContentGenerateTool(BaseTool):
    """Generate long-form structured content via LLM with high token limit.

    Inputs:
    - topic (string, required): What to write about
    - query (string, optional): Alias for topic
    - instructions (string, optional): Additional formatting/style instructions
    - output_path (string, optional): File path to save content to
    - min_lines (integer, optional): Minimum number of lines to generate
    - format (string, optional): "markdown" (default) | "plain"

    Outputs:
    - content (string): The generated content
    - file_path (string): Path where content was saved
    - path (string): Same as file_path (for binding compatibility)
    - line_count (integer): Number of lines generated
    - char_count (integer): Character count
    """

    def get_tool_name(self) -> str:
        return "content_generate"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        topic = self.get_input(inputs, "topic", "") or self.get_input(inputs, "query", "") or self.get_input(inputs, "subject", "")
        instructions = self.get_input(inputs, "instructions", "")
        output_path = self.get_input(inputs, "output_path", "")
        min_lines = int(self.get_input(inputs, "min_lines", 0) or 0)
        fmt = str(self.get_input(inputs, "format", "markdown") or "markdown").lower()
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest")

        # Derive topic from fallbacks
        if not topic and instructions:
            topic = instructions
        if not topic and output_path:
            topic = Path(output_path).stem.replace("_", " ").replace("-", " ")
        if not topic:
            return ToolOutput(success=False, data={}, error="Topic is required")

        # Build the user prompt
        length_hint = f"\n\nIMPORTANT: Generate at least {min_lines} lines of content. Be thorough and detailed." if min_lines > 0 else ""
        format_hint = "\n\nOutput plain text without markdown formatting." if fmt == "plain" else ""
        extra = f"\n\nAdditional instructions: {instructions}" if instructions else ""
        user_msg = f"Write detailed content about: {topic}{extra}{length_hint}{format_hint}"

        max_tokens = 8192 if min_lines > 100 else 4096

        try:
            response_text, provider = await routed_chat(
                "content_generate",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=max_tokens,
            )
        except Exception as e:
            return ToolOutput(success=False, data={}, error=f"LLM generation failed: {e}")

        if not response_text or len(response_text.strip()) < 20:
            return ToolOutput(success=False, data={}, error="Generated content was too short or empty")

        content = response_text.strip()
        line_count = content.count("\n") + 1

        # Always save to file — auto-generate path if not provided
        if not output_path:
            slug = re.sub(r'[^\w\s-]', '', topic[:40]).strip().replace(' ', '_').lower()
            slug = slug or "generated_content"
            ext = ".md" if fmt == "markdown" else ".txt"
            output_path = f"{slug}{ext}"

        try:
            resolved = os.path.abspath(os.path.expanduser(output_path.strip().strip("\"'")))

            # Redirect bare filenames to artifact store
            if not os.path.isabs(output_path) and "/" not in output_path and "\\" not in output_path:
                from app.path.manager import PathManager
                artifact_dir = PathManager().get_artifact_dir("documents", user_id)
                resolved = str(artifact_dir / os.path.basename(resolved))

            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

            # Register artifact
            from app.path.artifacts import get_artifact_store
            label = Path(resolved).stem.replace("_", " ").replace("-", " ")
            get_artifact_store().register_file(
                kind="document",
                tool_name=self.get_tool_name(),
                file_path=resolved,
                user_id=user_id,
                task_id=str(inputs.get("_task_id", "")),
                label=label,
                metadata={"topic": topic, "line_count": line_count},
            )
        except Exception as e:
            return ToolOutput(
                success=True,
                data={"content": content, "line_count": line_count, "char_count": len(content), "file_path": "", "path": "", "error_saving": str(e)},
            )

        return ToolOutput(
            success=True,
            data={
                "content": content,
                "file_path": resolved,
                "path": resolved,
                "line_count": line_count,
                "char_count": len(content),
            },
        )
