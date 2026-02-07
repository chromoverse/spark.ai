"""
LLM Reasoning Router
--------------------
API endpoints for LLM chat inference.

Endpoints:
    POST /reasoning/chat - Chat with the reasoning model
"""

from typing import Union, cast, Iterator
import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import json

from app.api.v1.llm.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse
)
from app.services.inference_service import InferenceService
from app.core.config import settings


# Create router with prefix and tags
router = APIRouter(
    prefix="/reasoning",
    tags=["reasoning"],
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)


def get_service(request: Request) -> InferenceService:
    """
    Get inference service from app state.
    
    Args:
        request: FastAPI request object
        
    Returns:
        InferenceService instance
        
    Raises:
        HTTPException: If service not initialized
    """
    service: InferenceService = request.app.state.inference_service
    
    if not service or not service.is_ready:
        raise HTTPException(
            status_code=503,
            detail="Inference service not ready. Model is still loading."
        )
    
    return service


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat with the reasoning model",
    description="""
    Send a chat message to the reasoning model and receive a response.
    
    The messages list should contain the conversation history with roles:
    - **system**: System instructions (optional, first message)
    - **user**: User messages
    - **assistant**: Previous assistant responses
    
    The model will generate a response based on the full conversation context.
    """,
    responses={
        200: {"description": "Successful response from model"},
        503: {"description": "Service not ready"},
        500: {"description": "Inference error"}
    }
)
async def chat(request: Request, body: ChatRequest) -> Union[ChatResponse, StreamingResponse]:
    """
    Chat endpoint for LLM reasoning.
    
    Accepts a list of messages and returns the model's response.
    Uses cached model from app.state for optimal performance.
    """
    service = get_service(request)
    
    try:
        # Convert Pydantic models to dicts for service
        messages = [msg.model_dump() for msg in body.messages]
        
        if body.stream:
            # Get the synchronous generator from the service
            sync_generator = cast(Iterator[str], service.chat(
                messages=messages,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                stream=True,
                json_mode=body.json_mode
            ))
            
            async def event_generator():
                # Use run_in_executor to iterate over sync generator without blocking
                loop = asyncio.get_event_loop()
                
                def get_next_chunk():
                    try:
                        return next(sync_generator)
                    except StopIteration:
                        return None
                
                while True:
                    chunk = await loop.run_in_executor(None, get_next_chunk)
                    if chunk is None:
                        break
                    # Yield SSE format
                    yield f"data: {json.dumps({'response': chunk, 'model': settings.model_name})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        # Non-streaming - cast to str since stream=False returns str
        response_text = cast(str, service.chat(
            messages=messages,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            stream=False,
            json_mode=body.json_mode
        ))
        
        return ChatResponse(
            response=response_text,
            model=settings.model_name,
            usage=None
        )
        
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Inference error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )
