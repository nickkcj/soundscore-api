"""Direct message router for 1:1 conversations."""

import json
import uuid as uuid_module

from fastapi import APIRouter, Query, HTTPException, UploadFile, File
from sqlalchemy import select, func, or_, and_, case
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.direct_message import Conversation, DirectMessage
from app.models.group import Group, GroupMember, GroupMessage
from app.models.review import Review
from app.schemas.direct_message import (
    ConversationResponse,
    ConversationListResponse,
    DirectMessageResponse,
    MessageListResponse,
    SendMessageRequest,
    ShareReviewRequest,
    OtherUser,
)
from app.core.exceptions import NotFoundException, ForbiddenException, BadRequestException
from app.dependencies import CurrentUser, DbSession
from app.services.storage_service import StorageService
from app.config import get_settings

router = APIRouter()


def _get_ordered_ids(user1_id: int, user2_id: int) -> tuple[int, int]:
    """Return user IDs in ascending order for consistent conversation lookup."""
    return (min(user1_id, user2_id), max(user1_id, user2_id))


# ============== Conversations ==============

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List conversations",
)
async def list_conversations(
    current_user: CurrentUser,
    db: DbSession,
):
    """List all conversations for the current user, ordered by most recent message."""
    # Get conversations where user is participant
    conversations_result = await db.execute(
        select(Conversation)
        .where(
            or_(
                Conversation.user1_id == current_user.id,
                Conversation.user2_id == current_user.id,
            )
        )
        .order_by(Conversation.updated_at.desc())
    )
    conversations = conversations_result.scalars().all()

    if not conversations:
        return ConversationListResponse(conversations=[], total=0)

    response_list = []
    for conv in conversations:
        # Determine the other user
        other_user_id = conv.user2_id if conv.user1_id == current_user.id else conv.user1_id

        # Get other user info
        user_result = await db.execute(
            select(User).where(User.id == other_user_id)
        )
        other_user = user_result.scalar_one_or_none()
        if not other_user:
            continue

        profile_picture = await StorageService.resolve_profile_picture(other_user.profile_picture)

        # Get last message
        last_msg_result = await db.execute(
            select(DirectMessage)
            .where(DirectMessage.conversation_id == conv.id)
            .order_by(DirectMessage.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()

        last_message = None
        if last_msg:
            sender_result = await db.execute(
                select(User).where(User.id == last_msg.sender_id)
            )
            sender = sender_result.scalar_one_or_none()
            sender_pp = await StorageService.resolve_profile_picture(
                sender.profile_picture if sender else None
            )
            last_message = DirectMessageResponse(
                id=last_msg.id,
                conversation_id=last_msg.conversation_id,
                sender_id=last_msg.sender_id,
                sender_username=sender.username if sender else "Unknown",
                sender_profile_picture=sender_pp,
                content=last_msg.content,
                image_url=last_msg.image_url,
                is_read=last_msg.is_read,
                created_at=last_msg.created_at,
            )

        # Get unread count
        unread_result = await db.execute(
            select(func.count(DirectMessage.id))
            .where(
                DirectMessage.conversation_id == conv.id,
                DirectMessage.sender_id != current_user.id,
                DirectMessage.is_read == False,
            )
        )
        unread_count = unread_result.scalar() or 0

        response_list.append(
            ConversationResponse(
                id=conv.id,
                other_user=OtherUser(
                    id=other_user.id,
                    username=other_user.username,
                    profile_picture=profile_picture,
                ),
                last_message=last_message,
                unread_count=unread_count,
                updated_at=conv.updated_at,
            )
        )

    return ConversationListResponse(
        conversations=response_list,
        total=len(response_list),
    )


@router.post(
    "/conversations/{username}",
    response_model=ConversationResponse,
    summary="Start or get conversation",
)
async def start_conversation(
    username: str,
    current_user: CurrentUser,
    db: DbSession,
):
    """Start a new conversation with a user, or return existing one."""
    # Find the other user
    user_result = await db.execute(
        select(User).where(User.username == username)
    )
    other_user = user_result.scalar_one_or_none()
    if not other_user:
        raise NotFoundException("User not found")

    if other_user.id == current_user.id:
        raise BadRequestException("Cannot message yourself")

    # Check for existing conversation (IDs always stored in ascending order)
    u1, u2 = _get_ordered_ids(current_user.id, other_user.id)

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.user1_id == u1,
            Conversation.user2_id == u2,
        )
    )
    conv = conv_result.scalar_one_or_none()

    if not conv:
        conv = Conversation(user1_id=u1, user2_id=u2)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

    profile_picture = await StorageService.resolve_profile_picture(other_user.profile_picture)

    return ConversationResponse(
        id=conv.id,
        other_user=OtherUser(
            id=other_user.id,
            username=other_user.username,
            profile_picture=profile_picture,
        ),
        last_message=None,
        unread_count=0,
        updated_at=conv.updated_at,
    )


