from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ============== Group Schemas ==============

class GroupCreate(BaseModel):
    """Schema for creating a group."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    privacy: str = Field(default="public", pattern="^(public|private)$")
    category: Optional[str] = Field(None, max_length=50)


class GroupUpdate(BaseModel):
    """Schema for updating a group."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    privacy: Optional[str] = Field(None, pattern="^(public|private)$")
    category: Optional[str] = Field(None, max_length=50)
    cover_image: Optional[str] = None


class GroupResponse(BaseModel):
    """Schema for group response."""
    id: int
    uuid: UUID
    name: str
    description: Optional[str]
    privacy: str
    category: Optional[str]
    cover_image: Optional[str]
    created_at: datetime
    created_by_id: int

    # Stats
    member_count: int = 0
    is_member: Optional[bool] = None

    model_config = {"from_attributes": True}


class GroupListResponse(BaseModel):
    """Schema for paginated group list."""
    groups: list[GroupResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


# ============== Group Member Schemas ==============

class GroupMemberResponse(BaseModel):
    """Schema for group member response."""
    user_id: int
    username: str
    profile_picture: Optional[str]
    role: str
    joined_at: datetime
    is_online: bool = False

    model_config = {"from_attributes": True}


class GroupMemberListResponse(BaseModel):
    """Schema for group member list."""
    members: list[GroupMemberResponse]
    total: int


# ============== Group Message Schemas ==============

class GroupMessageCreate(BaseModel):
    """Schema for creating a group message."""
    content: str = Field(..., min_length=1, max_length=5000)


class GroupMessageResponse(BaseModel):
    """Schema for group message response."""
    id: int
    content: str
    image_url: Optional[str] = None
    created_at: datetime

    # User info
    user_id: int
    username: str
    profile_picture: Optional[str]

    model_config = {"from_attributes": True}


class GroupMessageListResponse(BaseModel):
    """Schema for paginated message list."""
    messages: list[GroupMessageResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


# ============== Group Detail Schema ==============

class GroupDetailResponse(BaseModel):
    """Schema for detailed group response with members and recent messages."""
    group: GroupResponse
    members: list[GroupMemberResponse]
    recent_messages: list[GroupMessageResponse]
    is_member: bool
    user_role: Optional[str] = None


# ============== WebSocket Message Schemas ==============

class WSMessageIn(BaseModel):
    """Schema for incoming WebSocket messages."""
    type: str = "message"  # "message", "typing", "ping"
    content: Optional[str] = None
    image_url: Optional[str] = None


class WSMessageOut(BaseModel):
    """Schema for outgoing WebSocket messages."""
    type: str  # "message", "user_joined", "user_left", "online_users", "typing", "pong"
    content: Optional[str] = None
    image_url: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    profile_picture: Optional[str] = None
    message_id: Optional[int] = None
    timestamp: Optional[str] = None
    online_users: Optional[list[dict]] = None


# ============== Group Invite Schemas ==============

class GroupInviteCreate(BaseModel):
    """Schema for creating a group invite."""
    invitee_username: str = Field(..., min_length=1, max_length=50)


class GroupInviteResponse(BaseModel):
    """Schema for group invite response."""
    id: int
    uuid: UUID
    group_id: int
    group_name: str
    group_uuid: UUID
    group_cover_image: Optional[str]
    invitee_id: int
    invitee_username: str
    inviter_id: int
    inviter_username: str
    inviter_profile_picture: Optional[str]
    status: str
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


class GroupInviteListResponse(BaseModel):
    """Schema for paginated invite list."""
    invites: list[GroupInviteResponse]
    total: int


class InviteActionResponse(BaseModel):
    """Response for accept/decline invite."""
    success: bool
    message: str
    group_uuid: Optional[UUID] = None
