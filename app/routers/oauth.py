"""OAuth router for Google and Spotify authentication."""

import html
import hashlib
import json
import secrets
import re
from datetime import datetime, timezone, timedelta
from typing import Literal
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.oauth import OAuthAccount, OAuthExchangeCode
from app.services.oauth_service import (
    oauth,
    get_spotify_user_info,
    is_provider_configured,
)
from app.core.security import (
    create_access_token,
    create_oauth_link_token,
    create_refresh_token,
    verify_oauth_link_token,
)
from app.core.exceptions import BadRequestException, ConflictException
from app.config import get_settings
from app.dependencies import DbSession, CurrentUser
from app.schemas.auth import MessageResponse, TokenResponse
from app.schemas.oauth import (
    LinkedAccountsResponse,
    OAuthAccountResponse,
    OAuthExchangeRequest,
    OAuthLinkIntentRequest,
    OAuthLinkIntentResponse,
)

router = APIRouter()
settings = get_settings()

MOBILE_OAUTH_SCHEMES = {"soundscore", "soundscore-dev", "soundscore-preview"}
MOBILE_OAUTH_HTTPS_REDIRECTS = {
    "https://www.soundscore.com.br/reviews/oauth/callback",
}
MOBILE_EXCHANGE_CODE_TTL_SECONDS = 120


