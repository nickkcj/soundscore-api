"""OAuth router for Google and Spotify authentication."""

import secrets
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.oauth import OAuthAccount
from app.services.oauth_service import (
    oauth,
    get_spotify_user_info,
    is_provider_configured,
)
from app.core.security import create_access_token, create_refresh_token
from app.core.exceptions import BadRequestException
from app.config import get_settings
from app.dependencies import DbSession, CurrentUser
from app.schemas.oauth import LinkedAccountsResponse, OAuthAccountResponse

router = APIRouter()
settings = get_settings()


async def generate_unique_username(db: AsyncSession, base_name: str) -> str:
    """Generate a unique username based on OAuth profile name."""
    # Clean the base name - only allow alphanumeric and underscore
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '', base_name.lower())

    # Ensure minimum length
    if len(clean_name) < 3:
        clean_name = f"user_{clean_name}"

    # Truncate if too long (leaving room for suffix)
    if len(clean_name) > 40:
        clean_name = clean_name[:40]

    # Check if username exists
    result = await db.execute(
        select(User).where(User.username == clean_name)
    )
    if not result.scalar_one_or_none():
        return clean_name

    # Add random suffix
    for _ in range(10):
        suffix = secrets.token_hex(3)
        username = f"{clean_name}_{suffix}"
        if len(username) > 50:
            username = f"{clean_name[:40]}_{suffix}"

        result = await db.execute(
            select(User).where(User.username == username)
        )
        if not result.scalar_one_or_none():
            return username

    # Fallback with timestamp
    return f"user_{secrets.token_hex(8)}"


async def find_or_create_user(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str | None,
    name: str | None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_in: int | None = None,
) -> User:
    """Find existing user or create new one from OAuth data."""

    # 1. Check if OAuth account already linked
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        # User already has this OAuth linked, update tokens and get the user
        if access_token:
            oauth_account.access_token = access_token
            oauth_account.refresh_token = refresh_token
            if expires_in:
                oauth_account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        result = await db.execute(
            select(User).where(User.id == oauth_account.user_id)
        )
        user = result.scalar_one()
        user.last_login = datetime.now(timezone.utc)
        await db.commit()
        return user

    # 2. Check if email matches existing user (link accounts)
    if email:
        result = await db.execute(
            select(User).where(func.lower(User.email) == email.lower())
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # Link OAuth to existing user
            token_expires_at = None
            if expires_in:
                token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            oauth_account = OAuthAccount(
                user_id=existing_user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=email,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
            )
            db.add(oauth_account)
            existing_user.last_login = datetime.now(timezone.utc)
            await db.commit()
            return existing_user

    # 3. Create new user
    username = await generate_unique_username(db, name or "user")

    new_user = User(
        username=username,
        email=email.lower() if email else f"{provider}_{provider_user_id}@oauth.local",
        password_hash=None,  # OAuth-only user, no password
    )
    db.add(new_user)
    await db.flush()  # Get the user ID

    # Link OAuth account
    token_expires_at = None
    if expires_in:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    oauth_account = OAuthAccount(
        user_id=new_user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=email,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )
    db.add(oauth_account)

    new_user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(new_user)

    return new_user


def create_frontend_redirect(user: User, error: str | None = None) -> RedirectResponse:
    """Create redirect to frontend with tokens or error."""
    frontend_url = settings.frontend_url

    if error:
        return RedirectResponse(
            url=f"{frontend_url}/oauth/callback?error={error}",
            status_code=302
        )

    access_token = create_access_token(subject=user.username)
    refresh_token = create_refresh_token(subject=user.username)

    return RedirectResponse(
        url=f"{frontend_url}/oauth/callback?access_token={access_token}&refresh_token={refresh_token}",
        status_code=302
    )


# ============= Google OAuth =============

@router.get("/google/login")
async def google_login(request: Request):
    """Initiate Google OAuth login."""
    if not is_provider_configured('google'):
        raise BadRequestException("Google OAuth is not configured")

    redirect_uri = f"{settings.backend_url}/api/v1/oauth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback."""
    if not is_provider_configured('google'):
        raise BadRequestException("Google OAuth is not configured")

    try:
        token = await oauth.google.authorize_access_token(request)

        # Google returns user info in the ID token
        user_info = token.get('userinfo')
        if not user_info:
            return create_frontend_redirect(None, error="Failed to get user info from Google")

        provider_user_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name') or user_info.get('given_name')

        if not provider_user_id:
            return create_frontend_redirect(None, error="Invalid Google user data")

        user = await find_or_create_user(
            db=db,
            provider='google',
            provider_user_id=provider_user_id,
            email=email,
            name=name,
        )

        if not user.is_active:
            return create_frontend_redirect(None, error="User account is inactive")

        return create_frontend_redirect(user)

    except Exception as e:
        return create_frontend_redirect(None, error=f"OAuth error: {str(e)}")


# ============= Spotify OAuth =============

@router.get("/spotify/login")
async def spotify_login(request: Request):
    """Initiate Spotify OAuth login."""
    if not is_provider_configured('spotify'):
        raise BadRequestException("Spotify OAuth is not configured")

    redirect_uri = f"{settings.backend_url}/api/v1/oauth/spotify/callback"
    return await oauth.spotify.authorize_redirect(request, redirect_uri)


@router.get("/spotify/callback")
async def spotify_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Spotify OAuth callback."""
    if not is_provider_configured('spotify'):
        raise BadRequestException("Spotify OAuth is not configured")

    try:
        token = await oauth.spotify.authorize_access_token(request)
        access_token = token.get('access_token')

        if not access_token:
            return create_frontend_redirect(None, error="Failed to get access token from Spotify")

        # Fetch user info from Spotify API
        user_info = await get_spotify_user_info(access_token)

        provider_user_id = user_info.get('id')
        email = user_info.get('email')
        name = user_info.get('display_name')

        if not provider_user_id:
            return create_frontend_redirect(None, error="Invalid Spotify user data")

        user = await find_or_create_user(
            db=db,
            provider='spotify',
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            access_token=access_token,
            refresh_token=token.get('refresh_token'),
            expires_in=token.get('expires_in'),
        )

        if not user.is_active:
            return create_frontend_redirect(None, error="User account is inactive")

        return create_frontend_redirect(user)

    except Exception as e:
        return create_frontend_redirect(None, error=f"OAuth error: {str(e)}")


# ============= Account Management =============

@router.get("/linked-accounts", response_model=LinkedAccountsResponse)
async def get_linked_accounts(current_user: CurrentUser, db: DbSession):
    """Get the current user's linked OAuth accounts."""
    result = await db.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == current_user.id)
    )
    oauth_accounts = result.scalars().all()

    google_account = None
    spotify_account = None

    for account in oauth_accounts:
        if account.provider == 'google':
            google_account = OAuthAccountResponse.model_validate(account)
        elif account.provider == 'spotify':
            spotify_account = OAuthAccountResponse.model_validate(account)

    return LinkedAccountsResponse(
        google=google_account,
        spotify=spotify_account,
        has_password=current_user.password_hash is not None,
    )
