"""Pydantic schemas for chatbot."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ChatMessageCreate(BaseModel):
    """Schema for sending a chat message."""
    message: str = Field(..., min_length=1, max_length=2000)


class ChatMessageResponse(BaseModel):
    """Schema for a chat message response."""
    id: int
    message: str
    response: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    """Schema for chatbot response."""
    response: str


class ChatHistoryResponse(BaseModel):
    """Schema for chat history."""
    messages: list[ChatMessageResponse]
    total: int


class ChatClearResponse(BaseModel):
    """Schema for clearing chat history."""
    message: str
    deleted_count: int
