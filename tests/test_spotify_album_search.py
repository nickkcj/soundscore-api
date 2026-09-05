from unittest.mock import AsyncMock

import pytest

from app.services.spotify_service import SpotifyService


@pytest.mark.asyncio
async def test_album_search_deduplicates_equivalent_cached_editions(monkeypatch) -> None:
    cached_albums = [
        {
            "spotify_id": "petal-us",
            "title": "petal",
            "artist": "Ariana Grande",
            "cover_image": "https://i.scdn.co/petal.jpg",
            "release_date": "2026-01-01",
        },
        {
            "spotify_id": "petal-br",
            "title": " PETAL ",
            "artist": "Ariana   Grande",
            "cover_image": "https://i.scdn.co/petal.jpg",
            "release_date": "2026",
        },
        {
            "spotify_id": "eternal-sunshine",
            "title": "eternal sunshine",
            "artist": "Ariana Grande",
            "cover_image": "https://i.scdn.co/eternal-sunshine.jpg",
            "release_date": "2024-03-08",
        },
    ]
    monkeypatch.setattr(
        "app.services.spotify_service.CacheService.get_json",
        AsyncMock(return_value=cached_albums),
    )

    albums = await SpotifyService().search_albums("Ariana", limit=10)

    assert [album.spotify_id for album in albums] == [
        "petal-us",
        "eternal-sunshine",
    ]


def test_album_deduplication_keeps_named_versions() -> None:
    from app.schemas.review import SpotifyAlbumResult

    albums = [
        SpotifyAlbumResult(
            spotify_id="standard",
            title="eternal sunshine",
            artist="Ariana Grande",
            release_date="2024-03-08",
        ),
        SpotifyAlbumResult(
            spotify_id="deluxe",
            title="eternal sunshine deluxe",
            artist="Ariana Grande",
            release_date="2025-03-28",
        ),
    ]

    assert SpotifyService._deduplicate_albums(albums, limit=10) == albums
