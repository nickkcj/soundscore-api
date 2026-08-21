import pytest
from pydantic import ValidationError

from app.schemas.direct_message import SendMessageRequest
from app.schemas.group import GroupMessageCreate


def test_direct_message_accepts_text_only() -> None:
    request = SendMessageRequest(content="Hello", client_id="2f8378fd-43b7-41e4-9f28-f2d8df6999e4")

    assert request.content == "Hello"
    assert request.image_path is None
    assert request.client_id == "2f8378fd-43b7-41e4-9f28-f2d8df6999e4"


def test_direct_message_accepts_image_only() -> None:
    request = SendMessageRequest(image_path="dm_images/12/4_image.jpg")

    assert request.content == ""
    assert request.image_path == "dm_images/12/4_image.jpg"


def test_direct_message_rejects_oversized_content() -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest(content="x" * 5001)


def test_direct_message_keeps_legacy_image_url_field() -> None:
    request = SendMessageRequest(image_url="dm_images/12/4_image.jpg")

    assert request.image_url == "dm_images/12/4_image.jpg"


def test_group_message_accepts_canonical_image_path() -> None:
    request = GroupMessageCreate(image_path="group_message_images/8/4_image.jpg", client_id="message-42")

    assert request.image_path == "group_message_images/8/4_image.jpg"
    assert request.client_id == "message-42"


def test_chat_message_rejects_unsafe_client_id() -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest(content="Hello", client_id="../../duplicate")


def test_group_message_keeps_legacy_image_url_field() -> None:
    request = GroupMessageCreate(image_url="group_message_images/8/4_image.jpg")

    assert request.image_url == "group_message_images/8/4_image.jpg"
