from pydantic import BaseModel
from datetime import datetime

class ChatModel(BaseModel):
    user_id: str
    message: str
    created_at: datetime = datetime.utcnow()
