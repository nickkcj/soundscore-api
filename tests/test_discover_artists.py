from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.reviews import discover
from app.schemas.review import SpotifyArtistResult
from app.services.spotify_service import SpotifyService


@pytest.mark.asyncio
async def test_discover_artist_search_returns_real_spotify_artist_ids(monkeypatch) -> None:
    artist = SpotifyArtistResult(
        spotify_id="spotify-artist-123",
        name="Little Simz",
        image_url="https://i.scdn.co/image/artist.jpg",
        followers=1_234_567,
        genres=["uk hip hop"],
        popularity=79,
    )
    search_artists = AsyncMock(return_value=[artist])
    monkeypatch.setattr("app.routers.reviews.spotify_service.search_artists", search_artists)

    response = await discover(
        q="Little Simz",
        type="artists",
        limit=5,
        db=None,
        current_user=None,
    )

    search_artists.assert_awaited_once_with("Little Simz", 5)
    assert response.albums == []
    assert response.users == []
    assert response.reviews == []
    assert response.artists == [artist]


def test_discover_response_remains_backward_compatible_without_artists() -> None:
    from app.routers.reviews import DiscoverResponse

    response = DiscoverResponse(albums=[], users=[], reviews=[])

    assert response.artists == []


@pytest.mark.asyncio
async def test_spotify_artist_search_parses_and_caches_artist_metadata(monkeypatch) -> None:
    response = MagicMock()
    response.json.return_value = {
        "artists": {
            "items": [
                {
                    "followers": {"total": 42},
                    "genres": ["neo soul"],
                    "id": "artist-id",
                    "images": [{"url": "https://i.scdn.co/image/artist.jpg"}],
                    "name": "Artist Name",
                    "popularity": 88,
                }
            ]
        }
    }
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    cache_set = AsyncMock(return_value=True)

    monkeypatch.setattr("app.services.spotify_service.CacheService.get_json", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.spotify_service.CacheService.set_json", cache_set)
    monkeypatch.setattr("app.services.spotify_service.get_http_client", lambda: client)

    service = SpotifyService()
    service._get_access_token = AsyncMock(return_value="token")

    artists = await service.search_artists("  Artist Name  ", limit=10)

    client.get.assert_awaited_once()
    assert client.get.await_args.kwargs["params"] == {
        "limit": 10,
        "q": "Artist Name",
        "type": "artist",
    }
    assert artists == [
        SpotifyArtistResult(
            followers=42,
            genres=["neo soul"],
            image_url="https://i.scdn.co/image/artist.jpg",
            name="Artist Name",
            popularity=88,
            spotify_id="artist-id",
        )
    ]
    cache_set.assert_awaited_once()
