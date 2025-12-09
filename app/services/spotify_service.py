import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import get_settings
from app.schemas.review import SpotifyAlbumResult

settings = get_settings()


class SpotifyService:
    """Service for interacting with Spotify API."""

    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE_URL = "https://api.spotify.com/v1"

    def __init__(self):
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def _get_access_token(self) -> str:
        """Get or refresh Spotify access token using Client Credentials flow."""
        # Return cached token if still valid
        if self._access_token and self._token_expires_at:
            if datetime.now(timezone.utc) < self._token_expires_at:
                return self._access_token

        # Get new token
        if not settings.spotify_client_id or not settings.spotify_client_secret:
            raise ValueError("Spotify credentials not configured")

        credentials = f"{settings.spotify_client_id}:{settings.spotify_client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        # Set expiry 5 minutes before actual expiry for safety
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)

        return self._access_token

    async def search_albums(self, query: str, limit: int = 20) -> list[SpotifyAlbumResult]:
        """
        Search for albums on Spotify.

        Args:
            query: Search query string
            limit: Maximum number of results (default 20, max 50)

        Returns:
            List of album search results
        """
        if not query.strip():
            return []

        token = await self._get_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/search",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": query,
                    "type": "album",
                    "limit": min(limit, 50),
                },
            )
            response.raise_for_status()
            data = response.json()

        albums = []
        for item in data.get("albums", {}).get("items", []):
            albums.append(
                SpotifyAlbumResult(
                    spotify_id=item["id"],
                    title=item["name"],
                    artist=", ".join(artist["name"] for artist in item["artists"]),
                    cover_image=item["images"][0]["url"] if item.get("images") else None,
                    release_date=item.get("release_date"),
                )
            )

        return albums

    async def get_album(self, spotify_id: str) -> Optional[SpotifyAlbumResult]:
        """
        Get album details by Spotify ID.

        Args:
            spotify_id: Spotify album ID

        Returns:
            Album details or None if not found
        """
        token = await self._get_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/albums/{spotify_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            item = response.json()

        return SpotifyAlbumResult(
            spotify_id=item["id"],
            title=item["name"],
            artist=", ".join(artist["name"] for artist in item["artists"]),
            cover_image=item["images"][0]["url"] if item.get("images") else None,
            release_date=item.get("release_date"),
        )

    async def get_album_tracks(self, spotify_id: str) -> list[dict]:
        """
        Get tracks for an album.

        Args:
            spotify_id: Spotify album ID

        Returns:
            List of track info dictionaries
        """
        token = await self._get_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.API_BASE_URL}/albums/{spotify_id}/tracks",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 50},
            )

            if response.status_code == 404:
                return []

            response.raise_for_status()
            data = response.json()

        tracks = []
        for item in data.get("items", []):
            tracks.append({
                "track_number": item.get("track_number"),
                "name": item.get("name"),
                "duration_ms": item.get("duration_ms"),
                "preview_url": item.get("preview_url"),
            })

        return tracks

    async def get_album_details(self, spotify_id: str) -> Optional[dict]:
        """
        Get complete album details including tracks.

        Args:
            spotify_id: Spotify album ID

        Returns:
            Complete album details with tracks, or None if not found
        """
        token = await self._get_access_token()

        async with httpx.AsyncClient() as client:
            # Fetch album details
            response = await client.get(
                f"{self.API_BASE_URL}/albums/{spotify_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            album_data = response.json()

        # Extract album info
        album_details = {
            "spotify_id": album_data["id"],
            "title": album_data["name"],
            "artist": ", ".join(artist["name"] for artist in album_data["artists"]),
            "cover_image": album_data["images"][0]["url"] if album_data.get("images") else None,
            "release_date": album_data.get("release_date"),
            "label": album_data.get("label"),
            "copyrights": [c.get("text", "") for c in album_data.get("copyrights", [])],
            "total_tracks": album_data.get("total_tracks", 0),
            "popularity": album_data.get("popularity", 0),
            "spotify_url": album_data.get("external_urls", {}).get("spotify", ""),
        }

        # Extract tracks from the album response (already included)
        tracks = []
        tracks_data = album_data.get("tracks", {}).get("items", [])
        for item in tracks_data:
            tracks.append({
                "track_number": item.get("track_number", 0),
                "name": item.get("name", ""),
                "duration_ms": item.get("duration_ms", 0),
                "explicit": item.get("explicit", False),
                "spotify_url": item.get("external_urls", {}).get("spotify", ""),
                "artists": ", ".join(artist["name"] for artist in item.get("artists", [])),
            })

        album_details["tracks"] = tracks

        return album_details


# Singleton instance
spotify_service = SpotifyService()
