"""OAuth service for Google and Spotify authentication."""

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
import httpx

from app.config import get_settings

settings = get_settings()

oauth = OAuth()

# Google OAuth - OpenID Connect
if settings.google_oauth_client_id and settings.google_oauth_client_secret:
    oauth.register(
        name='google',
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

# Spotify OAuth
if settings.spotify_oauth_client_id and settings.spotify_oauth_client_secret:
    oauth.register(
        name='spotify',
        client_id=settings.spotify_oauth_client_id,
        client_secret=settings.spotify_oauth_client_secret,
        authorize_url='https://accounts.spotify.com/authorize',
        access_token_url='https://accounts.spotify.com/api/token',
        client_kwargs={
            'scope': 'user-read-email user-read-private'
        }
    )


async def get_spotify_user_info(access_token: str) -> dict:
    """Fetch user info from Spotify API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://api.spotify.com/v1/me',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        response.raise_for_status()
        return response.json()


def get_oauth_client(provider: str):
    """Get OAuth client for a provider."""
    if provider == 'google':
        return oauth.google if hasattr(oauth, 'google') else None
    elif provider == 'spotify':
        return oauth.spotify if hasattr(oauth, 'spotify') else None
    return None


def is_provider_configured(provider: str) -> bool:
    """Check if a provider is properly configured."""
    if provider == 'google':
        return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)
    elif provider == 'spotify':
        return bool(settings.spotify_oauth_client_id and settings.spotify_oauth_client_secret)
    return False
