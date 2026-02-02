from datetime import time
import json
import re
import logging
from typing import Optional
from pydantic import BaseModel, ValidationError
from json_repair import repair_json
from app.models.pqh_response_model import PQHResponse, CognitiveState

logger = logging.getLogger(__name__)



# ==================== ZERO-LATENCY CLEANER ====================
def clean_pqh_response(raw_data: str, emotion: str = "neutral") -> PQHResponse:
    """
    Ultra-fast PQH response cleaner with zero-latency focus.
    
    Validation hierarchy (fastest to slowest):
    1. Direct parse (0ms overhead)
    2. Strip markdown (1-2ms)
    3. JSON repair (5-10ms)
    4. Field-by-field reconstruction (last resort)
    """
    
    # Fast path: Try direct parse first (most common case)
    try:
        data = json.loads(raw_data)
        return PQHResponse(**data)
    except (json.JSONDecodeError, ValidationError):
        pass
    
    # Path 2: Strip markdown wrappers
    try:
        cleaned = raw_data.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned).rstrip("`").strip()
        
        data = json.loads(cleaned)
        return PQHResponse(**data)
    except (json.JSONDecodeError, ValidationError):
        pass
    
    # Path 3: JSON repair (slower but robust)
    try:
        repaired = repair_json(raw_data.strip())
        data = json.loads(repaired)
        
        # Handle double-encoded JSON
        if isinstance(data, str):
            data = json.loads(data)
        
        return PQHResponse(**data)
    except (json.JSONDecodeError, ValidationError, Exception):
        pass
    
    # Path 4: Manual reconstruction (last resort)
    logger.warning("Fast paths failed, attempting manual reconstruction")
    return _reconstruct_pqh_response(raw_data, emotion)


def _reconstruct_pqh_response(raw_data: str, emotion: str) -> PQHResponse:
    """
    Manually reconstruct PQHResponse when all fast paths fail.
    Extracts fields using regex patterns.
    """
    
    try:
        # Try one more time with aggressive cleaning
        cleaned = raw_data.strip()
        
        # Remove markdown
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned).rstrip("`").strip()
        
        # Fix common JSON errors
        cleaned = cleaned.replace("'", '"')  # Single to double quotes
        cleaned = re.sub(r',\s*}', '}', cleaned)  # Trailing commas
        cleaned = re.sub(r',\s*]', ']', cleaned)  # Trailing commas in arrays
        
        data = json.loads(cleaned)
        
        # Extract fields with fallbacks
        request_id = data.get("request_id", f"error_{int(time.time()*1000)}") # type: ignore
        
        # Extract cognitive_state
        cog_state = data.get("cognitive_state", {})
        cognitive_state = CognitiveState(
            user_query=cog_state.get("user_query", "[Parse Error]"),
            emotion=cog_state.get("emotion", emotion),
            thought_process=cog_state.get("thought_process", "Response parsing failed"),
            answer=cog_state.get("answer", raw_data[:200] if raw_data else "Unable to process response."),
            answer_english=cog_state.get("answer_english", "Unable to process response.")
        )
        
        # Extract requested_tool
        requested_tool = data.get("requested_tool", [])
        if not isinstance(requested_tool, list):
            requested_tool = [requested_tool] if requested_tool else []
        
        return PQHResponse(
            request_id=request_id,
            cognitive_state=cognitive_state,
            requested_tool=requested_tool
        )
    
    except Exception as e:
        logger.error(f"Manual reconstruction failed: {e}", exc_info=True)
        return _create_error_pqh_response(raw_data, emotion)


def _create_error_pqh_response(raw_data: str, emotion: str) -> PQHResponse:
    """Create safe fallback PQHResponse when all parsing fails."""
    
    import time
    
    return PQHResponse(
        request_id=f"error_{int(time.time()*1000)}",
        cognitive_state=CognitiveState(
            user_query="[Parse Error]",
            emotion=emotion,
            thought_process="Failed to parse AI response. All validation paths exhausted.",
            answer=raw_data[:200] if raw_data else "Response processing failed.",
            answer_english="Unable to process response. Please try again."
        ),
        requested_tool=[]
    )


# ==================== QUICK VALIDATOR ====================
def is_valid_pqh_format(raw_data: str) -> bool:
    """
    Ultra-fast format checker (< 1ms for valid responses).
    Returns True if response matches PQH format.
    """
    
    try:
        # Quick string checks (fastest)
        if not raw_data or len(raw_data) < 50:
            return False
        
        if "request_id" not in raw_data or "cognitive_state" not in raw_data:
            return False
        
        # Try direct parse (still fast)
        data = json.loads(raw_data.strip())
        
        # Check required top-level keys
        if not all(k in data for k in ["request_id", "cognitive_state"]):
            return False
        
        # Check cognitive_state structure
        cog_state = data.get("cognitive_state", {})
        required_cog_keys = ["user_query", "emotion", "thought_process", "answer", "answer_english"]
        
        if not all(k in cog_state for k in required_cog_keys):
            return False
        
        return True
    
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False
