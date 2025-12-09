import asyncio
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.feed import Notification
from app.models.review import Review, Comment


class NotificationService:
    """Service for creating and managing notifications."""

    # In-memory store for SSE connections (user_id -> list of queues)
    _sse_connections: dict[int, list[asyncio.Queue]] = {}

    @classmethod
    def register_sse_connection(cls, user_id: int) -> asyncio.Queue:
        """Register a new SSE connection for a user."""
        queue: asyncio.Queue = asyncio.Queue()
        if user_id not in cls._sse_connections:
            cls._sse_connections[user_id] = []
        cls._sse_connections[user_id].append(queue)
        return queue

    @classmethod
    def unregister_sse_connection(cls, user_id: int, queue: asyncio.Queue):
        """Unregister an SSE connection."""
        if user_id in cls._sse_connections:
            try:
                cls._sse_connections[user_id].remove(queue)
                if not cls._sse_connections[user_id]:
                    del cls._sse_connections[user_id]
            except ValueError:
                pass

    @classmethod
    async def push_notification(cls, user_id: int, notification_data: dict):
        """Push a notification to all SSE connections for a user."""
        if user_id in cls._sse_connections:
            for queue in cls._sse_connections[user_id]:
                await queue.put(notification_data)

    @staticmethod
    async def create_notification(
        db: AsyncSession,
        recipient_id: int,
        actor_id: int,
        notification_type: str,
        message: str,
        review_id: Optional[int] = None,
        comment_id: Optional[int] = None,
    ) -> Notification:
        """
        Create a new notification.

        Args:
            db: Database session
            recipient_id: User receiving the notification
            actor_id: User who triggered the notification
            notification_type: Type of notification (like, comment, follow, review)
            message: Notification message
            review_id: Related review ID (optional)
            comment_id: Related comment ID (optional)

        Returns:
            Created notification
        """
        # Don't notify yourself
        if recipient_id == actor_id:
            return None

        notification = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            notification_type=notification_type,
            message=message,
            review_id=review_id,
            comment_id=comment_id,
        )
        db.add(notification)
        await db.flush()
        await db.refresh(notification)

        # Get actor info for SSE push
        actor_result = await db.execute(
            select(User).where(User.id == actor_id)
        )
        actor = actor_result.scalar_one()

        # Push to SSE connections
        notification_data = {
            "id": notification.id,
            "notification_type": notification_type,
            "message": message,
            "is_read": False,
            "created_at": notification.created_at.isoformat(),
            "actor_id": actor_id,
            "actor_username": actor.username,
            "actor_profile_picture": actor.profile_picture,
            "review_id": review_id,
            "comment_id": comment_id,
        }
        await NotificationService.push_notification(recipient_id, notification_data)

        return notification

    @staticmethod
    async def create_like_notification(
        db: AsyncSession,
        actor: User,
        review: Review,
    ):
        """Create notification when someone likes a review."""
        message = f"{actor.username} liked your review"
        await NotificationService.create_notification(
            db=db,
            recipient_id=review.user_id,
            actor_id=actor.id,
            notification_type="like",
            message=message,
            review_id=review.id,
        )

    @staticmethod
    async def create_comment_notification(
        db: AsyncSession,
        actor: User,
        review: Review,
        comment: Comment,
    ):
        """Create notification when someone comments on a review."""
        message = f"{actor.username} commented on your review"
        await NotificationService.create_notification(
            db=db,
            recipient_id=review.user_id,
            actor_id=actor.id,
            notification_type="comment",
            message=message,
            review_id=review.id,
            comment_id=comment.id,
        )

    @staticmethod
    async def create_reply_notification(
        db: AsyncSession,
        actor: User,
        parent_comment: Comment,
        reply: Comment,
    ):
        """Create notification when someone replies to a comment."""
        message = f"{actor.username} replied to your comment"
        await NotificationService.create_notification(
            db=db,
            recipient_id=parent_comment.user_id,
            actor_id=actor.id,
            notification_type="comment",
            message=message,
            review_id=parent_comment.review_id,
            comment_id=reply.id,
        )

    @staticmethod
    async def create_follow_notification(
        db: AsyncSession,
        actor: User,
        recipient_id: int,
    ):
        """Create notification when someone follows a user."""
        message = f"{actor.username} started following you"
        await NotificationService.create_notification(
            db=db,
            recipient_id=recipient_id,
            actor_id=actor.id,
            notification_type="follow",
            message=message,
        )


notification_service = NotificationService()
