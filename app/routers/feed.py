import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.models.user import User, UserFollow
from app.models.review import Review, ReviewLike, Comment, Album
from app.models.feed import Notification
from app.schemas.feed import (
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
    MarkReadResponse,
    FeedResponse,
)
from app.schemas.review import ReviewResponse, AlbumResponse
from app.core.exceptions import NotFoundException
from app.dependencies import CurrentUser, DbSession, QueryTokenUser
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService
from app.utils.batch_queries import build_review_responses_batch

router = APIRouter()


# ============== Social Feed ==============

@router.get(
    "",
    response_model=FeedResponse,
    summary="Get social feed",
)
async def get_feed(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort: str = Query("desc", regex="^(asc|desc)$", description="Sort order: 'desc' for latest first, 'asc' for oldest first"),
):
    """
    Get personalized social feed.

    Shows reviews from users you follow, ordered by most recent.
    If you don't follow anyone, shows latest reviews from all users.
    """
    # Get IDs of users the current user follows
    following_result = await db.execute(
        select(UserFollow.following_id).where(UserFollow.follower_id == current_user.id)
    )
    following_ids = [row[0] for row in following_result.all()]

    # Build query - show reviews from followed users, or all if not following anyone
    if following_ids:
        # Include own reviews too
        following_ids.append(current_user.id)
        query = select(Review).where(Review.user_id.in_(following_ids))
        count_query = select(func.count()).select_from(Review).where(Review.user_id.in_(following_ids))
    else:
        # Show all reviews if not following anyone
        query = select(Review)
        count_query = select(func.count()).select_from(Review)

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Determine sort order
    order_clause = Review.created_at.desc() if sort == "desc" else Review.created_at.asc()

    # Get paginated reviews
    offset = (page - 1) * per_page
    result = await db.execute(
        query
        .options(selectinload(Review.user), selectinload(Review.album))
        .order_by(order_clause)
        .offset(offset)
        .limit(per_page)
    )
    reviews = result.scalars().all()

    # Build responses using batch queries (avoids N+1)
    review_responses = await build_review_responses_batch(reviews, db, current_user.id)

    return FeedResponse(
        reviews=review_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


# ============== Notifications ==============

@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="Get notifications",
)
async def get_notifications(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False, description="Only show unread notifications"),
):
    """Get user's notifications."""
    # Build query
    query = select(Notification).where(Notification.recipient_id == current_user.id)
    count_query = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == current_user.id
    )

    if unread_only:
        query = query.where(Notification.is_read == False)
        count_query = count_query.where(Notification.is_read == False)

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get unread count
    unread_result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False
        )
    )
    unread_count = unread_result.scalar() or 0

    # Get paginated notifications
    offset = (page - 1) * per_page
    result = await db.execute(
        query
        .options(selectinload(Notification.actor))
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    notifications = result.scalars().all()

    # Parallel profile picture resolution
    profile_urls = await asyncio.gather(*[
        StorageService.resolve_profile_picture(n.actor.profile_picture)
        for n in notifications
    ])

    # Build responses
    notification_responses = [
        NotificationResponse(
            id=n.id,
            notification_type=n.notification_type,
            message=n.message,
            is_read=n.is_read,
            created_at=n.created_at,
            actor_id=n.actor.id,
            actor_username=n.actor.username,
            actor_profile_picture=profile_url,
            review_id=n.review_id,
            comment_id=n.comment_id,
        )
        for n, profile_url in zip(notifications, profile_urls)
    ]

    return NotificationListResponse(
        notifications=notification_responses,
        unread_count=unread_count,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
    )


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountResponse,
    summary="Get unread notification count",
)
async def get_unread_count(current_user: CurrentUser, db: DbSession):
    """Get count of unread notifications."""
    result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False
        )
    )
    unread_count = result.scalar() or 0

    return UnreadCountResponse(unread_count=unread_count)


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="Mark notification as read",
)
async def mark_notification_read(
    notification_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Mark a single notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise NotFoundException("Notification not found")

    notification.is_read = True
    await db.commit()

    return MarkReadResponse(success=True, message="Notification marked as read")


@router.post(
    "/notifications/read-all",
    response_model=MarkReadResponse,
    summary="Mark all notifications as read",
)
async def mark_all_notifications_read(current_user: CurrentUser, db: DbSession):
    """Mark all notifications as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False
        )
    )
    notifications = result.scalars().all()

    for notification in notifications:
        notification.is_read = True

    await db.commit()

    return MarkReadResponse(
        success=True,
        message=f"Marked {len(notifications)} notifications as read"
    )


# ============== Server-Sent Events (SSE) ==============

async def notification_event_generator(
    user_id: int,
    queue: asyncio.Queue
) -> AsyncGenerator[str, None]:
    """Generate SSE events for notifications."""
    try:
        while True:
            try:
                # Wait for notification with timeout (for keepalive)
                notification_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"event: notification\ndata: {json.dumps(notification_data)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive ping
                yield f"event: ping\ndata: {{}}\n\n"
    except asyncio.CancelledError:
        pass


@router.get(
    "/notifications/stream",
    summary="SSE stream for real-time notifications",
)
async def notification_stream(current_user: QueryTokenUser):
    """
    Server-Sent Events stream for real-time notifications.

    Connect to this endpoint to receive notifications in real-time.

    Example JavaScript:
    ```javascript
    const eventSource = new EventSource('/api/v1/feed/notifications/stream', {
        headers: { 'Authorization': 'Bearer <token>' }
    });

    eventSource.addEventListener('notification', (event) => {
        const notification = JSON.parse(event.data);
        console.log('New notification:', notification);
    });

    eventSource.addEventListener('ping', () => {
        console.log('Keepalive ping');
    });
    ```
    """
    queue = NotificationService.register_sse_connection(current_user.id)

    async def cleanup():
        NotificationService.unregister_sse_connection(current_user.id, queue)

    return StreamingResponse(
        notification_event_generator(current_user.id, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
        background=cleanup,
    )
