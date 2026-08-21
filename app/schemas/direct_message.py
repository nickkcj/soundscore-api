"""Direct message schemas for API responses."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SendMessageRequest(BaseModel):
    """Schema for sending a direct message with text and/or an uploaded image."""
    content: str = Field("", max_length=5000)
    image_path: Optional[str] = Field(None, max_length=500)
    # Backwards-compatible field used by the existing web client.
    image_url: Optional[str] = Field(None, max_length=500)
    client_id: Optional[str] = Field(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class ShareReviewRequest(BaseModel):
    """Schema for sharing a review via DM or group."""
    recipient_username: Optional[str] = None
    group_uuid: Optional[str] = None


class OtherUser(BaseModel):
    """Brief user info for conversation list."""
    id: int
    username: str
    profile_picture: Optional[str] = None


class DirectMessageResponse(BaseModel):
    """Schema for a single direct message."""
    id: int
    conversation_id: int
    sender_id: int
    sender_username: str
    sender_profile_picture: Optional[str] = None
    content: str
    image_url: Optional[str] = None
    client_id: Optional[str] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    """Schema for a conversation in the list."""
    id: int
    other_user: OtherUser
    last_message: Optional[DirectMessageResponse] = None
    unread_count: int = 0
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Schema for paginated conversation list."""
    conversations: list[ConversationResponse]
    total: int


class MessageListResponse(BaseModel):
    """Schema for paginated message list."""
    messages: list[DirectMessageResponse]
    total: int
    page: int
    per_page: int
    has_more: bool
