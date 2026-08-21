import pytest
from pydantic import ValidationError

from app.schemas.push import PushDeviceRequest
from app.services.push_service import PushService


def test_push_device_accepts_an_expo_android_token() -> None:
    request = PushDeviceRequest(
        token="ExponentPushToken[android-installation-token]",
        platform="android",
    )

    assert request.platform == "android"
    assert request.token.startswith("ExponentPushToken[")


def test_push_device_rejects_an_arbitrary_endpoint() -> None:
    with pytest.raises(ValidationError):
        PushDeviceRequest(token="https://example.com/callback", platform="android")


def test_remote_push_payload_is_deliberately_generic() -> None:
    payload = PushService._payload(
        "ExponentPushToken[android-installation-token]",
        "/messages",
    )

    assert payload == {
        "to": "ExponentPushToken[android-installation-token]",
        "title": "SoundScore",
        "body": "You have new activity.",
        "data": {"url": "/messages"},
        "sound": "default",
        "channelId": "social",
    }
