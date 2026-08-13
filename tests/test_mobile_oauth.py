import pytest
from starlette.requests import Request

from app.core.exceptions import BadRequestException
from app.routers.oauth import configure_oauth_client


def request_with_session() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "session": {}})


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "soundscore://oauth/callback",
        "soundscore-dev://oauth/callback",
        "soundscore-preview://oauth/callback",
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
