from pydantic import BaseModel, Field
from typing import Optional
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
    category: Optional[str] = None
    needs_clarification: bool = False