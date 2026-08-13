import pytest
from pydantic import ValidationError

from app.schemas.auth import PasswordSetRequest
from app.schemas.user import UserUpdate


def test_password_set_requires_a_valid_new_password() -> None:
    request = PasswordSetRequest(new_password="secure-password")

    assert request.new_password == "secure-password"


def test_password_set_rejects_a_short_password() -> None:
    with pytest.raises(ValidationError):
        PasswordSetRequest(new_password="short")


def test_profile_update_distinguishes_clearing_bio_from_omitting_it() -> None:
    cleared = UserUpdate(bio=None)
    omitted = UserUpdate()

    assert "bio" in cleared.model_fields_set
    assert "bio" not in omitted.model_fields_set
