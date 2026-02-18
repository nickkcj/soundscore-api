"""Artist schemas for API responses."""

from pydantic import BaseModel
from typing import Optional


class ArtistAlbumItem(BaseModel):
    """An album by the artist with SoundScore stats."""
    spotify_id: str
    title: str
    cover_image: Optional[str] = None
    release_date: Optional[str] = None
    avg_rating: Optional[float] = None
    review_count: int = 0


class ArtistDetailResponse(BaseModel):
    """Complete artist details response."""
    spotify_id: str
    name: str
    image_url: Optional[str] = None
    genres: list[str] = []
    popularity: int = 0
    followers: int = 0
    spotify_url: str = ""
    summary: Optional[str] = None
    albums: list[ArtistAlbumItem] = []
