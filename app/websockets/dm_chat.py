"""WebSocket handler for direct message conversations."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.direct_message import Conversation, DirectMessage
from app.core.security import verify_access_token
from app.websockets.manager import ConnectionManager
from app.services.storage_service import StorageService

router = APIRouter()

# Separate manager for DM connections (avoids ID collision with group manager)
dm_manager = ConnectionManager()


async def get_user_from_token(token: str) -> User | None:
    """Validate JWT token and return user."""
    username = verify_access_token(token)
    if not username:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()


async def verify_conversation_participant(user_id: int, conversation_id: int) -> bool:
    """Check if user is a participant of the conversation."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        return user_id in (conv.user1_id, conv.user2_id)


async def save_dm_message(conversation_id: int, sender_id: int, content: str, image_url: str | None = None) -> DirectMessage:
    """Save a direct message to the database."""
    async with AsyncSessionLocal() as db:
        message = DirectMessage(
            conversation_id=conversation_id,
            sender_id=sender_id,
            content=content,
            image_url=image_url,
        )
        db.add(message)

        # Update conversation timestamp
        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(timezone.utc))
        )

        await db.commit()
        await db.refresh(message)
        return message


async def mark_messages_read(conversation_id: int, reader_id: int):
    """Mark all messages from the other user as read."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(DirectMessage)
            .where(
                DirectMessage.conversation_id == conversation_id,
                DirectMessage.sender_id != reader_id,
                DirectMessage.is_read == False,
            )
            .values(is_read=True)
        )
        await db.commit()


async def get_fresh_user_data(user_id: int) -> dict | None:
    """Get fresh user data with resolved profile picture."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            profile_picture = await StorageService.resolve_profile_picture(user.profile_picture)
            return {
                "id": user.id,
                "username": user.username,
                "profile_picture": profile_picture,
            }
        return None


@router.websocket("/ws/dm/{conversation_id}")
async def dm_websocket(
    websocket: WebSocket,
    conversation_id: int,
    token: str = Query(...),
):
    """
    WebSocket endpoint for direct messages.

    Connect with: ws://host/ws/dm/{conversation_id}?token=<jwt_token>

    Message formats:

    Incoming (client -> server):
    {"type": "message", "content": "Hello!"}
    {"type": "typing"}
    {"type": "read"}
    {"type": "ping"}

    Outgoing (server -> client):
    {"type": "message", "content": "Hello!", "sender_id": 1, "username": "john",
     "profile_picture": "...", "message_id": 123, "timestamp": "..."}
    {"type": "typing", "user_id": 1, "username": "john"}
    {"type": "read"}
    {"type": "pong"}
    """
    # Authenticate
    user = await get_user_from_token(token)
    if not user:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Verify participation
    is_participant = await verify_conversation_participant(user.id, conversation_id)
    if not is_participant:
        await websocket.accept()
        await websocket.close(code=4003, reason="Not a participant of this conversation")
        return

    # Accept and register
    await websocket.accept()
    await dm_manager.connect(websocket, conversation_id, user.id)

    # Mark existing messages as read
    await mark_messages_read(conversation_id, user.id)

    try:
        while True:
            data = await websocket.receive_text()

            try:
                message_data = json.loads(data)
                message_type = message_data.get("type", "message")

                if message_type == "message":
                    content = message_data.get("content", "").strip()
                    image_url = message_data.get("image_url")

                    if not content and not image_url:
                        continue

                    # Save to DB
                    saved_message = await save_dm_message(
                        conversation_id, user.id, content, image_url
                    )

                    # Get fresh user data
                    fresh_user = await get_fresh_user_data(user.id)
                    username = fresh_user["username"] if fresh_user else user.username
                    profile_picture = fresh_user["profile_picture"] if fresh_user else None

                    # Resolve image URL
                    resolved_image_url = image_url
                    if image_url and not image_url.startswith("http"):
                        resolved_image_url = await StorageService.get_signed_url(
                            image_url, expires_in=86400
                        )

                    # Broadcast to both users in conversation
                    await dm_manager.broadcast_to_group(
                        conversation_id,
                        {
                            "type": "message",
                            "content": content,
                            "image_url": resolved_image_url,
                            "sender_id": user.id,
                            "username": username,
                            "profile_picture": profile_picture,
                            "message_id": saved_message.id,
                            "timestamp": saved_message.created_at.isoformat(),
                        },
                    )

                elif message_type == "typing":
                    await dm_manager.broadcast_to_group(
                        conversation_id,
                        {
                            "type": "typing",
                            "user_id": user.id,
                            "username": user.username,
                        },
                        exclude_user_id=user.id,
                    )

                elif message_type == "read":
                    await mark_messages_read(conversation_id, user.id)
                    await dm_manager.broadcast_to_group(
                        conversation_id,
                        {"type": "read", "user_id": user.id},
                        exclude_user_id=user.id,
                    )

                elif message_type == "ping":
                    await dm_manager.send_personal_message(
                        {"type": "pong"},
                        websocket,
                    )

            except json.JSONDecodeError:
                continue

    except WebSocketDisconnect:
        pass
    finally:
        dm_manager.disconnect(conversation_id, user.id)
