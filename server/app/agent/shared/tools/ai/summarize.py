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

        TASK:
        1. ALWAYS extract relevant information from the CONTEXT first.
        2. ONLY use your own knowledge to enrich or clarify — never to replace what's in the CONTEXT.
        3. If the CONTEXT clearly contains the answer, use it. Do NOT say "no information available" if the CONTEXT has it.
        - summary: 2-3 short natural sentences (for TTS).
        - formatted_content: up to 10 clean sentences expanding on the summary.

        QUERY: {query or "Summarize the key information."}

        CONTEXT:
        {context}

        OUTPUT (strict):
        {{"success":true,"data":{{"summary":"...","formatted_content":"...","original_length":{len(str(context))},"summary_length":0,"summarized_at":"<ISO8601>"}},"error":null}}"""
    
        response_text, provider = await llm_chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1000
        )

        try:
            # 1. Naive cleanup
            clean = response_text.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            # 2. Robust extraction (find first { and last })
            start = clean.find("{")
            end = clean.rfind("}")
            
            if start != -1 and end != -1 and end > start:
                 clean = clean[start : end + 1]

            parsed = json.loads(clean)
            return ToolOutput(
                success=parsed.get("success", False),
                data=parsed.get("data", {}),
                error=parsed.get("error")
            )
        except Exception as e:
            print(f"Raw LLM response: {response_text!r}")
            return ToolOutput(success=False, data={}, error=f"Invalid JSON: {str(e)}")