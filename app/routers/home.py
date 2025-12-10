import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.models.user import User
from app.models.review import Album, Review, ReviewLike, Comment
from app.schemas.review import ReviewResponse, AlbumResponse
from app.dependencies import DbSession, OptionalUser
from app.services.storage_service import StorageService

router = APIRouter()


# ============== Schemas ==============

class TopAlbumResponse(BaseModel):
    """Schema for top album response."""
    spotify_id: str
    title: str
    artist: str
    cover_image: str | None = None
    release_date: str | None = None
    avg_rating: float
    review_count: int


class TopAlbumsListResponse(BaseModel):
    """Schema for top albums list response."""
    albums: list[TopAlbumResponse]


class TrendingAlbumResponse(BaseModel):
    """Schema for trending album response."""
    spotify_id: str
    title: str
    artist: str
    cover_image: str | None = None
    release_date: str | None = None
    avg_rating: float | None = None
    review_count: int
    week_start: str  # ISO date string of the week start


class TrendingAlbumsListResponse(BaseModel):
    """Schema for trending albums list response."""
    albums: list[TrendingAlbumResponse]
    week_start: str  # Which week the data is from
    week_end: str


class RecentReviewResponse(BaseModel):
    """Schema for recent review response (simplified for home page)."""
    id: int
    rating: int
    text: str | None
    created_at: str
    album_title: str
    album_artist: str
    album_cover_image: str | None
    album_spotify_id: str
    user_id: int
    username: str
    user_profile_picture: str | None


class RecentReviewsListResponse(BaseModel):
    """Schema for recent reviews list response."""
    reviews: list[RecentReviewResponse]


# ============== Endpoints ==============

@router.get(
    "/top-albums",
    response_model=TopAlbumsListResponse,
    summary="Get top rated albums",
)
async def get_top_albums(
    db: DbSession,
    limit: int = Query(6, ge=1, le=20, description="Number of albums to return"),
):
    """
    Get top rated albums for the home page.

    Ranked by average rating (descending), then by review count (descending).
    Only includes albums with at least 1 review.
    """
    # Query albums with their average rating and review count
    result = await db.execute(
        select(
            Album.spotify_id,
            Album.title,
            Album.artist,
            Album.cover_image,
            Album.release_date,
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.id).label("review_count")
        )
        .join(Review, Review.album_id == Album.id)
        .group_by(Album.id)
        .having(func.count(Review.id) >= 1)
        .order_by(
            func.avg(Review.rating).desc(),
            func.count(Review.id).desc()
        )
        .limit(limit)
    )

    albums = []
    for row in result.all():
        albums.append(TopAlbumResponse(
            spotify_id=row.spotify_id,
            title=row.title,
            artist=row.artist,
            cover_image=row.cover_image,
            release_date=row.release_date,
            avg_rating=round(float(row.avg_rating), 1),
            review_count=row.review_count,
        ))

    return TopAlbumsListResponse(albums=albums)


@router.get(
    "/recent-reviews",
    response_model=RecentReviewsListResponse,
    summary="Get recent reviews",
)
async def get_recent_reviews(
    db: DbSession,
    limit: int = Query(6, ge=1, le=20, description="Number of reviews to return"),
):
    """
    Get most recent reviews for the home page.

    Returns reviews with user and album info, ordered by creation date (newest first).
    """
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.album))
        .order_by(Review.created_at.desc())
        .limit(limit)
    )
    reviews = result.scalars().all()

    # Parallel profile picture resolution
    profile_urls = await asyncio.gather(*[
        StorageService.resolve_profile_picture(r.user.profile_picture)
        for r in reviews
    ])

    review_responses = [
        RecentReviewResponse(
            id=review.id,
            rating=review.rating,
            text=review.text,
            created_at=review.created_at.isoformat(),
            album_title=review.album.title,
            album_artist=review.album.artist,
            album_cover_image=review.album.cover_image,
            album_spotify_id=review.album.spotify_id,
            user_id=review.user.id,
            username=review.user.username,
            user_profile_picture=profile_url,
        )
        for review, profile_url in zip(reviews, profile_urls)
    ]

    return RecentReviewsListResponse(reviews=review_responses)


@router.get(
    "/trending-albums",
    response_model=TrendingAlbumsListResponse,
    summary="Get trending albums",
)
async def get_trending_albums(
    db: DbSession,
    limit: int = Query(6, ge=1, le=20, description="Number of albums to return"),
    max_weeks_back: int = Query(12, ge=1, le=52, description="Max weeks to look back"),
):
    """
    Get trending albums based on review count in the current week.

    If no reviews are found in the current week, it looks back week by week
    until it finds a week with reviews (up to max_weeks_back).

    Albums are ranked by review count (descending), then by average rating.
    """
    now = datetime.now(timezone.utc)

    # Find the start of the current week (Monday)
    days_since_monday = now.weekday()
    current_week_start = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    albums = []
    week_start = current_week_start
    week_end = week_start + timedelta(days=7)

    # Look back week by week until we find data
    for _ in range(max_weeks_back):
        # Query albums with reviews in this week, ordered by review count
        result = await db.execute(
            select(
                Album.spotify_id,
                Album.title,
                Album.artist,
                Album.cover_image,
                Album.release_date,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("review_count")
            )
            .join(Review, Review.album_id == Album.id)
            .where(
                and_(
                    Review.created_at >= week_start,
                    Review.created_at < week_end
                )
            )
            .group_by(Album.id)
            .order_by(
                func.count(Review.id).desc(),
                func.avg(Review.rating).desc()
            )
            .limit(limit)
        )

        rows = result.all()

        if rows:
            # Found data for this week
            for row in rows:
                albums.append(TrendingAlbumResponse(
                    spotify_id=row.spotify_id,
                    title=row.title,
                    artist=row.artist,
                    cover_image=row.cover_image,
                    release_date=row.release_date,
                    avg_rating=round(float(row.avg_rating), 1) if row.avg_rating else None,
                    review_count=row.review_count,
                    week_start=week_start.date().isoformat(),
                ))
            break

        # No data this week, go back one week
        week_end = week_start
        week_start = week_start - timedelta(days=7)

    return TrendingAlbumsListResponse(
        albums=albums,
        week_start=week_start.date().isoformat(),
        week_end=week_end.date().isoformat(),
    )
