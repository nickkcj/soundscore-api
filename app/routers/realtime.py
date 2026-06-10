"""
Supabase Realtime support.

The frontend subscribes to Postgres changes (new group/direct messages)
straight from Supabase. Authorization works via RLS: this endpoint mints
a short-lived JWT signed with the Supabase JWT secret, carrying the
SoundScore user id in the `app_user_id` claim, which the RLS policies
on group_messages/direct_messages check against memberships.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

from app.config import get_settings
from app.dependencies import CurrentUser

router = APIRouter()
settings = get_settings()

REALTIME_TOKEN_TTL_MINUTES = 55  # client should refresh before expiry


class RealtimeConfigResponse(BaseModel):
    """Everything supabase-js needs to subscribe to Realtime."""
    supabase_url: str
    supabase_anon_key: str
    token: str
    expires_in: int


@router.get(
    "/token",
    response_model=RealtimeConfigResponse,
    summary="Get Supabase Realtime credentials",
)
async def get_realtime_token(current_user: CurrentUser):
    """Mint a Supabase-compatible JWT for the authenticated user."""
    if not settings.supabase_url or not settings.supabase_jwt_secret or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Realtime is not configured")

    now = datetime.now(timezone.utc)
    expires_in = REALTIME_TOKEN_TTL_MINUTES * 60
    claims = {
        "sub": str(current_user.id),
        "role": "authenticated",       # role the RLS policies target
        "app_user_id": current_user.id,  # claim checked by the policies
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256")

    return RealtimeConfigResponse(
        supabase_url=settings.supabase_url,
        supabase_anon_key=settings.supabase_anon_key,
        token=token,
        expires_in=expires_in,
    )
