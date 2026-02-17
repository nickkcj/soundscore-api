from uuid import UUID

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.models.user import User, UserFollow
from app.models.review import Album, Review, Comment, ReviewLike, CommentLike
from app.schemas.review import (
    ReviewCreate,
    ReviewUpdate,
    ReviewResponse,
    ReviewListResponse,
    CommentCreate,
    CommentResponse,
    CommentListResponse,
    LikeResponse,
    SpotifyAlbumResult,
    AlbumResponse,
    AlbumWithRating,
    TrackItem,
    AlbumDetailResponse,
)
from app.schemas.user import UserListItem
from app.schemas.auth import MessageResponse
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    BadRequestException,
)
from app.dependencies import CurrentUser, OptionalUser, DbSession
from app.services.spotify_service import spotify_service
from app.services.gemini_service import gemini_service
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService
from app.services.cache_service import CacheInvalidation
from app.utils.batch_queries import build_review_responses_batch

router = APIRouter()


# ============== Helper Functions ==============

async def _build_review_response(
    review: Review,
    db: DbSession,
    current_user_id: int | None = None
) -> ReviewResponse:
    """Build a ReviewResponse with all related data."""
    # Get like count
    like_count_result = await db.execute(
        select(func.count()).select_from(ReviewLike).where(ReviewLike.review_id == review.id)
    )
    like_count = like_count_result.scalar() or 0

    # Get comment count
    comment_count_result = await db.execute(
        select(func.count()).select_from(Comment).where(Comment.review_id == review.id)
    )
    comment_count = comment_count_result.scalar() or 0

    # Check if current user liked
    is_liked = None
    if current_user_id:
        like_result = await db.execute(
            select(ReviewLike).where(
                ReviewLike.review_id == review.id,
                ReviewLike.user_id == current_user_id
            )
        )
        is_liked = like_result.scalar_one_or_none() is not None

    # Resolve profile picture URL
    profile_picture_url = await StorageService.resolve_profile_picture(review.user.profile_picture)

    return ReviewResponse(
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
        user_profile_picture=profile_picture_url,
        like_count=like_count,
        comment_count=comment_count,
        is_liked=is_liked,
    )


# ============== Spotify Search ==============

