import json
import re
import logging
from typing import Any
from json_repair import repair_json
from app.schemas.chat_schema import (
    ActionDetails, ChatResponse, Confirmation, AnswerDetails
)

logger = logging.getLogger(__name__)

def clean_ai_response(raw_data: str) -> ChatResponse:
    """Parse AI response with Hindi/English fields and robust error handling."""
    
    try:
        # Strip markdown wrappers
        raw_data = raw_data.strip()
        if raw_data.startswith("```"):
            raw_data = re.sub(r"^```[a-zA-Z]*\n?", "", raw_data).rstrip("`").strip()
        
        # Repair malformed JSON
        try:
            raw_data = repair_json(raw_data)
        except Exception as e:
            logger.warning(f"JSON repair skipped: {e}")
        
        # Parse JSON
        data: Any = json.loads(raw_data)
        
        # Handle double-encoded JSON
        if isinstance(data, str):
            logger.warning("Double-encoded JSON detected, re-parsing...")
            data = json.loads(data)
        
        # Unwrap nested JSON in 'answer' field
        if "answer" in data and isinstance(data["answer"], str):
            try:
                nested = json.loads(repair_json(data["answer"]))
                if isinstance(nested, dict) and "actionDetails" in nested:
                    logger.warning("Unwrapping nested JSON from 'answer'")
                    data = nested
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Extract required fields
        user_query = data.get("user_query", "").strip()
        answer = data.get("answer", "").strip().replace("\\n", "\n")
        answer_english = data.get("answer_english", "").strip().replace("\\n", "\n")
        action_msg = data.get("actionCompletedMessage", "").strip()
        action_msg_en = data.get("actionCompletedMessageEnglish", "").strip()
        action = data.get("action", "").strip()
        emotion = data.get("emotion", "neutral").strip()
        
        # Parse answerDetails
        answer_details_data = data.get("answerDetails", {})
        answer_details = AnswerDetails(
            content=answer_details_data.get("content", ""),
            sources=answer_details_data.get("sources", []),
            references=answer_details_data.get("references", []),
            additional_info=answer_details_data.get("additional_info", {})
        )
        
        # Parse actionDetails
        action_details_data = data.get("actionDetails", {})
        action_details = _parse_action_details(action_details_data)
        
        # Build validated response
        cleaned = ChatResponse(
            user_query=user_query,
            answer=answer,
            answer_english=answer_english,
            actionCompletedMessage=action_msg,
            actionCompletedMessageEnglish=action_msg_en,
            action=action,
            emotion=emotion,
            answerDetails=answer_details,
            actionDetails=action_details
        )
        
        logger.info(f"Cleaned response: query={user_query[:30]}, action={action}, confirmed={action_details.confirmation.isConfirmed}")
        return cleaned
    
    except (json.JSONDecodeError, AttributeError, TypeError, KeyError) as e:
        logger.error(f"Parse failed: {e}", exc_info=True)
        logger.debug(f"Raw data: {raw_data[:500]}...")
        return _create_fallback_response(raw_data)

def _parse_action_details(data: dict) -> ActionDetails:
    """Parse actionDetails with confirmation logic."""
    confirmation_data = data.get("confirmation", {})
    confirmation = Confirmation(
        isConfirmed=confirmation_data.get("isConfirmed", False),
        actionRegardingQuestion=confirmation_data.get("actionRegardingQuestion", "")
    )
    
    return ActionDetails(
        type=data.get("type", ""),
        query=data.get("query", ""),
        title=data.get("title", ""),
        artist=data.get("artist", ""),
        topic=data.get("topic", ""),
        platforms=data.get("platforms", []),
        app_name=data.get("app_name", ""),
        target=data.get("target", ""),
        location=data.get("location", ""),
        searchResults=data.get("searchResults", []),
        confirmation=confirmation,
        additional_info=data.get("additional_info", {})
    )

def _create_fallback_response(raw_data: str) -> ChatResponse:
    """Create safe fallback when parsing fails."""
    return ChatResponse(
        user_query="[Parse Error]",
        answer=raw_data.strip()[:200] if raw_data else "Response processing failed.",
        answer_english="Unable to process response.",
        actionCompletedMessage="",
        actionCompletedMessageEnglish="",
        action="",
        emotion="neutral",
        answerDetails=AnswerDetails(
            content="", sources=[], references=[], additional_info={}
        ),
        actionDetails=ActionDetails(
            type="", query="", title="", artist="", topic="",
            platforms=[], app_name="", target="", location="",
            searchResults=[],
            confirmation=Confirmation(isConfirmed=False, actionRegardingQuestion=""),
            additional_info={}
        )
    )