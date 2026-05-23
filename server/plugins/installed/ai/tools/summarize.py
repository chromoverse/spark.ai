from app.plugins.tools.tool_base import BaseTool, ToolOutput
from typing import Any, Dict
from app.ai.providers.router import routed_chat # type: ignore
from datetime import datetime, timezone
import json


def _normalize_mode(raw_mode: Any) -> str:
    mode = str(raw_mode or "tts").strip().lower()
    return mode if mode in {"tts", "research"} else "tts"


async def _emit(user_id: str, task_id: str, stage: str, message: str) -> None:
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name="ai_summarize",
            payload={"stage": stage, "message": message},
        )
    except Exception:
        pass

class AiSummarizeTool(BaseTool):
    """
    Inputs:
    - query (string, optional)
    - context (string, required)
    - mode (string, optional): "tts" (default) | "research"

    Outputs:
    - summary (string): 1-3 natural sentences for TTS.
    - formatted_content (string): detailed 5-10 sentence answer (empty in tts mode).
    - original_length (integer)
    - summary_length (integer)
    - summarized_at (string)
    """

    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = "Summarize AI-related content like logs, conversations, or documents"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "query": {"type": "string", "required": False},
        "context": {"type": "string", "required": True},
        "mode": {
            "type": "string",
            "required": False,
            "default": "tts",
            "enum": ["tts", "research"],
        },
        "max_length": {"type": "integer", "required": False, "default": 700},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "summary": {
                "type": "string",
                "description": "This must be max 2 3 sentences covering the main points of the content as this is for text to speech in humatic way.",
            },
            "formatted_content": {
                "type": "string",
                "description": "This can be upt max 10 sentences as this clears up and give information deep.",
            },
            "original_length": {"type": "integer"},
            "summary_length": {"type": "integer"},
            "summarized_at": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "ai summarize"},
    ]
    SEMANTIC_TAGS = ["ai", "ai", "summarize"]
    TOOL_CATEGORY = "ai_content"
    METADATA: Dict[str, Any] = {"summary_tts": True}

    def get_tool_name(self) -> str:
        return "ai_summarize"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        context = self.get_input(inputs, "context")
        query = self.get_input(inputs, "query", None)
        mode = _normalize_mode(self.get_input(inputs, "mode", "tts"))
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
        task_id = str(inputs.get("_task_id") or "")

        if not context:
            return ToolOutput(success=False, data={}, error="No context provided")

        is_research = mode == "research"
        await _emit(user_id, task_id, "analyzing", "Analyzing content...")
        summary_word_cap = "60" if is_research else "40"
        formatted_rule = (
            "a detailed plain-text answer of 5-10 sentences covering who, what, why, when, where, and key consequences. No markdown, no bullet points."
            if is_research
            else 'always an empty string "".'
        )
        formatted_placeholder = "<detailed 5-10 sentence plain text>" if is_research else ""
        timestamp = datetime.now(timezone.utc).isoformat()

        prompt = f"""You are a summarization engine. Return ONLY valid JSON, no markdown, no extra text.

STRICT RULES:
1. Always respond in English only — regardless of the language in the context.
2. ALWAYS extract something useful from the CONTEXT. Never say "not mentioned", "not found", or "no information". Derive the closest relevant insight from what IS in the context.
3. "summary" must be 1-3 natural spoken sentences (max {summary_word_cap} words). Directly answers the QUERY. Written to be read aloud naturally.
4. "formatted_content" must be {formatted_rule}
5. Never hallucinate facts not grounded in the context.

QUERY: {query or "Summarize the key information."}
CONTEXT:
{context}

OUTPUT (strict JSON only, no extra text):
{{"success":true,"data":{{"summary":"<natural spoken answer>","formatted_content":"{formatted_placeholder}","original_length":{len(str(context))},"summary_length":0,"summarized_at":"{timestamp}"}},"error":null}}"""

        await _emit(user_id, task_id, "summarizing", "Generating summary...")
        response_text, provider = await routed_chat(
            "summarize",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500 if is_research else 300
        )

        await _emit(user_id, task_id, "formatting", "Formatting results...")
        try:
            clean = response_text.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end != -1 and end > start:
                clean = clean[start:end + 1]

            parsed = json.loads(clean)

            data = parsed.get("data", {})
            if not isinstance(data, dict):
                data = {}

            if not is_research:
                data["formatted_content"] = ""
            else:
                formatted_content = data.get("formatted_content", "")
                data["formatted_content"] = formatted_content if isinstance(formatted_content, str) else str(formatted_content)

            parsed["data"] = data

            return ToolOutput(
                success=parsed.get("success", False),
                data=data,
                error=parsed.get("error")
            )
        except Exception as e:
            print(f"Raw LLM response: {response_text!r}")
            return ToolOutput(success=False, data={}, error=f"Invalid JSON: {str(e)}")
