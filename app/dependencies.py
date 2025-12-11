from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedException
from app.services.cache_service import CacheService

# OAuth2 scheme for extracting bearer tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Cache TTL for user data (2 minutes - short enough to catch deactivations)
USER_CACHE_TTL = 120


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Dependency that extracts and validates the current user from JWT token.
    Uses Redis cache to avoid DB lookup on every request.

    Usage:
        @app.get("/protected")
        async def protected_route(current_user: User = Depends(get_current_user)):
            ...
    """
    # First, decode token to get user_id (if present) or username
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise UnauthorizedException()

    username = payload.get("sub")
    user_id = payload.get("user_id")  # New field we'll add to tokens

    if username is None:
        raise UnauthorizedException()

    # Try to get user from cache first (by user_id if available, else username)
    cache_key = f"user:auth:{user_id}" if user_id else f"user:auth:name:{username}"
    cached_user_data = await CacheService.get_json(cache_key)

    if cached_user_data:
        # Reconstruct user from cache (minimal fields needed for auth)
        # We still need to attach to session for any lazy loads
        result = await db.execute(
            select(User).where(User.id == cached_user_data["id"])
        )
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        # Cache is stale, user deleted or deactivated - continue to DB lookup

    # Cache miss or stale - query DB
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    # Cache the user data for subsequent requests
    await CacheService.set_json(
        f"user:auth:{user.id}",
        {"id": user.id, "username": user.username, "is_active": user.is_active},
        ttl=USER_CACHE_TTL
    )

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    Dependency that ensures the current user is active.

    Usage:
        @app.get("/active-only")
        async def active_route(user: User = Depends(get_current_active_user)):
            ...
    """
    if not current_user.is_active:
        raise UnauthorizedException("User account is inactive")
    return current_user


async def get_optional_user(
    token: Annotated[str | None, Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False))],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User | None:
    """
    Dependency that optionally extracts the current user.
    Returns None if no token or invalid token, instead of raising an exception.
    Uses Redis cache to avoid DB lookup on every request.

    Usage:
        @app.get("/public")
        async def public_route(user: User | None = Depends(get_optional_user)):
            if user:
                # Authenticated
            else:
                # Anonymous
    """
    if token is None:
        return None

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None

    username = payload.get("sub")
    user_id = payload.get("user_id")

    if username is None:
        return None

    # Try cache first
    cache_key = f"user:auth:{user_id}" if user_id else f"user:auth:name:{username}"
    cached_user_data = await CacheService.get_json(cache_key)

    if cached_user_data:
        result = await db.execute(
            select(User).where(User.id == cached_user_data["id"])
        )
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user

    # Cache miss - query DB
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    # Cache for next time
    await CacheService.set_json(
        f"user:auth:{user.id}",
        {"id": user.id, "username": user.username, "is_active": user.is_active},
        ttl=USER_CACHE_TTL
    )

    return user


async def get_user_from_query_token(
    token: Annotated[str, Query(...)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Dependency that extracts user from token passed as query parameter.
    Used for SSE endpoints where headers cannot be set (EventSource limitation).
    Uses Redis cache to avoid DB lookup on every request.

    Usage:
        @app.get("/stream")
        async def stream(user: User = Depends(get_user_from_query_token)):
            ...
    """
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise UnauthorizedException()

    username = payload.get("sub")
    user_id = payload.get("user_id")

    if username is None:
        raise UnauthorizedException()

    # Try cache first
    cache_key = f"user:auth:{user_id}" if user_id else f"user:auth:name:{username}"
    cached_user_data = await CacheService.get_json(cache_key)

    if cached_user_data:
        result = await db.execute(
            select(User).where(User.id == cached_user_data["id"])
        )
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user

    # Cache miss - query DB
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    # Cache for next time
    await CacheService.set_json(
        f"user:auth:{user.id}",
        {"id": user.id, "username": user.username, "is_active": user.is_active},
        ttl=USER_CACHE_TTL
    )

    return user


# Type aliases for cleaner dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
QueryTokenUser = Annotated[User, Depends(get_user_from_query_token)]
