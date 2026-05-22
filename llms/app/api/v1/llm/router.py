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
    responses={
        200: {"description": "Successful response from model"},
        503: {"description": "Service not ready"},
        500: {"description": "Inference error"}
    }
)
async def chat(request: Request, body: ChatRequest) -> Union[ChatResponse, StreamingResponse]:
    """Chat endpoint — streams SSE or returns JSON."""
    service = get_service(request)

    try:
        messages = [msg.model_dump() for msg in body.messages]

        if body.stream:
            sync_generator = cast(Iterator[str], service.chat(
                messages=messages,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                stream=True,
                json_mode=body.json_mode
            ))

            async def event_generator():
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
                    yield f"data: {json.dumps({'response': chunk, 'model': settings.model_name})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

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
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/cancel", summary="Cancel in-flight generation")
async def cancel_generation(request: Request):
    """Cancel current generation — critical for voice interruption support."""
    service = get_service(request)
    cancelled = service.cancel_generation()
    return {"cancelled": cancelled}
