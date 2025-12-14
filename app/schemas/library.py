"""Library schemas for scrobbling and listening stats."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NowPlayingResponse(BaseModel):
    """Response for currently playing track."""
    track_id: str
    track_name: str
    artist_name: str
    album_name: str
    album_image_url: Optional[str]
    duration_ms: int
    progress_ms: int
    is_playing: bool


class ScrobbleResponse(BaseModel):
    """Response for a single scrobble."""
    id: int
    track_id: str
    track_name: str
    artist_name: str
    album_name: Optional[str]
    album_image_url: Optional[str]
    duration_ms: Optional[int]
    played_at: datetime

    model_config = {"from_attributes": True}


class TopArtistResponse(BaseModel):
    """Response for top artist."""
    name: str
    image: Optional[str] = None
    scrobble_count: Optional[int] = None  # Not available from Spotify API


class TopTrackResponse(BaseModel):
    """Response for top track."""
    name: str
    artist: str
    album: Optional[str]
    image: Optional[str]
    scrobble_count: int


class TopAlbumResponse(BaseModel):
    """Response for top album."""
    name: str
    artist: str
    image: Optional[str]
    scrobble_count: int


class ScrobblesByDayResponse(BaseModel):
    """Response for scrobbles by day."""
    date: str
    count: int


class TopArtistStats(BaseModel):
    """Top artist with count."""
    name: str
    count: int


class TopTrackStats(BaseModel):
    """Top track with count."""
    name: str
    artist: str
    image: Optional[str]
    count: int


class LibraryStatsResponse(BaseModel):
    """Response for library statistics."""
    total_scrobbles: int
    unique_artists_count: int
    top_artist: Optional[TopArtistStats]
    top_track: Optional[TopTrackStats]
    scrobbles_by_day: list[ScrobblesByDayResponse]


class SyncResponse(BaseModel):
    """Response for sync operation."""
    synced_count: int
    message: str


class SpotifyConnectionStatus(BaseModel):
    """Status of Spotify connection for a user."""
    connected: bool
    username: Optional[str] = None
