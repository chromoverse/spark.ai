from fastapi import APIRouter
from app.schemas import ChatRequest, ChatResponse
from app.services.chat.chat_service import chat
import logging
logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
  chatRes = await chat(
    request.text, 
    request.user_id,
    wait_for_execution=True,    # ✅ Wait for tasks to complete
    execution_timeout=30.0       # ✅ Max 30 seconds
  )
  if(chatRes):
    return chatRes
