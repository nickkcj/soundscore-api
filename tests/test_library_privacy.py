from types import SimpleNamespace

import pytest

from app.core.exceptions import ForbiddenException
from app.routers.library import ensure_library_access
from app.schemas.user import UserProfileResponse


def user(user_id: int, *, library_public: bool) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, library_public=library_public)


def test_public_library_allows_anonymous_access() -> None:
    ensure_library_access(user(1, library_public=True), None)


def test_private_library_allows_its_owner() -> None:
    owner = user(1, library_public=False)
    ensure_library_access(owner, owner)


def test_private_library_rejects_other_users() -> None:
    with pytest.raises(ForbiddenException) as error:
        ensure_library_access(
            user(1, library_public=False),
            user(2, library_public=True),
        )

    assert error.value.status_code == 403
    assert error.value.detail == "This library is private"


def test_profile_response_preserves_private_library_setting() -> None:
    response = UserProfileResponse(
        id=1,
        username="listener",
        email="listener@example.com",
        created_at="2026-08-13T00:00:00Z",
        library_public=False,
    )

    assert response.library_public is False


def test_public_profile_can_omit_private_email() -> None:
    response = UserProfileResponse(
        id=1,
        username="listener",
        created_at="2026-08-13T00:00:00Z",
        library_public=True,
    )

    assert "email" not in response.model_dump(exclude_none=True)
