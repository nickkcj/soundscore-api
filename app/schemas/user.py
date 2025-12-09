from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema with common fields."""
    username: str
    email: EmailStr


class UserCreate(UserBase):
    """Schema for creating a user (internal use)."""
    password_hash: str


class UserUpdate(BaseModel):
    """Schema for updating user profile."""
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    bio: Optional[str] = Field(None, max_length=500)
    profile_picture: Optional[str] = None
    banner_image: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response (public info)."""
    id: int
    username: str
    profile_picture: Optional[str] = None
    banner_image: Optional[str] = None
    bio: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfileResponse(UserResponse):
    """Schema for user profile with stats."""
    email: EmailStr
    review_count: int = 0
    followers_count: int = 0
    following_count: int = 0
    avg_rating: Optional[float] = None
    is_following: Optional[bool] = None  # Only set when viewing another user's profile


class UserListItem(BaseModel):
    """Schema for user in lists (followers, following, search results)."""
    id: int
    username: str
    profile_picture: Optional[str] = None
    bio: Optional[str] = None
    is_following: Optional[bool] = None

    model_config = {"from_attributes": True}


class PaginatedUsersResponse(BaseModel):
    """Schema for paginated user list."""
    users: list[UserListItem]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


class FollowResponse(BaseModel):
    """Schema for follow/unfollow response."""
    success: bool
    message: str
    followers_count: int
