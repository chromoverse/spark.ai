from datetime import datetime
from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from app.ai.providers.manager import llm_chat


class AiSummarizeTool(BaseTool):

    def get_tool_name(self) -> str:
        return "ai_summarize"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        content = self.get_input(inputs, "content")
        query = self.get_input(inputs, "query", None)
        max_length = self.get_input(inputs, "max_length", 700)

        system_prompt = """You are an AI summarization engine used inside a production tool called "ai_summarize".

        Your job is to analyze the provided content and generate a structured JSON response.

        STRICT RULES:

        1. You MUST return ONLY valid JSON.
        2. You MUST follow the exact output schema structure.
        3. Do NOT add explanations, markdown, or extra text.
        4. If an error occurs, return success=false and populate the error field.
        5. The summary must:
          - Be maximum 2–3 sentences
          - Be natural, human-like, and conversational (for text-to-speech)
          - Cover the most important points relevant to the query
        6. The formatted_content:
          - Can be up to 10 sentences
          - Should clarify and expand the main ideas cleanly
          - Remove noise, logs, repeated lines, irrelevant data
        7. If a query is provided:
          - Focus ONLY on content relevant to the query
          - Ignore unrelated sections
        8. If no query is provided:
          - Summarize the overall important information

        OUTPUT FORMAT (MUST MATCH EXACTLY):

        {
          "success": boolean,
          "data": {
            "summary": string,
            "formatted_content": string,
            "original_length": integer,
            "summary_length": integer,
            "summarized_at": string
          },
          "error": string | null
        }

        The summarized_at field must be ISO 8601 format.
        The summary_length must equal the length of the summary string in characters.
        The original_length must equal the length of the original content in characters.

        DO NOT include any fields outside this structure.
        """

        user_prompt = f"""
        QUERY:
        {query if query else "null"}

        MAX_LENGTH:
        {max_length}

        CONTENT:
        {content}
        """

        response_text, provider = await llm_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )

        try:
            import json
            parsed = json.loads(response_text)

            return ToolOutput(
                success=parsed.get("success", False),
                data=parsed.get("data", {}),
                error=parsed.get("error")
            )

        except Exception as e:
            return ToolOutput(
                success=False,
                data={},
                error=f"Invalid JSON returned from LLM: {str(e)}"
            )
