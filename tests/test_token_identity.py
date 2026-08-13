from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_token_contains_stable_user_identity() -> None:
    payload = decode_token(create_access_token("old_name", user_id=42))

    assert payload is not None
    assert payload["sub"] == "old_name"
    assert payload["user_id"] == 42
    assert payload["type"] == "access"


def test_refresh_token_contains_stable_user_identity() -> None:
    payload = decode_token(create_refresh_token("old_name", user_id=42))

    assert payload is not None
    assert payload["sub"] == "old_name"
    assert payload["user_id"] == 42
    assert payload["type"] == "refresh"


def test_legacy_tokens_without_user_id_remain_valid() -> None:
    payload = decode_token(create_access_token("listener"))

    assert payload is not None
    assert payload["sub"] == "listener"
    assert "user_id" not in payload
