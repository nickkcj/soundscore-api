import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.group import Group, GroupMember, GroupMessage
from app.core.security import verify_access_token
from app.websockets.manager import manager
from app.services.storage_service import StorageService

router = APIRouter()


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


async def verify_group_membership(user_id: int, group_id: int) -> bool:
    """Check if user is a member of the group."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none() is not None


async def save_message(group_id: int, user_id: int, content: str) -> GroupMessage:
    """Save a chat message to the database."""
    async with AsyncSessionLocal() as db:
        message = GroupMessage(
            group_id=group_id,
            user_id=user_id,
            content=content,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message


async def get_fresh_user_data(user_id: int) -> dict | None:
    """Get fresh user data from database with resolved profile picture URL."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            # Resolve profile picture to signed URL
            profile_picture_url = await StorageService.resolve_profile_picture(user.profile_picture)
            return {
                "id": user.id,
                "username": user.username,
                "profile_picture": profile_picture_url,
            }
        return None


async def get_online_users_info(group_id: int, online_user_ids: list[int]) -> list[dict]:
    """Get user info for online users with resolved profile picture URLs."""
    if not online_user_ids:
        return []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id.in_(online_user_ids))
        )
        users = result.scalars().all()

        users_info = []
        for user in users:
            profile_picture_url = await StorageService.resolve_profile_picture(user.profile_picture)
            users_info.append({
                "user_id": user.id,
                "username": user.username,
                "profile_picture": profile_picture_url,
            })
        return users_info


@router.websocket("/ws/group/{group_id}")
async def group_chat_websocket(
    websocket: WebSocket,
    group_id: int,
    token: str = Query(...),
):
    """
    WebSocket endpoint for group chat.

    Connect with: ws://host/ws/group/{group_id}?token=<jwt_token>

    Message formats:

    Incoming (client -> server):
    {
        "type": "message",
        "content": "Hello everyone!"
    }

    Outgoing (server -> client):
    {
        "type": "message",
        "content": "Hello everyone!",
        "user_id": 1,
        "username": "john",
        "profile_picture": "https://...",
        "message_id": 123,
        "timestamp": "2024-01-01T12:00:00Z"
    }

    {
        "type": "user_joined",
        "user_id": 1,
        "username": "john",
        "profile_picture": "https://..."
    }

    {
        "type": "user_left",
        "user_id": 1,
        "username": "john"
    }

    {
        "type": "online_users",
        "online_users": [
            {"user_id": 1, "username": "john", "profile_picture": "..."},
            {"user_id": 2, "username": "jane", "profile_picture": "..."}
        ]
    }
    """
    # Authenticate user
    user = await get_user_from_token(token)
    if not user:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Verify group membership
    is_member = await verify_group_membership(user.id, group_id)
    if not is_member:
        await websocket.accept()
        await websocket.close(code=4003, reason="Not a member of this group")
        return

    # Accept connection and register
    await websocket.accept()
    await manager.connect(websocket, group_id, user.id)

    # Resolve profile picture URL for this user
    user_profile_picture = await StorageService.resolve_profile_picture(user.profile_picture)

    try:
        # Notify others that user joined
        await manager.broadcast_to_group(
            group_id,
            {
                "type": "user_joined",
                "user_id": user.id,
                "username": user.username,
                "profile_picture": user_profile_picture,
            },
            exclude_user_id=user.id,
        )

        # Send current online users to the new connection
        online_user_ids = manager.get_online_users(group_id)
        online_users_info = await get_online_users_info(group_id, online_user_ids)
        await manager.send_personal_message(
            {
                "type": "online_users",
                "online_users": online_users_info,
            },
            websocket,
        )

        # Listen for messages
        while True:
            data = await websocket.receive_text()

            try:
                message_data = json.loads(data)
                message_type = message_data.get("type", "message")

                if message_type == "message":
                    content = message_data.get("content", "").strip()
                    if not content:
                        continue

                    # Save message to database
                    saved_message = await save_message(group_id, user.id, content)

                    # Get fresh user data for up-to-date profile picture
                    fresh_user = await get_fresh_user_data(user.id)
                    username = fresh_user["username"] if fresh_user else user.username
                    profile_picture = fresh_user["profile_picture"] if fresh_user else user.profile_picture

                    # Broadcast to all users in the group
                    await manager.broadcast_to_group(
                        group_id,
                        {
                            "type": "message",
                            "content": content,
                            "user_id": user.id,
                            "username": username,
                            "profile_picture": profile_picture,
                            "message_id": saved_message.id,
                            "timestamp": saved_message.created_at.isoformat(),
                        },
                    )

                elif message_type == "typing":
                    # Broadcast typing indicator (excluding sender)
                    await manager.broadcast_to_group(
                        group_id,
                        {
                            "type": "typing",
                            "user_id": user.id,
                            "username": user.username,
                        },
                        exclude_user_id=user.id,
                    )

                elif message_type == "ping":
                    await manager.send_personal_message(
                        {"type": "pong"},
                        websocket,
                    )

            except json.JSONDecodeError:
                # Invalid JSON, ignore
                continue

    except WebSocketDisconnect:
        pass
    finally:
        # Clean up connection
        manager.disconnect(group_id, user.id)

        # Notify others that user left
        await manager.broadcast_to_group(
            group_id,
            {
                "type": "user_left",
                "user_id": user.id,
                "username": user.username,
            },
        )