@router.get(
    "/search/albums",
    response_model=list[SpotifyAlbumResult],
    summary="Search albums on Spotify",
)
async def search_albums(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=10, description="Number of results (Spotify Dev Mode max: 10)"),
    current_user: CurrentUser = None,  # Require auth
):
    """
    Search for albums on Spotify.

    Returns album info including Spotify ID, title, artist, cover image.
    """
    try:
        return await spotify_service.search_albums(q, limit)
    except ValueError as e:
        raise BadRequestException(str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Spotify API error: {str(e)}")


# ============== Discover ==============

class DiscoverResponse(BaseModel):
    """Response schema for discover endpoint."""
    albums: list[AlbumWithRating]
    users: list[UserListItem]


@router.get(
    "/discover",
    response_model=DiscoverResponse,
    summary="Discover albums and users",
)
async def discover(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("all", description="Type of search: albums, users, or all"),
    limit: int = Query(10, ge=1, le=10, description="Number of results per type (Spotify Dev Mode max: 10)"),
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """
    Search for albums on Spotify and users in the database.

    - **type=albums**: Only search Spotify albums
    - **type=users**: Only search users in database
    - **type=all**: Search both albums and users

    Returns albums with their average ratings and review counts from our database.
    """
    albums: list[AlbumWithRating] = []
    users: list[UserListItem] = []

    # Search albums on Spotify
    if type in ("albums", "all"):
        try:
            spotify_results = await spotify_service.search_albums(q, limit)

            # Get spotify_ids to look up ratings in our database
            spotify_ids = [album.spotify_id for album in spotify_results]

            # Query our database for existing albums with ratings
            if spotify_ids:
                album_stats_query = await db.execute(
                    select(
                        Album.spotify_id,
                        func.avg(Review.rating).label("avg_rating"),
                        func.count(Review.id).label("review_count")
                    )
                    .join(Review, Review.album_id == Album.id)
                    .where(Album.spotify_id.in_(spotify_ids))
                    .group_by(Album.spotify_id)
                )
                album_stats = {row.spotify_id: (row.avg_rating, row.review_count) for row in album_stats_query.all()}
            else:
                album_stats = {}

            # Merge Spotify results with our database stats
            for album in spotify_results:
                stats = album_stats.get(album.spotify_id)
                albums.append(AlbumWithRating(
                    spotify_id=album.spotify_id,
                    title=album.title,
                    artist=album.artist,
                    cover_image=album.cover_image,
                    release_date=album.release_date,
                    avg_rating=round(float(stats[0]), 1) if stats and stats[0] else None,
                    review_count=stats[1] if stats else 0,
                ))
        except Exception:
            # If Spotify fails, return empty albums list
            pass

    # Search users in database
    if type in ("users", "all"):
        # Search by username (case-insensitive, partial match)
        # Exclude current user from results
        user_filters = [User.username.ilike(f"%{q}%")]
        if current_user:
            user_filters.append(User.id != current_user.id)

        user_query = await db.execute(
            select(User)
            .where(*user_filters)
            .order_by(User.username)
            .limit(limit)
        )
        found_users = user_query.scalars().all()

        # Check which users the current user is following
        following_ids = set()
        if current_user:
            following_result = await db.execute(
                select(UserFollow.following_id).where(UserFollow.follower_id == current_user.id)
            )
            following_ids = set(row[0] for row in following_result.all())

        for user in found_users:
            # Resolve profile picture
            profile_pic = await StorageService.resolve_profile_picture(user.profile_picture)

            users.append(UserListItem(
                id=user.id,
                username=user.username,
                profile_picture=profile_pic,
                bio=user.bio,
                is_following=user.id in following_ids if current_user else None,
            ))

    return DiscoverResponse(albums=albums, users=users)


# ============== Album Details ==============

@router.get(
    "/album/{spotify_id}/details",
    response_model=AlbumDetailResponse,
    summary="Get album details",
)
async def get_album_details(
    spotify_id: str,
    db: DbSession,
    current_user: OptionalUser = None,
):
    """
    Get complete album details from Spotify plus SoundScore stats.

    - Fetches album info, tracklist from Spotify
    - Returns avg rating and review count from SoundScore
    - Generates AI summary on first access (cached in DB)
    """
    # Fetch album details from Spotify
    spotify_data = await spotify_service.get_album_details(spotify_id)

    if not spotify_data:
        raise NotFoundException("Album not found on Spotify")

    # Check if album exists in our database
    album_result = await db.execute(
        select(Album).where(Album.spotify_id == spotify_id)
    )
    album = album_result.scalar_one_or_none()

    # Get stats from our database
    avg_rating = None
    review_count = 0
    summary = None

    if album:
        # Get review stats
        stats_result = await db.execute(
            select(
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("review_count")
            ).where(Review.album_id == album.id)
        )
        stats = stats_result.first()
        if stats:
            avg_rating = round(float(stats.avg_rating), 1) if stats.avg_rating else None
            review_count = stats.review_count or 0

        # Get or generate summary
        summary = album.summary

    # Generate summary if not exists and album has enough data
    if not summary and spotify_data.get("tracks"):
        try:
            summary = gemini_service.generate_album_summary(
                title=spotify_data["title"],
                artist=spotify_data["artist"],
                release_date=spotify_data.get("release_date"),
                tracks=spotify_data["tracks"],
                label=spotify_data.get("label"),
            )

            # Save summary to database if album exists
            if summary and album:
                album.summary = summary
                await db.commit()
            elif summary and not album:
                # Create album record to store summary
                new_album = Album(
                    spotify_id=spotify_id,
                    title=spotify_data["title"],
                    artist=spotify_data["artist"],
                    cover_image=spotify_data.get("cover_image"),
                    release_date=spotify_data.get("release_date"),
                    summary=summary,
                )
                db.add(new_album)
                await db.commit()
        except Exception:
            # If summary generation fails, continue without it
            pass

    # Build track items
    tracks = [
        TrackItem(
            track_number=t["track_number"],
            name=t["name"],
            duration_ms=t["duration_ms"],
            explicit=t["explicit"],
            spotify_url=t["spotify_url"],
            artists=t["artists"],
        )
        for t in spotify_data.get("tracks", [])
    ]

    return AlbumDetailResponse(
        spotify_id=spotify_data["spotify_id"],
        title=spotify_data["title"],
        artist=spotify_data["artist"],
        cover_image=spotify_data.get("cover_image"),
        release_date=spotify_data.get("release_date"),
        label=spotify_data.get("label"),
        copyrights=spotify_data.get("copyrights", []),
        total_tracks=spotify_data.get("total_tracks", 0),
        popularity=spotify_data.get("popularity", 0),
        spotify_url=spotify_data.get("spotify_url", ""),
        tracks=tracks,
        summary=summary,
        avg_rating=avg_rating,
        review_count=review_count,
    )


# ============== Review CRUD ==============

@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
    summary="Create a review",
)
async def create_review(
    review_data: ReviewCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Create a new album review.

    - User can only review each album once
    - Rating must be 1-5
    - Creates the album record if it doesn't exist
    """
    # Get or create album
    album_result = await db.execute(
        select(Album).where(Album.spotify_id == review_data.spotify_id)
    )
    album = album_result.scalar_one_or_none()

    if not album:
        album = Album(
            spotify_id=review_data.spotify_id,
            title=review_data.title,
            artist=review_data.artist,
            cover_image=review_data.cover_image,
            release_date=review_data.release_date,
        )
        db.add(album)
        await db.flush()

    # Check if user already reviewed this album
    existing_review = await db.execute(
        select(Review).where(
            Review.user_id == current_user.id,
            Review.album_id == album.id
        )
    )
    if existing_review.scalar_one_or_none():
        raise ConflictException("You have already reviewed this album")

    # Create review
    review = Review(
        user_id=current_user.id,
        album_id=album.id,
        rating=review_data.rating,
        text=review_data.text,
        is_favorite=review_data.is_favorite,
    )
    db.add(review)
    await db.commit()

    # Invalidate feed caches for the author's followers
    follower_result = await db.execute(
        select(UserFollow.follower_id).where(UserFollow.following_id == current_user.id)
    )
    follower_ids = [row[0] for row in follower_result.all()]
    await CacheInvalidation.on_new_review(current_user.id, follower_ids)

    # Reload with relationships
    await db.refresh(review)
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.album))
        .where(Review.id == review.id)
    )
    review = result.scalar_one()

    return await _build_review_response(review, db, current_user.id)


@router.get(
    "/{review_uuid}",
    response_model=ReviewResponse,
    summary="Get a review by UUID",
)
async def get_review(
    review_uuid: UUID,
    db: DbSession,
    current_user: OptionalUser = None,
):
    """Get a single review by UUID."""
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.album))
        .where(Review.uuid == review_uuid)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise NotFoundException("Review not found")

    return await _build_review_response(
        review, db,
        current_user.id if current_user else None
    )


@router.patch(
    "/{review_uuid}",
    response_model=ReviewResponse,
    summary="Update a review",
)
async def update_review(
    review_uuid: UUID,
    update_data: ReviewUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Update a review.

    Only the review author can update.
    """
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.album))
        .where(Review.uuid == review_uuid)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise NotFoundException("Review not found")

    if review.user_id != current_user.id:
        raise ForbiddenException("You can only edit your own reviews")

    # Update fields
    if update_data.rating is not None:
        review.rating = update_data.rating
    if update_data.text is not None:
        review.text = update_data.text
    if update_data.is_favorite is not None:
        review.is_favorite = update_data.is_favorite

    await db.commit()
    await db.refresh(review)

    return await _build_review_response(review, db, current_user.id)


