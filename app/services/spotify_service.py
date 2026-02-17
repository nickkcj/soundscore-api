import base64
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from httpx import HTTPStatusError

from app.config import get_settings
from app.schemas.review import SpotifyAlbumResult
from app.services.cache_service import CacheService, CacheKeys
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

settings = get_settings()


class SpotifyService:
    """Service for interacting with Spotify API using global HTTP client."""

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

        client = get_http_client()
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




    async def search_albums(self, query: str, limit: int = 10) -> list[SpotifyAlbumResult]:
        """
        Search for albums on Spotify with error handling and caching.
        """
        if not query.strip():
            return []

        # 1. Check cache first
        query_hash = hashlib.md5(f"{query.lower()}:{limit}".encode()).hexdigest()
        cache_key = f"{CacheKeys.SPOTIFY_SEARCH}{query_hash}"

        try:
            cached = await CacheService.get_json(cache_key)
            if cached:
                return [SpotifyAlbumResult(**item) for item in cached]
        except Exception as e:
            logger.error(f"Erro ao ler cache: {e}")

        # 2. Get Access Token
        token = await self._get_access_token()

        # 3. Request to Spotify
        client = get_http_client()
        try:
            response = await client.get(
                f"{self.API_BASE_URL}/search",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": query,
                    "type": "album",
                    "limit": min(limit, 10),
                },
                timeout=10.0 # Evita que a requisição fique pendurada
            )
            
            # Se o Spotify responder algo diferente de 2xx, cai no except abaixo
            response.raise_for_status()
            data = response.json()

        except HTTPStatusError as e:
            # AQUI ESTÁ O SEGREDO: Loga o erro real do Spotify sem derrubar o app
            error_body = e.response.json() if e.response.content else e.response.text
            logger.error(f"Spotify API Error {e.response.status_code}: {error_body}")
            return [] # Retorna vazio pro front em vez de dar 502
        except Exception as e:
            logger.error(f"Erro inesperado na busca do Spotify: {e}")
            return []

        # 4. Parse Results
        albums = []
        items = data.get("albums", {}).get("items", [])
        
        for item in items:
            try:
                albums.append(
                    SpotifyAlbumResult(
                        spotify_id=item["id"],
                        title=item["name"],
                        artist=", ".join(artist["name"] for artist in item["artists"]),
                        cover_image=item["images"][0]["url"] if item.get("images") else None,
                        release_date=item.get("release_date"),
                    )
                )
            except (KeyError, IndexError) as e:
                logger.warning(f"Erro ao parsear álbum do Spotify: {e}")
                continue

        # 5. Cache results for 1 hour
        if albums:
            try:
                await CacheService.set_json(
                    cache_key,
                    [a.model_dump() for a in albums],
                    ttl=3600
                )
            except Exception as e:
                logger.error(f"Erro ao salvar no cache: {e}")

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

        client = get_http_client()
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

        client = get_http_client()
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
            Complete album details with tracks, or None if not found (cached for 24h)
        """
        # Check cache first
        cache_key = f"{CacheKeys.SPOTIFY_ALBUM}{spotify_id}"
        cached = await CacheService.get_json(cache_key)
        if cached:
            return cached

        token = await self._get_access_token()

        client = get_http_client()
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

        # Cache for 24 hours (album info doesn't change often)
        await CacheService.set_json(cache_key, album_details, ttl=86400)

        return album_details


# Singleton instance
spotify_service = SpotifyService()
