from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from app.ai.providers.manager import llm_chat
import json


class AiSummarizeTool(BaseTool):
    def get_tool_name(self) -> str:
        return "ai_summarize"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        context = self.get_input(inputs, "context")
        query = self.get_input(inputs, "query", None)

        if not context:
            print("No context provided")
            return ToolOutput(success=False, data={}, error="No context provided")

        prompt = f"""You are a summarization engine. Return ONLY valid JSON, no markdown, no extra text.

STRICT RULES:
1. Always respond in English only — regardless of the language in the context.
2. ALWAYS extract something useful from the CONTEXT. Never say "not mentioned", "not found", "no information", or anything similar. If the exact answer isn't there, derive the closest relevant insight from what IS in the context.
3. The "summary" must be exactly 1 sentence (max 30 words). It must directly answer the QUERY using the context. It will be read aloud via TTS — make it natural and fluent.
4. "formatted_content" must always be an empty string "".
5. Never hallucinate facts not grounded in the context.

QUERY: {query or "Summarize the key information."}

CONTEXT:
{context}

OUTPUT (strict JSON, no extra text):
{{"success":true,"data":{{"summary":"<one natural English sentence max 30 words>","formatted_content":"","original_length":{len(str(context))},"summary_length":0,"summarized_at":"<ISO8601>"}},"error":null}}"""

        response_text, provider = await llm_chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300
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

            start = clean.find("{")
            end = clean.rfind("}")
            if start != -1 and end != -1 and end > start:
                clean = clean[start:end + 1]

            parsed = json.loads(clean)

            # Enforce formatted_content is always empty
            if "data" in parsed:
                parsed["data"]["formatted_content"] = ""

            return ToolOutput(
                success=parsed.get("success", False),
                data=parsed.get("data", {}),
                error=parsed.get("error")
            )

        except Exception as e:
            print(f"Raw LLM response: {response_text!r}")
            return ToolOutput(success=False, data={}, error=f"Invalid JSON: {str(e)}")