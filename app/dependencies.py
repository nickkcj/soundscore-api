from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.core.security import verify_access_token
from app.core.exceptions import UnauthorizedException

# OAuth2 scheme for extracting bearer tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Dependency that extracts and validates the current user from JWT token.

    Usage:
        @app.get("/protected")
        async def protected_route(current_user: User = Depends(get_current_user)):
            ...
    """
    username = verify_access_token(token)
    if username is None:
        raise UnauthorizedException()

    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

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

    username = verify_access_token(token)
    if username is None:
        return None

    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    return user


async def get_user_from_query_token(
    token: Annotated[str, Query(...)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Dependency that extracts user from token passed as query parameter.
    Used for SSE endpoints where headers cannot be set (EventSource limitation).

    Usage:
        @app.get("/stream")
        async def stream(user: User = Depends(get_user_from_query_token)):
            ...
    """
    username = verify_access_token(token)
    if username is None:
        raise UnauthorizedException()

    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    return user


# Type aliases for cleaner dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
QueryTokenUser = Annotated[User, Depends(get_user_from_query_token)]
