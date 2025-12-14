"""Spotify scrobble service for fetching and managing listening history."""

from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.models.oauth import OAuthAccount
from app.models.scrobble import Scrobble
from app.models.user import User
from app.config import get_settings

settings = get_settings()

SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyScrobbleService:
    """Service for interacting with Spotify API for scrobbling features."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_spotify_oauth(self, user_id: int) -> Optional[OAuthAccount]:
        """Get the Spotify OAuth account for a user."""
        result = await self.db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user_id,
                OAuthAccount.provider == 'spotify'
            )
        )
        return result.scalar_one_or_none()

    async def get_spotify_oauth_by_username(self, username: str) -> Optional[OAuthAccount]:
        """Get the Spotify OAuth account for a user by username."""
        result = await self.db.execute(
            select(OAuthAccount)
            .join(User)
            .where(
                User.username == username,
                OAuthAccount.provider == 'spotify'
            )
        )
        return result.scalar_one_or_none()

    async def refresh_token_if_needed(self, oauth: OAuthAccount) -> bool:
        """Refresh the access token if it's expired or about to expire."""
        if not oauth.token_expires_at:
            return False

        # Refresh if token expires in less than 5 minutes
        if oauth.token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return True  # Token still valid

        if not oauth.refresh_token:
            return False

        # Refresh the token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                'https://accounts.spotify.com/api/token',
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': oauth.refresh_token,
                    'client_id': settings.spotify_oauth_client_id,
                    'client_secret': settings.spotify_oauth_client_secret,
                }
            )

            if response.status_code != 200:
                return False

            data = response.json()
            oauth.access_token = data['access_token']
            if 'refresh_token' in data:
                oauth.refresh_token = data['refresh_token']
            oauth.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=data['expires_in'])

            await self.db.commit()
            return True

    async def get_currently_playing(self, oauth: OAuthAccount) -> Optional[dict]:
        """Get the currently playing track for a user."""
        if not oauth.access_token:
            return None

        if not await self.refresh_token_if_needed(oauth):
            if oauth.token_expires_at and oauth.token_expires_at < datetime.now(timezone.utc):
                return None

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me/player/currently-playing",
                headers={'Authorization': f'Bearer {oauth.access_token}'}
            )

            if response.status_code == 204:
                return None  # Nothing playing

            if response.status_code != 200:
                return None

            data = response.json()
            if not data or data.get('currently_playing_type') != 'track':
                return None

            track = data.get('item')
            if not track:
                return None

            return {
                'track_id': track['id'],
                'track_name': track['name'],
                'artist_name': ', '.join(a['name'] for a in track['artists']),
                'album_name': track['album']['name'],
                'album_image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'duration_ms': track['duration_ms'],
                'progress_ms': data.get('progress_ms', 0),
                'is_playing': data.get('is_playing', False),
            }

    async def get_recently_played(self, oauth: OAuthAccount, limit: int = 50) -> list[dict]:
        """Get recently played tracks from Spotify."""
        if not oauth.access_token:
            return []

        if not await self.refresh_token_if_needed(oauth):
            if oauth.token_expires_at and oauth.token_expires_at < datetime.now(timezone.utc):
                return []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me/player/recently-played",
                headers={'Authorization': f'Bearer {oauth.access_token}'},
                params={'limit': min(limit, 50)}
            )

            if response.status_code != 200:
                return []

            data = response.json()
            tracks = []

            for item in data.get('items', []):
                track = item['track']
                tracks.append({
                    'track_id': track['id'],
                    'track_name': track['name'],
                    'artist_name': ', '.join(a['name'] for a in track['artists']),
                    'album_name': track['album']['name'],
                    'album_image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                    'duration_ms': track['duration_ms'],
                    'played_at': item['played_at'],
                })

            return tracks

    async def sync_scrobbles(self, user_id: int) -> int:
        """Sync recently played tracks to scrobbles table."""
        oauth = await self.get_spotify_oauth(user_id)
        if not oauth:
            return 0

        tracks = await self.get_recently_played(oauth)
        if not tracks:
            return 0

        synced_count = 0
        for track in tracks:
            played_at = datetime.fromisoformat(track['played_at'].replace('Z', '+00:00'))

            # Use upsert to avoid duplicates
            stmt = insert(Scrobble).values(
                user_id=user_id,
                track_id=track['track_id'],
                track_name=track['track_name'],
                artist_name=track['artist_name'],
                album_name=track['album_name'],
                album_image_url=track['album_image_url'],
                duration_ms=track['duration_ms'],
                played_at=played_at,
            ).on_conflict_do_nothing(
                constraint='unique_scrobble'
            )

            result = await self.db.execute(stmt)
            if result.rowcount > 0:
                synced_count += 1

        await self.db.commit()
        return synced_count

    async def get_scrobbles(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> list[Scrobble]:
        """Get scrobbles for a user."""
        result = await self.db.execute(
            select(Scrobble)
            .where(Scrobble.user_id == user_id)
            .order_by(Scrobble.played_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_stats(self, user_id: int, days: int = 30) -> dict:
        """Get listening statistics for a user."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Total scrobbles
        total_result = await self.db.execute(
            select(func.count(Scrobble.id))
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
        )
        total_scrobbles = total_result.scalar() or 0

        # Unique artists count
        unique_artists_result = await self.db.execute(
            select(func.count(func.distinct(Scrobble.artist_name)))
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
        )
        unique_artists_count = unique_artists_result.scalar() or 0

        # Top artist
        top_artist_result = await self.db.execute(
            select(Scrobble.artist_name, func.count(Scrobble.id).label('count'))
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
            .group_by(Scrobble.artist_name)
            .order_by(func.count(Scrobble.id).desc())
            .limit(1)
        )
        top_artist_row = top_artist_result.first()
        top_artist = {
            'name': top_artist_row[0],
            'count': top_artist_row[1]
        } if top_artist_row else None

        # Top track
        top_track_result = await self.db.execute(
            select(
                Scrobble.track_name,
                Scrobble.artist_name,
                Scrobble.album_image_url,
                func.count(Scrobble.id).label('count')
            )
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
            .group_by(Scrobble.track_name, Scrobble.artist_name, Scrobble.album_image_url)
            .order_by(func.count(Scrobble.id).desc())
            .limit(1)
        )
        top_track_row = top_track_result.first()
        top_track = {
            'name': top_track_row[0],
            'artist': top_track_row[1],
            'image': top_track_row[2],
            'count': top_track_row[3]
        } if top_track_row else None

        # Scrobbles by day
        scrobbles_by_day_result = await self.db.execute(
            select(
                func.date(Scrobble.played_at).label('date'),
                func.count(Scrobble.id).label('count')
            )
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
            .group_by(func.date(Scrobble.played_at))
            .order_by(func.date(Scrobble.played_at))
        )
        scrobbles_by_day = [
            {'date': str(row[0]), 'count': row[1]}
            for row in scrobbles_by_day_result.all()
        ]

        return {
            'total_scrobbles': total_scrobbles,
            'unique_artists_count': unique_artists_count,
            'top_artist': top_artist,
            'top_track': top_track,
            'scrobbles_by_day': scrobbles_by_day,
        }

    async def get_top_artists(self, user_id: int, days: int = 30, limit: int = 10) -> list[dict]:
        """Get top artists for a user from local scrobbles (no images)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(Scrobble.artist_name, func.count(Scrobble.id).label('count'))
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
            .group_by(Scrobble.artist_name)
            .order_by(func.count(Scrobble.id).desc())
            .limit(limit)
        )

        return [
            {'name': row[0], 'scrobble_count': row[1]}
            for row in result.all()
        ]

    async def get_top_artists_from_spotify(
        self,
        oauth: OAuthAccount,
        time_range: str = 'medium_term',
        limit: int = 10
    ) -> list[dict]:
        """Get top artists directly from Spotify API (with images).

        Args:
            oauth: The user's Spotify OAuth account
            time_range: 'short_term' (4 weeks), 'medium_term' (6 months), 'long_term' (years)
            limit: Number of artists to return (max 50)
        """
        if not oauth.access_token:
            return []

        if not await self.refresh_token_if_needed(oauth):
            if oauth.token_expires_at and oauth.token_expires_at < datetime.now(timezone.utc):
                return []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me/top/artists",
                headers={'Authorization': f'Bearer {oauth.access_token}'},
                params={
                    'time_range': time_range,
                    'limit': min(limit, 50)
                }
            )

            if response.status_code != 200:
                return []

            data = response.json()
            artists = []

            for item in data.get('items', []):
                image_url = None
                if item.get('images') and len(item['images']) > 0:
                    # Find the best image for horizontal banner (widest with good quality)
                    images = item['images']
                    best_image = images[0]  # Default to largest

                    for img in images:
                        width = img.get('width') or 0
                        height = img.get('height') or 0
                        # Prefer wider images for horizontal banners
                        # Also ensure minimum quality (at least 300px wide)
                        if width >= 300:
                            best_width = best_image.get('width') or 0
                            if width > best_width:
                                best_image = img

                    image_url = best_image['url']

                artists.append({
                    'name': item['name'],
                    'image': image_url,
                    'spotify_id': item['id'],
                    'genres': item.get('genres', []),
                    'popularity': item.get('popularity', 0),
                })

            return artists

    async def get_top_tracks(self, user_id: int, days: int = 30, limit: int = 10) -> list[dict]:
        """Get top tracks for a user."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                Scrobble.track_name,
                Scrobble.artist_name,
                Scrobble.album_name,
                Scrobble.album_image_url,
                func.count(Scrobble.id).label('count')
            )
            .where(Scrobble.user_id == user_id, Scrobble.played_at >= since)
            .group_by(
                Scrobble.track_name,
                Scrobble.artist_name,
                Scrobble.album_name,
                Scrobble.album_image_url
            )
            .order_by(func.count(Scrobble.id).desc())
            .limit(limit)
        )

        return [
            {
                'name': row[0],
                'artist': row[1],
                'album': row[2],
                'image': row[3],
                'scrobble_count': row[4]
            }
            for row in result.all()
        ]

    async def get_top_albums(self, user_id: int, days: int = 30, limit: int = 10) -> list[dict]:
        """Get top albums for a user based on scrobble count.

        Albums are identified by the combination of album_name + artist_name.
        Scrobbles with null/empty album names are skipped.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                Scrobble.album_name,
                Scrobble.artist_name,
                Scrobble.album_image_url,
                func.count(Scrobble.id).label('count')
            )
            .where(
                Scrobble.user_id == user_id,
                Scrobble.played_at >= since,
                Scrobble.album_name.isnot(None),
                Scrobble.album_name != '',
            )
            .group_by(
                Scrobble.album_name,
                Scrobble.artist_name,
                Scrobble.album_image_url
            )
            .order_by(func.count(Scrobble.id).desc())
            .limit(limit)
        )

        return [
            {
                'name': row[0],
                'artist': row[1],
                'image': row[2],
                'scrobble_count': row[3]
            }
            for row in result.all()
        ]
