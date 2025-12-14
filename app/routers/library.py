"""Library router for scrobbling and listening stats."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.dependencies import DbSession, CurrentUser
from app.services.spotify_scrobble_service import SpotifyScrobbleService
from app.schemas.library import (
    NowPlayingResponse,
    ScrobbleResponse,
    LibraryStatsResponse,
    TopArtistResponse,
    TopTrackResponse,
    SyncResponse,
    SpotifyConnectionStatus,
)
from app.core.exceptions import NotFoundException, BadRequestException

router = APIRouter()


async def get_user_by_username(db: AsyncSession, username: str) -> User:
    """Get user by username or raise 404."""
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User not found")
    return user


# ============= Now Playing (Public) =============

@router.get(
    "/now-playing/{username}",
    response_model=NowPlayingResponse | None,
    summary="Get currently playing track for a user",
)
async def get_now_playing(username: str, db: DbSession):
    """
    Get the currently playing track for a user.
    Returns null if nothing is playing or user doesn't have Spotify connected.
    This is a public endpoint.
    """
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    oauth = await service.get_spotify_oauth(user.id)

    if not oauth:
        return None

    return await service.get_currently_playing(oauth)


# ============= Spotify Connection Status =============

@router.get(
    "/spotify-status/{username}",
    response_model=SpotifyConnectionStatus,
    summary="Check if user has Spotify connected",
)
async def get_spotify_status(username: str, db: DbSession):
    """Check if a user has their Spotify account connected."""
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    oauth = await service.get_spotify_oauth(user.id)

    return SpotifyConnectionStatus(
        connected=oauth is not None,
        username=oauth.provider_email if oauth else None,
    )


# ============= Scrobbles =============

@router.get(
    "/scrobbles/{username}",
    response_model=list[ScrobbleResponse],
    summary="Get scrobbles for a user",
)
async def get_scrobbles(
    username: str,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Get the listening history (scrobbles) for a user."""
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    scrobbles = await service.get_scrobbles(user.id, limit=limit, offset=offset)
    return scrobbles


# ============= Stats =============

@router.get(
    "/stats/{username}",
    response_model=LibraryStatsResponse,
    summary="Get listening statistics for a user",
)
async def get_stats(
    username: str,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
):
    """Get listening statistics for a user."""
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    stats = await service.get_stats(user.id, days=days)
    return stats


# ============= Top Artists =============

@router.get(
    "/top/artists/{username}",
    response_model=list[TopArtistResponse],
    summary="Get top artists for a user",
)
async def get_top_artists(
    username: str,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Get top artists for a user based on scrobble count."""
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    artists = await service.get_top_artists(user.id, days=days, limit=limit)
    return artists


# ============= Top Tracks =============

@router.get(
    "/top/tracks/{username}",
    response_model=list[TopTrackResponse],
    summary="Get top tracks for a user",
)
async def get_top_tracks(
    username: str,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Get top tracks for a user based on scrobble count."""
    user = await get_user_by_username(db, username)
    service = SpotifyScrobbleService(db)
    tracks = await service.get_top_tracks(user.id, days=days, limit=limit)
    return tracks


# ============= Sync (Authenticated) =============

@router.post(
    "/sync",
    response_model=SyncResponse,
    summary="Sync scrobbles from Spotify",
)
async def sync_scrobbles(current_user: CurrentUser, db: DbSession):
    """
    Sync recently played tracks from Spotify to the local database.
    Requires authentication and a connected Spotify account.
    """
    service = SpotifyScrobbleService(db)
    oauth = await service.get_spotify_oauth(current_user.id)

    if not oauth:
        raise BadRequestException(
            "Spotify account not connected. Please connect your Spotify account first."
        )

    synced_count = await service.sync_scrobbles(current_user.id)

    return SyncResponse(
        synced_count=synced_count,
        message=f"Successfully synced {synced_count} new scrobbles from Spotify.",
    )
