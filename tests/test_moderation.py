"""Safety boundaries tested without production accounts or services."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from app.routers.moderation import ReportInput, TermsInput, report_target, require_admin
from app.services.moderation_service import blocked_user_ids, ensure_not_blocked, require_terms


def test_blocks_cover_both_directions():
    sql = str(blocked_user_ids(7).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "user_blocks.blocker_id = 7" in sql
    assert "user_blocks.blocked_id = 7" in sql


@pytest.mark.asyncio
async def test_blocked_interaction_is_rejected():
    db = SimpleNamespace(scalar=AsyncMock(return_value=3))
    with pytest.raises(HTTPException) as error:
        await ensure_not_blocked(db, 7, 3)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_unblocked_interaction_is_allowed():
    await ensure_not_blocked(SimpleNamespace(scalar=AsyncMock(return_value=None)), 7, 3)


@pytest.mark.asyncio
async def test_terms_required_before_publishing():
    with pytest.raises(HTTPException) as error:
        await require_terms(SimpleNamespace(get=AsyncMock(return_value=None)), 7)
    assert error.value.status_code == 403
    await require_terms(SimpleNamespace(get=AsyncMock(return_value=object())), 7)


def test_rejects_obsolete_terms():
    with pytest.raises(ValidationError):
        TermsInput(version="old")


def test_only_moderators_can_read_reports():
    with pytest.raises(HTTPException) as error:
        require_admin(SimpleNamespace(is_superuser=False))
    assert error.value.status_code == 403
    require_admin(SimpleNamespace(is_superuser=True))


@pytest.mark.asyncio
async def test_private_dm_cannot_be_reported_by_an_outsider():
    body = ReportInput(target_type="direct_message", target_id="12", reason="spam")
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(id=12, conversation_id=2)),
                         get=AsyncMock(return_value=SimpleNamespace(user1_id=3, user2_id=4)))
    with pytest.raises(HTTPException) as error:
        await report_target(body, SimpleNamespace(id=7), db)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_own_content_cannot_be_reported():
    body = ReportInput(target_type="comment", target_id="12", reason="spam")
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(id=12, user_id=7, text="hello")))
    with pytest.raises(HTTPException) as error:
        await report_target(body, SimpleNamespace(id=7), db)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_invalid_report_identifier_returns_422():
    with pytest.raises(HTTPException) as error:
        await report_target(ReportInput(target_type="review", target_id="invalid", reason="spam"), SimpleNamespace(id=7), None)
    assert error.value.status_code == 422
