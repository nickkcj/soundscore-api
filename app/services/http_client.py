"""
Global HTTP Client with connection pooling for external API calls.

This module provides a singleton HTTP client that should be used for all
external HTTP requests (Supabase, Spotify, etc.) to:
1. Avoid creating new connections on every request
2. Reuse TCP connections (connection pooling)
3. Have consistent timeout settings
4. Reduce latency significantly in serverless environments
"""
import httpx
from typing import Optional


class HTTPClientManager:
    """Manages a global httpx.AsyncClient with connection pooling."""

    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """
        Get or create the global HTTP client.

        The client is created lazily on first use but then reused.
        Connection limits and timeouts are optimized for serverless.
        """
        if cls._client is None:
            cls._client = httpx.AsyncClient(
                # Connection pooling settings
                limits=httpx.Limits(
                    max_keepalive_connections=20,  # Keep 20 connections alive
                    max_connections=50,            # Max 50 total connections
                    keepalive_expiry=30.0,         # Close idle connections after 30s
                ),
                # Timeout settings - fail fast
                timeout=httpx.Timeout(
                    connect=5.0,    # 5s to establish connection
                    read=15.0,      # 15s to read response
                    write=10.0,     # 10s to write request
                    pool=5.0,       # 5s to get connection from pool
                ),
                # HTTP/2 for better performance with APIs that support it
                http2=True,
                # Follow redirects automatically
                follow_redirects=True,
            )
        return cls._client

    @classmethod
    async def close(cls) -> None:
        """Close the HTTP client. Call this on app shutdown."""
        if cls._client is not None:
            await cls._client.aclose()
            cls._client = None

    @classmethod
    async def warmup(cls) -> None:
        """
        Warm up the HTTP client by creating it early.
        Call this in the app lifespan startup.
        """
        cls.get_client()


# Convenience function for getting the client
def get_http_client() -> httpx.AsyncClient:
    """Get the global HTTP client instance."""
    return HTTPClientManager.get_client()
