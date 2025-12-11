from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel

from app.schemas.review import ReviewResponse


# ============== Notification Schemas ==============

class NotificationResponse(BaseModel):
    """Schema for notification response."""
    id: int
    notification_type: str  # "like", "comment", "follow", "review"
    message: str
    is_read: bool
    created_at: datetime

    # Actor info (who triggered the notification)
    actor_id: int
    actor_username: str
    actor_profile_picture: Optional[str] = None

    # Related content (optional)
    review_id: Optional[int] = None
    review_uuid: Optional[UUID] = None
    comment_id: Optional[int] = None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Schema for paginated notification list."""
    notifications: list[NotificationResponse]
    unread_count: int
    total: int
    page: int
    per_page: int
    has_next: bool


class UnreadCountResponse(BaseModel):
    """Schema for unread notification count."""
    unread_count: int


class MarkReadResponse(BaseModel):
    """Schema for mark as read response."""
    success: bool
    message: str


# ============== Feed Schemas ==============

class FeedResponse(BaseModel):
    """Schema for social feed response."""
    reviews: list[ReviewResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


# ============== SSE Event Schemas ==============

class SSENotificationEvent(BaseModel):
    """Schema for SSE notification event."""
    event: str = "notification"
    data: NotificationResponse
