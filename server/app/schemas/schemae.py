from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class RequestTTS(BaseModel):
  text: str