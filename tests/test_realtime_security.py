from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt

from app.routers import realtime


@pytest.mark.asyncio
async def test_realtime_token_uses_short_lived_stable_user_claim(monkeypatch) -> None:
    monkeypatch.setattr(realtime.settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(realtime.settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(realtime.settings, "supabase_jwt_secret", "realtime-test-secret")

    response = await realtime.get_realtime_token(SimpleNamespace(id=42))
    claims = jwt.decode(response.token, "realtime-test-secret", algorithms=["HS256"])

    assert response.expires_in == 55 * 60
    assert claims["sub"] == "42"
    assert claims["app_user_id"] == 42
    assert claims["role"] == "authenticated"
    assert claims["exp"] - claims["iat"] == response.expires_in


@pytest.mark.asyncio
async def test_realtime_token_fails_closed_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(realtime.settings, "supabase_url", "")
    monkeypatch.setattr(realtime.settings, "supabase_anon_key", "")
    monkeypatch.setattr(realtime.settings, "supabase_jwt_secret", "")

    with pytest.raises(HTTPException) as error:
        await realtime.get_realtime_token(SimpleNamespace(id=42))

    assert getattr(error.value, "status_code", None) == 503
