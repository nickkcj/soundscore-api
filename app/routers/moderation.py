"""Community safety endpoints. Reports are only exposed to superusers."""
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, or_, func
from sqlalchemy.dialects.postgresql import insert
from app.dependencies import CurrentUser, DbSession
from app.models.user import User, UserFollow
from app.models.review import Review, Comment
from app.models.group import Group, GroupMember, GroupMessage
from app.models.direct_message import DirectMessage, Conversation
from app.models.moderation import ContentReport, UserBlock, TermsAcceptance
from app.services.moderation_service import TERMS_VERSION
from app.services.cache_service import CacheService

router = APIRouter()


class TermsInput(BaseModel):
    version: Literal["2026-10-03"]


class ReportInput(BaseModel):
    target_type: Literal["user", "review", "comment", "group", "group_message", "direct_message"]
    target_id: str = Field(min_length=1, max_length=64)
    reason: Literal["harassment", "hate", "sexual", "violence", "spam", "privacy", "other"]
    details: str | None = Field(default=None, max_length=2000)


class ResolutionInput(BaseModel):
    action: Literal["dismiss", "remove", "suspend"]
    note: str = Field(min_length=3, max_length=2000)


@router.get("/terms")
async def terms_status(current_user: CurrentUser, db: DbSession):
    acceptance = await db.get(TermsAcceptance, (current_user.id, TERMS_VERSION))
    return {"version": TERMS_VERSION, "accepted": acceptance is not None}


@router.post("/terms")
async def accept_terms(body: TermsInput, current_user: CurrentUser, db: DbSession):
    await db.execute(insert(TermsAcceptance).values(user_id=current_user.id, version=body.version).on_conflict_do_nothing())
    await db.commit()
    return {"version": TERMS_VERSION, "accepted": True}


@router.get("/blocks")
async def list_blocks(current_user: CurrentUser, db: DbSession):
    users = (await db.scalars(select(User).join(UserBlock, UserBlock.blocked_id == User.id)
                             .where(UserBlock.blocker_id == current_user.id).order_by(User.username))).all()
    return {"users": [{"id": u.id, "username": u.username} for u in users]}


async def target_user(username, db):
    user = await db.scalar(select(User).where(User.username == username.lower()))
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.put("/blocks/{username}")
async def block_user(username: str, current_user: CurrentUser, db: DbSession):
    other = await target_user(username, db)
    if other.id == current_user.id:
        raise HTTPException(400, "Cannot block yourself")
    await db.execute(insert(UserBlock).values(blocker_id=current_user.id, blocked_id=other.id).on_conflict_do_nothing())
    await db.execute(delete(UserFollow).where(or_(
        (UserFollow.follower_id == current_user.id) & (UserFollow.following_id == other.id),
        (UserFollow.follower_id == other.id) & (UserFollow.following_id == current_user.id),
    )))
    await db.commit()
    await CacheService.delete_pattern(f"feed:user:{current_user.id}:*")
    await CacheService.delete_pattern(f"feed:user:{other.id}:*")
    return {"blocked": True}


@router.delete("/blocks/{username}")
async def unblock_user(username: str, current_user: CurrentUser, db: DbSession):
    other = await target_user(username, db)
    await db.execute(delete(UserBlock).where(UserBlock.blocker_id == current_user.id, UserBlock.blocked_id == other.id))
    await db.commit()
    await CacheService.delete_pattern(f"feed:user:{current_user.id}:*")
    await CacheService.delete_pattern(f"feed:user:{other.id}:*")
    return {"blocked": False}


