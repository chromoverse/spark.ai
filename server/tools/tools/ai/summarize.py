from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from app.ai.providers.manager import llm_chat # type: ignore
from datetime import datetime, timezone
import json


def _normalize_mode(raw_mode: Any) -> str:
    mode = str(raw_mode or "tts").strip().lower()
    return mode if mode in {"tts", "research"} else "tts"

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

    def get_tool_name(self) -> str:
        return "ai_summarize"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        context = self.get_input(inputs, "context")
        query = self.get_input(inputs, "query", None)
        mode = _normalize_mode(self.get_input(inputs, "mode", "tts"))

        if not context:
            return ToolOutput(success=False, data={}, error="No context provided")

        is_research = mode == "research"
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

        response_text, provider = await llm_chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500 if is_research else 300
        )

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
