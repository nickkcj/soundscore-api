"""
Batch query utilities to avoid N+1 query problems.
"""
import asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Review, ReviewLike, Comment, Album
from app.schemas.review import ReviewResponse, AlbumResponse
from app.services.storage_service import StorageService


async def batch_load_review_stats(
    review_ids: list[int],
    db: AsyncSession,
    current_user_id: int | None = None
) -> dict:
    """
    Load likes, comments counts and user likes for multiple reviews in batch.

    Instead of 3 queries per review (N+1 problem), this does 3 queries total.

    Args:
        review_ids: List of review IDs to load stats for
        db: Database session
        current_user_id: Optional current user ID to check if they liked

    Returns:
        Dict with 'likes', 'comments', and 'user_liked' mappings
    """
    if not review_ids:
        return {"likes": {}, "comments": {}, "user_liked": set()}

    # Query 1: Like counts per review
    like_counts_result = await db.execute(
        select(ReviewLike.review_id, func.count(ReviewLike.id))
        .where(ReviewLike.review_id.in_(review_ids))
        .group_by(ReviewLike.review_id)
    )
    likes_map = dict(like_counts_result.all())

    # Query 2: Comment counts per review
    comment_counts_result = await db.execute(
        select(Comment.review_id, func.count(Comment.id))
        .where(Comment.review_id.in_(review_ids))
        .group_by(Comment.review_id)
    )
    comments_map = dict(comment_counts_result.all())

    # Query 3: Which reviews the current user liked
    user_liked: set[int] = set()
    if current_user_id:
        liked_result = await db.execute(
            select(ReviewLike.review_id)
            .where(
                ReviewLike.review_id.in_(review_ids),
                ReviewLike.user_id == current_user_id
            )
        )
        user_liked = {row[0] for row in liked_result.all()}

    return {
        "likes": likes_map,
        "comments": comments_map,
        "user_liked": user_liked,
    }


async def build_review_responses_batch(
    reviews: list[Review],
    db: AsyncSession,
    current_user_id: int | None = None
) -> list[ReviewResponse]:
    """
    Build ReviewResponse objects for multiple reviews efficiently.

    Uses batch queries for stats and parallel profile picture resolution.

    Args:
        reviews: List of Review objects with user and album loaded
        db: Database session
        current_user_id: Optional current user ID

    Returns:
        List of ReviewResponse objects
    """
    if not reviews:
        return []

    review_ids = [r.id for r in reviews]

    # Batch load all stats in 3 queries total
    stats = await batch_load_review_stats(review_ids, db, current_user_id)

    # Parallel profile picture resolution
    profile_urls = await asyncio.gather(*[
        StorageService.resolve_profile_picture(r.user.profile_picture)
        for r in reviews
    ])

    # Build responses
    responses = []
    for review, profile_url in zip(reviews, profile_urls):
        responses.append(
            ReviewResponse(
                id=review.id,
                uuid=review.uuid,
                rating=review.rating,
                text=review.text,
                is_favorite=review.is_favorite,
                created_at=review.created_at,
                updated_at=review.updated_at,
                album=AlbumResponse(
                    id=review.album.id,
                    spotify_id=review.album.spotify_id,
                    title=review.album.title,
                    artist=review.album.artist,
                    cover_image=review.album.cover_image,
                    release_date=review.album.release_date,
                ),
                user_id=review.user.id,
                username=review.user.username,
                user_profile_picture=profile_url,
                like_count=stats["likes"].get(review.id, 0),
                comment_count=stats["comments"].get(review.id, 0),
                is_liked=review.id in stats["user_liked"] if current_user_id else None,
            )
        )

    return responses
