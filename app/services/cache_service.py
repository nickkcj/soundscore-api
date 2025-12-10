"""
Redis Cache Service for SoundScore.

Provides a simple interface for caching data with TTL support.
"""
import json
from typing import Any

import redis.asyncio as redis

from app.config import get_settings


class CacheService:
    """Redis cache service with async support."""

    _client: redis.Redis | None = None

    @classmethod
    async def get_client(cls) -> redis.Redis:
        """Get or create Redis client connection."""
        if cls._client is None:
            settings = get_settings()
            cls._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return cls._client

    @classmethod
    async def get(cls, key: str) -> str | None:
        """Get a value from cache."""
        try:
            client = await cls.get_client()
            return await client.get(key)
        except Exception:
            # If Redis fails, return None (cache miss)
            return None

    @classmethod
    async def set(cls, key: str, value: str, ttl: int = 300) -> bool:
        """
        Set a value in cache with TTL.

        Args:
            key: Cache key
            value: Value to store (string)
            ttl: Time to live in seconds (default 5 minutes)

        Returns:
            True if successful, False otherwise
        """
        try:
            client = await cls.get_client()
            await client.set(key, value, ex=ttl)
            return True
        except Exception:
            return False

    @classmethod
    async def get_json(cls, key: str) -> Any | None:
        """Get a JSON value from cache."""
        value = await cls.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    async def set_json(cls, key: str, value: Any, ttl: int = 300) -> bool:
        """Set a JSON value in cache."""
        try:
            return await cls.set(key, json.dumps(value), ttl)
        except (TypeError, ValueError):
            return False

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete a key from cache."""
        try:
            client = await cls.get_client()
            await client.delete(key)
            return True
        except Exception:
            return False

    @classmethod
    async def delete_pattern(cls, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Pattern to match (e.g., "user:*")

        Returns:
            Number of keys deleted
        """
        try:
            client = await cls.get_client()
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return await client.delete(*keys)
            return 0
        except Exception:
            return 0

    @classmethod
    async def close(cls) -> None:
        """Close Redis connection."""
        if cls._client:
            await cls._client.close()
            cls._client = None


# Cache key prefixes
class CacheKeys:
    """Cache key prefixes for different data types."""

    SIGNED_URL = "signed_url:"  # TTL: 45 min
    SPOTIFY_SEARCH = "spotify:search:"  # TTL: 1 hour
    SPOTIFY_ALBUM = "spotify:album:"  # TTL: 24 hours
    TRENDING_ALBUMS = "trending:albums"  # TTL: 5 min
    USER_PROFILE = "user:profile:"  # TTL: 5 min
