from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from . import CamelModel
import time


class CognitiveState(CamelModel):
    user_query: str
    emotion: str = "neutral"
    thought_process: str = ""
    answer: str
    answer_english: str
 
class PQHResponse(CamelModel):
    request_id: str = Field(default_factory=lambda: f"pqh_{int(time.time()*1000)}")
    cognitive_state: CognitiveState
    category: Optional[List[str]] = None
    needs_clarification: bool = False

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [c for c in v if isinstance(c, str)] or None
        return None