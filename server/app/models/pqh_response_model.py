from pydantic import BaseModel
from typing import Optional, List
from . import CamelModel


class CognitiveState(CamelModel):
    user_query: str
    emotion: str
    thought_process: str
    answer: str
    answer_english: str
 
class PQHResponse(CamelModel):
    request_id: str
    cognitive_state: CognitiveState 
    requested_tool: Optional[List[str]] = []