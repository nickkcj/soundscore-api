import pytest
from starlette.requests import Request

from app.core.exceptions import BadRequestException
from app.core.security import create_oauth_link_token
from app.routers.oauth import configure_oauth_client, configure_oauth_link


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
