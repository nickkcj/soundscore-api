from fastapi import HTTPException
from sqlalchemy import select, or_, and_, union
from app.models.moderation import UserBlock, TermsAcceptance

TERMS_VERSION = "2026-10-03"


def blocked_user_ids(user_id: int):
    """Both directions: neither person should interact with the other."""
    return union(
        select(UserBlock.blocked_id).where(UserBlock.blocker_id == user_id),
        select(UserBlock.blocker_id).where(UserBlock.blocked_id == user_id),
    )


async def ensure_not_blocked(db, user_id: int, other_id: int):
    blocked = await db.scalar(select(UserBlock.blocker_id).where(or_(
        and_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == other_id),
        and_(UserBlock.blocker_id == other_id, UserBlock.blocked_id == user_id),
    )).limit(1))
    if blocked is not None:
        raise HTTPException(403, "Interaction unavailable")


async def require_terms(db, user_id: int):
    if await db.get(TermsAcceptance, (user_id, TERMS_VERSION)) is None:
        raise HTTPException(403, "Accept the community terms before publishing")
