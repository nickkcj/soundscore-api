import pytest
from starlette.requests import Request

from app.core.exceptions import BadRequestException
from app.core.security import create_oauth_link_token
from app.routers.oauth import create_auth_redirect, configure_oauth_client, configure_oauth_link, create_mobile_app_bridge


def request_with_session() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "session": {}})


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "soundscore://oauth/callback",
        "soundscore-dev://oauth/callback",
        "soundscore-preview://oauth/callback",
        "https://www.soundscore.com.br/reviews/oauth/callback",
    ],
)
def test_mobile_redirect_accepts_only_app_variants(redirect_uri: str) -> None:
    request = request_with_session()

    configure_oauth_client(request, "mobile", redirect_uri)

    assert request.session["oauth_mobile_redirect_uri"] == redirect_uri


@pytest.mark.parametrize(
    "redirect_uri",
    [
        None,
        "https://evil.example/oauth/callback",
        "https://soundscore.com.br/reviews/oauth/callback",
        "https://www.soundscore.com.br/reviews/another-callback",
        "soundscore://other/callback",
        "soundscore://oauth/callback?code=attacker",
        "soundscore://oauth/callback#fragment",
    ],
)
def test_mobile_redirect_rejects_untrusted_targets(redirect_uri: str | None) -> None:
    request = request_with_session()

    with pytest.raises(BadRequestException):
        configure_oauth_client(request, "mobile", redirect_uri)


def test_web_login_clears_a_stale_mobile_redirect() -> None:
    request = request_with_session()
    request.session["oauth_mobile_redirect_uri"] = "soundscore://oauth/callback"

    configure_oauth_client(request, "web", None)

    assert "oauth_mobile_redirect_uri" not in request.session


def test_link_intent_binds_user_to_matching_provider() -> None:
    request = request_with_session()
    token = create_oauth_link_token(42, "spotify")

    configure_oauth_link(request, "spotify", token)

    assert request.session["oauth_link_user_id"] == 42


def test_link_intent_rejects_a_different_provider() -> None:
    request = request_with_session()
    token = create_oauth_link_token(42, "google")

    with pytest.raises(BadRequestException):
        configure_oauth_link(request, "spotify", token)


def test_login_without_link_token_clears_stale_link_intent() -> None:
    request = request_with_session()
    request.session["oauth_link_user_id"] = 42

    configure_oauth_link(request, "spotify", None)

    assert "oauth_link_user_id" not in request.session


def test_android_bridge_auto_opens_and_offers_a_button() -> None:
    response = create_mobile_app_bridge(
        "soundscore://oauth/callback",
        "code=single-use-code",
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Open SoundScore" in body
    assert "soundscore://oauth/callback?code=single-use-code" in body
    assert "intent://" not in body
    assert "package=br.com.soundscore.app" not in body


def test_android_bridge_supports_the_previous_https_callback() -> None:
    response = create_mobile_app_bridge(
        "https://www.soundscore.com.br/reviews/oauth/callback",
        "code=single-use-code",
    )
    body = response.body.decode()

    assert "Open SoundScore" in body
    assert "soundscore://oauth/callback?code=single-use-code" in body
    assert "intent://" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redirect_uri",
    ["soundscore://oauth/callback", "https://www.soundscore.com.br/reviews/oauth/callback"],
)
async def test_auth_error_uses_android_bridge_for_supported_mobile_callbacks(redirect_uri: str) -> None:
    request = request_with_session()
    request.session["oauth_mobile_redirect_uri"] = redirect_uri

    response = await create_auth_redirect(request, None, None, "Access denied")  # type: ignore[arg-type]
    body = response.body.decode()

    assert response.status_code == 200
    assert "soundscore://oauth/callback?error=Access+denied" in body
