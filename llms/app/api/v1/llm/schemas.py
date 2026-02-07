"""
API Schemas for LLM Reasoning Endpoints
---------------------------------------
Pydantic models for request/response validation.
"""

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class Message(BaseModel):
    """
    A single message in a chat conversation.
    
    Attributes:
        role: The speaker role (system/user/assistant)
        content: The message text content
    """
    role: Literal["system", "user", "assistant"] = Field(
        description="Role of the message sender"
    )
    content: str = Field(
        description="Text content of the message"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What is 2 + 2?"
            }
        }


class ChatRequest(BaseModel):
    """
    Request body for chat endpoint.
    
    Attributes:
        messages: List of conversation messages
        max_tokens: Maximum tokens to generate (default: 512)
        temperature: Sampling temperature 0-2 (default: 0.1 for JSON)
        stream: Whether to stream the response
        json_mode: If True, enforces valid JSON output using grammar
    """
    messages: List[Message] = Field(
        description="Conversation history as list of messages"
    )
    max_tokens: int = Field(
        default=512,
        ge=1,
        le=32768,
        description="Maximum number of tokens to generate (supports up to 32K)"
    )
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (use 0.1-0.3 for JSON, higher for creative)"
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response"
    )
    json_mode: bool = Field(
        default=False,
        description="If True, enforces valid JSON output using grammar constraints"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "messages": [
                    {"role": "system", "content": "You are SPARK. Respond ONLY with valid JSON."},
                    {"role": "user", "content": "hey there"}
                ],
                "max_tokens": 256,
                "temperature": 0.1,
                "json_mode": True
            }
        }


class ChatResponse(BaseModel):
    """
    Response body for chat endpoint.
    
    Attributes:
        response: Generated text from the model
        model: Model identifier used
        usage: Token usage statistics (if available)
    """
    response: str = Field(
        description="Generated response text from the model"
    )
    model: str = Field(
        description="Model identifier that generated the response"
    )
    usage: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Token usage statistics"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "response": "A decorator is a function that wraps another function...",
                "model": "qwen2.5-7b",
                "usage": {
                    "prompt_tokens": 24,
                    "completion_tokens": 128
                }
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(description="Service health status")
    model_ready: bool = Field(description="Whether the model is loaded")
    device: Optional[str] = Field(
        default=None,
        description="Device type (cpu/gpu)"
    )


class ErrorResponse(BaseModel):
    """Error response body."""
    error: str = Field(description="Error message")
    detail: Optional[str] = Field(
        default=None,
        description="Detailed error information"
    )