def create_mobile_app_bridge(redirect_uri: str, query: str) -> HTMLResponse:
    """Render a user-activated Android handoff when Custom Tabs block redirects."""
    if redirect_uri in MOBILE_OAUTH_HTTPS_REDIRECTS:
        callback_url = f"soundscore://oauth/callback?{query}"
    else:
        callback_url = f"{redirect_uri}?{query}"
    safe_href = html.escape(callback_url, quote=True)
    script_target = json.dumps(callback_url)
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Return to SoundScore</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #FAF8F6; color: #251014; font-family: system-ui, sans-serif; }}
    main {{ width: min(100%, 420px); text-align: center; }}
    .mark {{ width: 64px; height: 64px; margin: 0 auto 20px; display: grid; place-items: center; border-radius: 50%; background: #F5E7E9; color: #722F37; font-size: 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    p {{ margin: 0 0 24px; color: #625850; line-height: 1.5; }}
    a {{ display: block; width: 100%; padding: 14px 18px; border-radius: 14px; background: #722F37; color: white; font-weight: 700; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <div class="mark">♪</div>
    <h1>Return to SoundScore</h1>
    <p>Your Spotify authorization is complete. Continue in the app.</p>
    <a href="{safe_href}">Open SoundScore</a>
  </main>
  <script>window.location.replace({script_target});</script>
</body>
</html>"""
    return HTMLResponse(
        content=body,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
        },
    )


def configure_oauth_client(
    request: Request,
    client: Literal["web", "mobile"],
    redirect_uri: str | None,
) -> None:
    """Persist a validated OAuth client target in the signed session cookie."""
    request.session.pop("oauth_mobile_redirect_uri", None)
    if client == "web":
        return

    if not redirect_uri:
        raise BadRequestException("A redirect URI is required for mobile OAuth")

    parsed = urlparse(redirect_uri)
    is_native_scheme = (
        parsed.scheme in MOBILE_OAUTH_SCHEMES
        and parsed.netloc == "oauth"
        and parsed.path.rstrip("/") == "/callback"
    )
    is_verified_app_link = redirect_uri in MOBILE_OAUTH_HTTPS_REDIRECTS
    if (
        not (is_native_scheme or is_verified_app_link)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise BadRequestException("Invalid mobile OAuth redirect URI")

    request.session["oauth_mobile_redirect_uri"] = redirect_uri


def configure_oauth_link(request: Request, provider: str, link_token: str | None) -> None:
    """Bind a validated native link intent to the signed OAuth session."""
    request.session.pop("oauth_link_user_id", None)
    if link_token is None:
        return
    user_id = verify_oauth_link_token(link_token, provider)
    if user_id is None:
        raise BadRequestException("Invalid or expired OAuth link request")
    request.session["oauth_link_user_id"] = user_id


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
    link_user_id: int | None = None,
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

    if link_user_id is not None:
        target_result = await db.execute(select(User).where(User.id == link_user_id))
        target_user = target_result.scalar_one_or_none()
        if target_user is None or not target_user.is_active:
            raise BadRequestException("The account receiving this connection is unavailable")

        if oauth_account and oauth_account.user_id != target_user.id:
            raise ConflictException(f"This {provider.title()} account is linked to another user")

        current_result = await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == target_user.id,
                OAuthAccount.provider == provider,
            )
        )
        current_account = current_result.scalar_one_or_none()
        if current_account and current_account.provider_user_id != provider_user_id:
            raise ConflictException(f"A different {provider.title()} account is already connected")

        linked_account = oauth_account or current_account
        if linked_account is None:
            linked_account = OAuthAccount(
                user_id=target_user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=email,
            )
            db.add(linked_account)

        linked_account.provider_email = email
        linked_account.access_token = access_token
        linked_account.refresh_token = refresh_token
        linked_account.token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            if expires_in
            else None
        )
        target_user.last_login = datetime.now(timezone.utc)
        await db.commit()
        return target_user

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


async def create_auth_redirect(
    request: Request,
    db: AsyncSession,
    user: User | None,
    error: str | None = None,
) -> RedirectResponse | HTMLResponse:
    """Return web tokens or a short-lived code for an approved native callback."""
    mobile_redirect_uri = request.session.pop("oauth_mobile_redirect_uri", None) or getattr(
        request.state,
        "oauth_mobile_redirect_uri",
        None,
    )
    request.state.oauth_mobile_redirect_uri = mobile_redirect_uri

    if mobile_redirect_uri:
        parsed_mobile_redirect = urlparse(mobile_redirect_uri)
        use_android_bridge = (
            parsed_mobile_redirect.scheme in MOBILE_ANDROID_PACKAGES
            or mobile_redirect_uri in MOBILE_OAUTH_HTTPS_REDIRECTS
        )
        if error or user is None:
            query = urlencode({"error": error or "OAuth sign-in failed"})
            if use_android_bridge:
                return create_mobile_app_bridge(mobile_redirect_uri, query)
            return RedirectResponse(url=f"{mobile_redirect_uri}?{query}", status_code=302)

        raw_code = secrets.token_urlsafe(48)
        code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        db.add(
            OAuthExchangeCode(
                code_hash=code_hash,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=MOBILE_EXCHANGE_CODE_TTL_SECONDS),
            )
        )
        await db.commit()
        query = urlencode({"code": raw_code})
        if use_android_bridge:
            return create_mobile_app_bridge(mobile_redirect_uri, query)
        return RedirectResponse(
            url=f"{mobile_redirect_uri}?{query}",
            status_code=302,
        )

    frontend_url = settings.frontend_url
    if error or user is None:
        return RedirectResponse(
            url=f"{frontend_url}/oauth/callback?{urlencode({'error': error or 'OAuth sign-in failed'})}",
            status_code=302,
        )

    access_token = create_access_token(subject=user.username, user_id=user.id)
    refresh_token = create_refresh_token(subject=user.username, user_id=user.id)
    return RedirectResponse(
        url=f"{frontend_url}/oauth/callback?{urlencode({'access_token': access_token, 'refresh_token': refresh_token})}",
        status_code=302,
    )


# ============= Google OAuth =============

@router.get("/google/login")
async def google_login(
    request: Request,
    client: Literal["web", "mobile"] = Query(default="web"),
    redirect_uri: str | None = Query(default=None),
    link_token: str | None = Query(default=None),
):
    """Initiate Google OAuth login."""
    if not is_provider_configured('google'):
        raise BadRequestException("Google OAuth is not configured")

    configure_oauth_client(request, client, redirect_uri)
    configure_oauth_link(request, "google", link_token)
    redirect_uri = f"{settings.backend_url}/api/v1/oauth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback."""
    if not is_provider_configured('google'):
        raise BadRequestException("Google OAuth is not configured")

    try:
        link_user_id = request.session.pop("oauth_link_user_id", None)
        token = await oauth.google.authorize_access_token(request)

        # Google returns user info in the ID token
        user_info = token.get('userinfo')
        if not user_info:
            return await create_auth_redirect(request, db, None, error="Failed to get user info from Google")

        provider_user_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name') or user_info.get('given_name')

        if not provider_user_id:
            return await create_auth_redirect(request, db, None, error="Invalid Google user data")

        user = await find_or_create_user(
            db=db,
            provider='google',
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            link_user_id=link_user_id,
        )

        if not user.is_active:
            return await create_auth_redirect(request, db, None, error="User account is inactive")

        return await create_auth_redirect(request, db, user)

    except Exception:
        return await create_auth_redirect(request, db, None, error="Google sign-in failed")


# ============= Spotify OAuth =============

@router.get("/spotify/login")
async def spotify_login(
    request: Request,
    client: Literal["web", "mobile"] = Query(default="web"),
    redirect_uri: str | None = Query(default=None),
    link_token: str | None = Query(default=None),
):
    """Initiate Spotify OAuth login."""
    if not is_provider_configured('spotify'):
        raise BadRequestException("Spotify OAuth is not configured")

    configure_oauth_client(request, client, redirect_uri)
    configure_oauth_link(request, "spotify", link_token)
    redirect_uri = f"{settings.backend_url}/api/v1/oauth/spotify/callback"
    return await oauth.spotify.authorize_redirect(request, redirect_uri)


@router.get("/spotify/callback")
async def spotify_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Spotify OAuth callback."""
    if not is_provider_configured('spotify'):
        raise BadRequestException("Spotify OAuth is not configured")

    try:
        link_user_id = request.session.pop("oauth_link_user_id", None)
        token = await oauth.spotify.authorize_access_token(request)
        access_token = token.get('access_token')

        if not access_token:
            return await create_auth_redirect(request, db, None, error="Failed to get access token from Spotify")

        # Fetch user info from Spotify API
        user_info = await get_spotify_user_info(access_token)

        provider_user_id = user_info.get('id')
        email = user_info.get('email')
        name = user_info.get('display_name')

        if not provider_user_id:
            return await create_auth_redirect(request, db, None, error="Invalid Spotify user data")

        user = await find_or_create_user(
            db=db,
            provider='spotify',
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            access_token=access_token,
            refresh_token=token.get('refresh_token'),
            expires_in=token.get('expires_in'),
            link_user_id=link_user_id,
        )

        if not user.is_active:
            return await create_auth_redirect(request, db, None, error="User account is inactive")

        return await create_auth_redirect(request, db, user)

    except Exception:
        return await create_auth_redirect(request, db, None, error="Spotify sign-in failed")


@router.post("/mobile/exchange", response_model=TokenResponse)
async def exchange_mobile_code(request: OAuthExchangeRequest, db: DbSession):
    """Atomically exchange a short-lived native authorization code for JWTs."""
    now = datetime.now(timezone.utc)
    code_hash = hashlib.sha256(request.code.encode("utf-8")).hexdigest()
    result = await db.execute(
        update(OAuthExchangeCode)
        .where(
            OAuthExchangeCode.code_hash == code_hash,
            OAuthExchangeCode.consumed_at.is_(None),
            OAuthExchangeCode.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(OAuthExchangeCode.user_id)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise BadRequestException("Invalid or expired authorization code")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise BadRequestException("Invalid or expired authorization code")

    await db.commit()
    return TokenResponse(
        access_token=create_access_token(subject=user.username, user_id=user.id),
        refresh_token=create_refresh_token(subject=user.username, user_id=user.id),
    )


@router.post("/mobile/link-intent", response_model=OAuthLinkIntentResponse)
async def create_mobile_link_intent(
    payload: OAuthLinkIntentRequest,
    current_user: CurrentUser,
):
    """Create a short-lived URL that links a provider to the authenticated user."""
    parsed = urlparse(payload.redirect_uri)
    if (
        parsed.scheme not in MOBILE_OAUTH_SCHEMES
        or parsed.netloc != "oauth"
        or parsed.path.rstrip("/") != "/callback"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise BadRequestException("Invalid mobile OAuth redirect URI")

    link_token = create_oauth_link_token(current_user.id, payload.provider)
    query = urlencode(
        {
            "client": "mobile",
            "redirect_uri": payload.redirect_uri,
            "link_token": link_token,
        }
    )
    return OAuthLinkIntentResponse(
        start_url=f"{settings.backend_url}/api/v1/oauth/{payload.provider}/login?{query}"
    )


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


@router.delete("/linked-accounts/{provider}", response_model=MessageResponse)
async def disconnect_linked_account(
    provider: Literal["google", "spotify"],
    current_user: CurrentUser,
    db: DbSession,
):
    """Disconnect a provider without allowing the user to lock themselves out."""
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == current_user.id,
            OAuthAccount.provider == provider,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise BadRequestException(f"{provider.title()} is not connected")

    accounts_result = await db.execute(
        select(func.count()).select_from(OAuthAccount).where(OAuthAccount.user_id == current_user.id)
    )
    account_count = accounts_result.scalar() or 0
    if current_user.password_hash is None and account_count <= 1:
        raise BadRequestException("Add another sign-in method before disconnecting this account")

    await db.delete(account)
    await db.commit()
    return MessageResponse(message=f"{provider.title()} disconnected successfully")
