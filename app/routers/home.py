from fastapi import APIRouter, Query
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.review import Album, Review, ReviewLike, Comment
from app.schemas.review import ReviewResponse, AlbumResponse
from app.dependencies import DbSession, OptionalUser
from app.services.storage_service import StorageService
from pydantic import BaseModel

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

    review_responses = []
    for review in reviews:
        # Resolve profile picture URL
        profile_picture_url = await StorageService.resolve_profile_picture(
            review.user.profile_picture
        )

        review_responses.append(RecentReviewResponse(
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
            user_profile_picture=profile_picture_url,
        ))

    return RecentReviewsListResponse(reviews=review_responses)