async def report_target(body, current_user, db):
    models = {"user": User, "review": Review, "comment": Comment, "group": Group,
              "group_message": GroupMessage, "direct_message": DirectMessage}
    model = models[body.target_type]
    try:
        key = UUID(body.target_id) if body.target_type in ("review", "group") else int(body.target_id)
    except ValueError:
        raise HTTPException(422, "Invalid content identifier")
    column = model.uuid if body.target_type in ("review", "group") else model.id
    target = await db.scalar(select(model).where(column == key))
    if not target:
        raise HTTPException(404, "Content not found")
    if body.target_type == "direct_message":
        conversation = await db.get(Conversation, target.conversation_id)
        if not conversation or current_user.id not in (conversation.user1_id, conversation.user2_id):
            raise HTTPException(404, "Content not found")
    if body.target_type in ("group", "group_message"):
        group = target if body.target_type == "group" else await db.get(Group, target.group_id)
        if body.target_type == "group_message" or group.privacy != "public":
            member = await db.scalar(select(GroupMember.id).where(GroupMember.group_id == group.id, GroupMember.user_id == current_user.id))
            if member is None:
                raise HTTPException(404, "Content not found")
    owner_id = target.id if body.target_type == "user" else getattr(target, "user_id", getattr(target, "sender_id", getattr(target, "created_by_id", None)))
    if owner_id == current_user.id:
        raise HTTPException(400, "Cannot report your own content")
    snapshot = {"owner_id": owner_id}
    for name in ("username", "bio", "text", "content", "name", "description", "image_url"):
        if hasattr(target, name):
            snapshot[name] = getattr(target, name)
    return target, snapshot


@router.post("/reports", status_code=201)
async def create_report(body: ReportInput, current_user: CurrentUser, db: DbSession):
    target, snapshot = await report_target(body, current_user, db)
    target_id = str(target.uuid if body.target_type in ("review", "group") else target.id)
    recent = await db.scalar(select(func.count()).select_from(ContentReport).where(
        ContentReport.reporter_id == current_user.id,
        ContentReport.created_at > datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)))
    if recent >= 30:
        raise HTTPException(429, "Daily report limit reached")
    await db.execute(insert(ContentReport).values(reporter_id=current_user.id, target_type=body.target_type,
        target_id=target_id, reason=body.reason, details=body.details,
        snapshot=json.dumps(snapshot, ensure_ascii=False), status="pending").on_conflict_do_nothing())
    await db.commit()
    return {"message": "Report received"}


def require_admin(user):
    if not user.is_superuser:
        raise HTTPException(403, "Moderator access required")


@router.get("/reports")
async def list_reports(current_user: CurrentUser, db: DbSession, status: Literal["pending", "resolved"] = "pending", limit: int = Query(50, ge=1, le=100)):
    require_admin(current_user)
    reports = (await db.scalars(select(ContentReport).where(ContentReport.status == status).order_by(ContentReport.created_at).limit(limit))).all()
    return {"reports": [{"id": r.id, "target_type": r.target_type, "target_id": r.target_id,
        "reason": r.reason, "details": r.details, "snapshot": json.loads(r.snapshot),
        "created_at": r.created_at, "resolution": r.resolution} for r in reports]}


@router.post("/reports/{report_id}/resolve")
async def resolve_report(report_id: int, body: ResolutionInput, current_user: CurrentUser, db: DbSession):
    require_admin(current_user)
    report = await db.get(ContentReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status != "pending":
        raise HTTPException(409, "Report already resolved")
    if body.action == "remove":
        if report.target_type == "user":
            raise HTTPException(400, "Use suspend for user reports")
        models = {"review": Review, "comment": Comment, "group": Group, "group_message": GroupMessage, "direct_message": DirectMessage}
        model = models[report.target_type]
        key = UUID(report.target_id) if report.target_type in ("review", "group") else int(report.target_id)
        column = model.uuid if report.target_type in ("review", "group") else model.id
        target = await db.scalar(select(model).where(column == key))
        if target:
            await db.delete(target)
    elif body.action == "suspend":
        owner_id = json.loads(report.snapshot).get("owner_id")
        user = await db.get(User, owner_id) if owner_id else None
        if user and user.is_superuser:
            raise HTTPException(400, "Cannot suspend a moderator")
        if user:
            user.is_active = False
    report.status = "resolved"
    report.resolution = f"{body.action}: {body.note}"
    report.resolved_by = current_user.id
    report.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await CacheService.delete_pattern("feed:*")
    return {"message": "Report resolved"}
