from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============== Album Schemas ==============

class AlbumBase(BaseModel):
    """Base album schema."""
    spotify_id: str
    title: str
    artist: str
    cover_image: Optional[str] = None
    release_date: Optional[str] = None


class AlbumResponse(AlbumBase):
    """Album response schema."""
    id: int

    model_config = {"from_attributes": True}


class SpotifyAlbumResult(BaseModel):
    """Spotify album search result."""
    spotify_id: str
    title: str
    artist: str
    cover_image: Optional[str] = None
    release_date: Optional[str] = None


# ============== Review Schemas ==============

class ReviewCreate(BaseModel):
    """Schema for creating a review."""
    spotify_id: str
    title: str
    artist: str
    cover_image: Optional[str] = None
    release_date: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    text: Optional[str] = Field(None, max_length=5000)
    is_favorite: bool = False


class ReviewUpdate(BaseModel):
    """Schema for updating a review."""
    rating: Optional[int] = Field(None, ge=1, le=5)
    text: Optional[str] = Field(None, max_length=5000)
    is_favorite: Optional[bool] = None


class ReviewResponse(BaseModel):
    """Schema for review response."""
    id: int
    rating: int
    text: Optional[str]
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    # Album info
    album: AlbumResponse

    # User info
    user_id: int
    username: str
    user_profile_picture: Optional[str] = None

    # Engagement stats
    like_count: int = 0
    comment_count: int = 0
    is_liked: Optional[bool] = None  # Whether current user liked this

    model_config = {"from_attributes": True}


class ReviewListResponse(BaseModel):
    """Schema for paginated review list."""
    reviews: list[ReviewResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


# ============== Comment Schemas ==============

class CommentCreate(BaseModel):
    """Schema for creating a comment."""
    text: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = None


class CommentResponse(BaseModel):
    """Schema for comment response."""
    id: int
    text: str
    created_at: datetime

    # User info
    user_id: int
    username: str
    user_profile_picture: Optional[str] = None

    # Parent info
    parent_id: Optional[int] = None

    # Like info
    like_count: int = 0
    is_liked: Optional[bool] = None

    # Nested replies (only first level)
    replies: list["CommentResponse"] = []

    model_config = {"from_attributes": True}


class CommentListResponse(BaseModel):
    """Schema for paginated comment list."""
    comments: list[CommentResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


# ============== Like Schemas ==============

class LikeResponse(BaseModel):
    """Schema for like toggle response."""
    liked: bool
    like_count: int


# ============== Discover Schemas ==============

class AlbumWithRating(SpotifyAlbumResult):
    """Album search result with rating info from our database."""
    avg_rating: Optional[float] = None
    review_count: int = 0


# ============== Album Detail Schemas ==============

class TrackItem(BaseModel):
    """Track item in album tracklist."""
    track_number: int
    name: str
    duration_ms: int
    explicit: bool
    spotify_url: str
    artists: str


class AlbumDetailResponse(BaseModel):
    """Complete album details from Spotify + SoundScore stats."""
    spotify_id: str
    title: str
    artist: str
    cover_image: Optional[str] = None
    release_date: Optional[str] = None
    label: Optional[str] = None
    copyrights: list[str] = []
    total_tracks: int
    popularity: int
    spotify_url: str
    tracks: list[TrackItem]
    summary: Optional[str] = None  # AI-generated summary
    avg_rating: Optional[float] = None
    review_count: int = 0