@router.delete(
    "/{review_uuid}",
    response_model=MessageResponse,
    summary="Delete a review",
)
async def delete_review(
    review_uuid: UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Delete a review.

    Only the review author can delete.
    """
    result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise NotFoundException("Review not found")

    if review.user_id != current_user.id:
        raise ForbiddenException("You can only delete your own reviews")

    # Get follower IDs before deleting
    follower_result = await db.execute(
        select(UserFollow.follower_id).where(UserFollow.following_id == current_user.id)
    )
    follower_ids = [row[0] for row in follower_result.all()]

    await db.delete(review)
    await db.commit()

    # Invalidate feed caches
    await CacheInvalidation.on_review_delete(current_user.id, follower_ids)

    return MessageResponse(message="Review deleted successfully")


# ============== Review Lists ==============

@router.get(
    "/user/{username}",
    response_model=ReviewListResponse,
    summary="Get reviews by user",
)
async def get_user_reviews(
    username: str,
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    favorites_only: bool = Query(False, description="Only show favorites"),
):
    """Get all reviews by a specific user."""
    # Get user
    user_result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    user = user_result.scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found")

    # Build query
    query = select(Review).where(Review.user_id == user.id)
    count_query = select(func.count()).select_from(Review).where(Review.user_id == user.id)

    if favorites_only:
        query = query.where(Review.is_favorite == True)
        count_query = count_query.where(Review.is_favorite == True)

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated reviews
    offset = (page - 1) * per_page
    result = await db.execute(
        query
        .options(selectinload(Review.user), selectinload(Review.album))
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    reviews = result.scalars().all()

    # Build responses using batch queries (avoids N+1)
    review_responses = await build_review_responses_batch(
        reviews, db, current_user.id if current_user else None
    )

    return ReviewListResponse(
        reviews=review_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


@router.get(
    "/album/{spotify_id}",
    response_model=ReviewListResponse,
    summary="Get reviews for an album",
)
async def get_album_reviews(
    spotify_id: str,
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get all reviews for a specific album."""
    # Get album
    album_result = await db.execute(
        select(Album).where(Album.spotify_id == spotify_id)
    )
    album = album_result.scalar_one_or_none()

    if not album:
        # Album not reviewed yet - return empty list
        return ReviewListResponse(
            reviews=[],
            total=0,
            page=page,
            per_page=per_page,
            has_next=False,
            has_prev=False,
        )

    # Get total
    total_result = await db.execute(
        select(func.count()).select_from(Review).where(Review.album_id == album.id)
    )
    total = total_result.scalar() or 0

    # Get paginated reviews
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.album))
        .where(Review.album_id == album.id)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    reviews = result.scalars().all()

    # Build responses using batch queries (avoids N+1)
    review_responses = await build_review_responses_batch(
        reviews, db, current_user.id if current_user else None
    )

    return ReviewListResponse(
        reviews=review_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


# ============== Comments ==============

@router.post(
    "/{review_uuid}/comments",
    response_model=CommentResponse,
    status_code=201,
    summary="Add a comment to a review",
)
async def create_comment(
    review_uuid: UUID,
    comment_data: CommentCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    """Add a comment to a review. Supports nested replies via parent_id."""
    # Verify review exists
    review_result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    # Verify parent comment if provided
    parent_comment = None
    if comment_data.parent_id:
        parent_result = await db.execute(
            select(Comment).where(
                Comment.id == comment_data.parent_id,
                Comment.review_id == review.id
            )
        )
        parent_comment = parent_result.scalar_one_or_none()
        if not parent_comment:
            raise NotFoundException("Parent comment not found")

    # Create comment
    comment = Comment(
        user_id=current_user.id,
        review_id=review.id,
        text=comment_data.text,
        parent_id=comment_data.parent_id,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)

    # Create notification
    if parent_comment:
        # Reply notification to parent comment author
        await NotificationService.create_reply_notification(
            db=db,
            actor=current_user,
            parent_comment=parent_comment,
            reply=comment,
        )
    else:
        # Comment notification to review author
        await NotificationService.create_comment_notification(
            db=db,
            actor=current_user,
            review=review,
            comment=comment,
        )

    await db.commit()

    # Resolve profile picture URL
    profile_picture_url = await StorageService.resolve_profile_picture(current_user.profile_picture)

    return CommentResponse(
        id=comment.id,
        text=comment.text,
        created_at=comment.created_at,
        user_id=current_user.id,
        username=current_user.username,
        user_profile_picture=profile_picture_url,
        parent_id=comment.parent_id,
        replies=[],
    )


@router.get(
    "/{review_uuid}/comments",
    response_model=CommentListResponse,
    summary="Get comments for a review",
)
async def get_review_comments(
    review_uuid: UUID,
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get top-level comments for a review with nested replies."""
    # Verify review exists
    review_result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    # Get total top-level comments
    total_result = await db.execute(
        select(func.count()).select_from(Comment).where(
            Comment.review_id == review.id,
            Comment.parent_id == None
        )
    )
    total = total_result.scalar() or 0

    # Get paginated top-level comments with replies
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Comment)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.replies).selectinload(Comment.user)
        )
        .where(
            Comment.review_id == review.id,
            Comment.parent_id == None
        )
        .order_by(Comment.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    comments = result.scalars().all()

    # Get all comment IDs (including replies) for batch like queries
    all_comment_ids = []
    for comment in comments:
        all_comment_ids.append(comment.id)
        for reply in comment.replies:
            all_comment_ids.append(reply.id)

    # Batch get like counts for all comments
    like_counts = {}
    if all_comment_ids:
        like_counts_result = await db.execute(
            select(CommentLike.comment_id, func.count(CommentLike.id))
            .where(CommentLike.comment_id.in_(all_comment_ids))
            .group_by(CommentLike.comment_id)
        )
        like_counts = {row[0]: row[1] for row in like_counts_result.all()}

    # Batch get user's likes if logged in
    user_liked_ids = set()
    if current_user and all_comment_ids:
        user_likes_result = await db.execute(
            select(CommentLike.comment_id)
            .where(
                CommentLike.comment_id.in_(all_comment_ids),
                CommentLike.user_id == current_user.id
            )
        )
        user_liked_ids = {row[0] for row in user_likes_result.all()}

    # Build responses
    comment_responses = []
    for comment in comments:
        # Resolve profile pictures for replies
        replies = []
        for reply in sorted(comment.replies, key=lambda r: r.created_at):
            reply_profile_url = await StorageService.resolve_profile_picture(reply.user.profile_picture)
            replies.append(
                CommentResponse(
                    id=reply.id,
                    text=reply.text,
                    created_at=reply.created_at,
                    user_id=reply.user.id,
                    username=reply.user.username,
                    user_profile_picture=reply_profile_url,
                    parent_id=reply.parent_id,
                    like_count=like_counts.get(reply.id, 0),
                    is_liked=reply.id in user_liked_ids if current_user else None,
                    replies=[],
                )
            )

        # Resolve profile picture for comment
        comment_profile_url = await StorageService.resolve_profile_picture(comment.user.profile_picture)
        comment_responses.append(
            CommentResponse(
                id=comment.id,
                text=comment.text,
                created_at=comment.created_at,
                user_id=comment.user.id,
                username=comment.user.username,
                user_profile_picture=comment_profile_url,
                parent_id=None,
                like_count=like_counts.get(comment.id, 0),
                is_liked=comment.id in user_liked_ids if current_user else None,
                replies=replies,
            )
        )

    return CommentListResponse(
        comments=comment_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
    )


@router.delete(
    "/{review_uuid}/comments/{comment_id}",
    response_model=MessageResponse,
    summary="Delete a comment",
)
async def delete_comment(
    review_uuid: UUID,
    comment_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Delete a comment. Only the comment author can delete."""
    # Verify review exists
    review_result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    result = await db.execute(
        select(Comment).where(
            Comment.id == comment_id,
            Comment.review_id == review.id
        )
    )
    comment = result.scalar_one_or_none()

    if not comment:
        raise NotFoundException("Comment not found")

    if comment.user_id != current_user.id:
        raise ForbiddenException("You can only delete your own comments")

    await db.delete(comment)
    await db.commit()

    return MessageResponse(message="Comment deleted successfully")


@router.post(
    "/{review_uuid}/comments/{comment_id}/like",
    response_model=LikeResponse,
    summary="Toggle like on a comment",
)
async def toggle_comment_like(
    review_uuid: UUID,
    comment_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Toggle like on a comment. If already liked, removes the like."""
    # Verify review exists
    review_result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    # Verify comment exists
    comment_result = await db.execute(
        select(Comment).where(
            Comment.id == comment_id,
            Comment.review_id == review.id
        )
    )
    comment = comment_result.scalar_one_or_none()
    if not comment:
        raise NotFoundException("Comment not found")

    # Check if already liked
    existing_like = await db.execute(
        select(CommentLike).where(
            CommentLike.user_id == current_user.id,
            CommentLike.comment_id == comment_id
        )
    )
    like = existing_like.scalar_one_or_none()

    if like:
        # Unlike
        await db.delete(like)
        liked = False
    else:
        # Like
        new_like = CommentLike(user_id=current_user.id, comment_id=comment_id)
        db.add(new_like)
        liked = True

    await db.commit()

    # Get updated like count
    count_result = await db.execute(
        select(func.count()).select_from(CommentLike).where(CommentLike.comment_id == comment_id)
    )
    like_count = count_result.scalar() or 0

    return LikeResponse(liked=liked, like_count=like_count)


# ============== Likes ==============

@router.post(
    "/{review_uuid}/like",
    response_model=LikeResponse,
    summary="Toggle like on a review",
)
async def toggle_like(
    review_uuid: UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    """Toggle like on a review. If already liked, removes the like."""
    # Verify review exists
    review_result = await db.execute(
        select(Review).where(Review.uuid == review_uuid)
    )
    review = review_result.scalar_one_or_none()
    if not review:
        raise NotFoundException("Review not found")

    # Check existing like
    like_result = await db.execute(
        select(ReviewLike).where(
            ReviewLike.review_id == review.id,
            ReviewLike.user_id == current_user.id
        )
    )
    existing_like = like_result.scalar_one_or_none()

    if existing_like:
        # Unlike
        await db.delete(existing_like)
        liked = False
    else:
        # Like
        new_like = ReviewLike(
            user_id=current_user.id,
            review_id=review.id,
        )
        db.add(new_like)
        liked = True

        # Create notification only when liking (not unliking)
        await NotificationService.create_like_notification(
            db=db,
            actor=current_user,
            review=review,
        )

    await db.commit()

    # Get updated count
    count_result = await db.execute(
        select(func.count()).select_from(ReviewLike).where(ReviewLike.review_id == review.id)
    )
    like_count = count_result.scalar() or 0

    return LikeResponse(liked=liked, like_count=like_count)