# ============== Messages ==============

@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="Get messages",
)
async def get_messages(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    """Get paginated messages for a conversation."""
    # Verify participant
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation not found")

    if current_user.id not in (conv.user1_id, conv.user2_id):
        raise ForbiddenException("Not a participant of this conversation")

    # Total
    total_result = await db.execute(
        select(func.count(DirectMessage.id))
        .where(DirectMessage.conversation_id == conversation_id)
    )
    total = total_result.scalar() or 0

    # Get messages (newest first, then reverse for display)
    offset = (page - 1) * per_page
    result = await db.execute(
        select(DirectMessage)
        .where(DirectMessage.conversation_id == conversation_id)
        .order_by(DirectMessage.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    messages = result.scalars().all()

    # Build responses
    message_responses = []
    for m in reversed(messages):
        sender_result = await db.execute(
            select(User).where(User.id == m.sender_id)
        )
        sender = sender_result.scalar_one_or_none()
        sender_pp = await StorageService.resolve_profile_picture(
            sender.profile_picture if sender else None
        )

        # Resolve image URL
        image_url = None
        if m.image_url:
            image_url = await StorageService.get_signed_url(m.image_url, expires_in=3600)

        message_responses.append(
            DirectMessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                sender_id=m.sender_id,
                sender_username=sender.username if sender else "Unknown",
                sender_profile_picture=sender_pp,
                content=m.content,
                image_url=image_url,
                is_read=m.is_read,
                created_at=m.created_at,
            )
        )

    return MessageListResponse(
        messages=message_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_more=offset + per_page < total,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=DirectMessageResponse,
    status_code=201,
    summary="Send message",
)
async def send_message(
    conversation_id: int,
    body: SendMessageRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """Send a message in a conversation."""
    # Verify participant
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation not found")

    if current_user.id not in (conv.user1_id, conv.user2_id):
        raise ForbiddenException("Not a participant of this conversation")

    # Create message
    message = DirectMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=body.content,
    )
    db.add(message)

    # Update conversation timestamp
    conv.updated_at = func.now()

    await db.commit()
    await db.refresh(message)

    profile_picture = await StorageService.resolve_profile_picture(current_user.profile_picture)

    return DirectMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_id=current_user.id,
        sender_username=current_user.username,
        sender_profile_picture=profile_picture,
        content=message.content,
        image_url=None,
        is_read=False,
        created_at=message.created_at,
    )


@router.post(
    "/conversations/{conversation_id}/messages/image",
    summary="Upload image for DM",
)
async def upload_dm_image(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    """Upload an image to be sent in a DM."""
    settings = get_settings()

    # Verify participant
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation not found")

    if current_user.id not in (conv.user1_id, conv.user2_id):
        raise ForbiddenException("Not a participant of this conversation")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if file.content_type not in allowed_types:
        raise BadRequestException(
            f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    # Validate file size
    contents = await file.read()
    if len(contents) > settings.max_upload_size_bytes:
        raise BadRequestException(
            f"File too large. Maximum size: {settings.max_upload_size_mb}MB"
        )

    try:
        bucket = "dm_images"
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{conversation_id}/{current_user.id}_{uuid_module.uuid4()}.{file_ext}"
        image_path = f"{bucket}/{filename}"

        StorageService.upload_file(image_path, contents, file.content_type)
        signed_url = await StorageService.get_signed_url(image_path, expires_in=86400)

        return {"image_url": signed_url, "image_path": image_path}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )


@router.put(
    "/conversations/{conversation_id}/read",
    summary="Mark conversation as read",
)
async def mark_as_read(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Mark all messages in a conversation as read."""
    # Verify participant
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation not found")

    if current_user.id not in (conv.user1_id, conv.user2_id):
        raise ForbiddenException("Not a participant of this conversation")

    # Mark unread messages from the other user as read
    from sqlalchemy import update
    await db.execute(
        update(DirectMessage)
        .where(
            DirectMessage.conversation_id == conversation_id,
            DirectMessage.sender_id != current_user.id,
            DirectMessage.is_read == False,
        )
        .values(is_read=True)
    )
    await db.commit()

    return {"success": True}


@router.get(
    "/unread-count",
    summary="Get total unread message count",
)
async def get_unread_count(
    current_user: CurrentUser,
    db: DbSession,
):
    """Get total unread messages across all conversations."""
    result = await db.execute(
        select(func.count(DirectMessage.id))
        .join(Conversation, DirectMessage.conversation_id == Conversation.id)
        .where(
            or_(
                Conversation.user1_id == current_user.id,
                Conversation.user2_id == current_user.id,
            ),
            DirectMessage.sender_id != current_user.id,
            DirectMessage.is_read == False,
        )
    )
    count = result.scalar() or 0
    return {"unread_count": count}


# ============== Share Review ==============

@router.post(
    "/share/review/{review_uuid}",
    summary="Share a review via DM or group",
)
async def share_review(
    review_uuid: str,
    body: ShareReviewRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """Share a review link to a user (DM) or group chat."""
    if not body.recipient_username and not body.group_uuid:
        raise BadRequestException("Must specify recipient_username or group_uuid")

    # Verify review exists and load album + user data
    from uuid import UUID
    from app.models.review import Album
    review_result = await db.execute(
        select(Review)
        .options(selectinload(Review.album), selectinload(Review.user))
        .where(Review.uuid == UUID(review_uuid))
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    # Resolve album cover image
    album_cover = review.album.cover_image

    # Build rich share content as JSON
    share_content = json.dumps({
        "type": "review_share",
        "review_uuid": review_uuid,
        "album_title": review.album.title,
        "album_artist": review.album.artist,
        "album_cover": album_cover,
        "album_spotify_id": review.album.spotify_id,
        "rating": review.rating,
        "text": (review.text[:150] + "...") if review.text and len(review.text) > 150 else review.text,
        "username": review.user.username,
        "is_favorite": review.is_favorite,
    })

    if body.recipient_username:
        # Share via DM
        user_result = await db.execute(
            select(User).where(User.username == body.recipient_username)
        )
        recipient = user_result.scalar_one_or_none()
        if not recipient:
            raise NotFoundException("User not found")

        if recipient.id == current_user.id:
            raise BadRequestException("Cannot share with yourself")

        # Get or create conversation
        u1, u2 = _get_ordered_ids(current_user.id, recipient.id)
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user1_id == u1,
                Conversation.user2_id == u2,
            )
        )
        conv = conv_result.scalar_one_or_none()

        if not conv:
            conv = Conversation(user1_id=u1, user2_id=u2)
            db.add(conv)
            await db.flush()

        # Send message
        message = DirectMessage(
            conversation_id=conv.id,
            sender_id=current_user.id,
            content=share_content,
        )
        db.add(message)
        conv.updated_at = func.now()
        await db.commit()

        return {"success": True, "type": "dm", "message": f"Shared with {body.recipient_username}"}

    elif body.group_uuid:
        # Share to group
        from uuid import UUID as UUIDType
        group_result = await db.execute(
            select(Group).where(Group.uuid == UUIDType(body.group_uuid))
        )
        group = group_result.scalar_one_or_none()
        if not group:
            raise NotFoundException("Group not found")

        # Verify membership
        member_result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group.id,
                GroupMember.user_id == current_user.id,
            )
        )
        if not member_result.scalar_one_or_none():
            raise ForbiddenException("Not a member of this group")

        # Send group message
        group_msg = GroupMessage(
            group_id=group.id,
            user_id=current_user.id,
            content=share_content,
        )
        db.add(group_msg)
        await db.commit()

        return {"success": True, "type": "group", "message": f"Shared to group"}
