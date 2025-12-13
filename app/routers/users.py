import asyncio
import uuid
import httpx
from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User, UserFollow
from app.models.review import Review
from app.schemas.user import (
    UserProfileResponse,
    UserUpdate,
    UserListItem,
    PaginatedUsersResponse,
    FollowResponse,
)
from app.schemas.auth import MessageResponse
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
    ConflictException,
)
from app.dependencies import CurrentUser, OptionalUser, DbSession
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService
from app.services.cache_service import CacheInvalidation
from app.services.recommendation_service import RecommendationService
from app.config import get_settings

router = APIRouter()


@router.get(
    "/profile/{username}",
    response_model=UserProfileResponse,
    summary="Get user profile",
)
async def get_user_profile(
    username: str,
    db: DbSession,
    current_user: OptionalUser = None
):
    """
    Get a user's public profile with stats.

    Returns:
    - User info (username, bio, profile picture)
    - Review count and average rating
    - Follower/following counts
    - Whether current user is following (if authenticated)
    """
    # Get user
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found")

    # Get review stats
    stats_result = await db.execute(
        select(
            func.count(Review.id).label("count"),
            func.avg(Review.rating).label("avg_rating")
        ).where(Review.user_id == user.id)
    )
    stats = stats_result.first()

    # Get follower count
    followers_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.following_id == user.id)
    )
    followers_count = followers_result.scalar() or 0

    # Get following count
    following_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.follower_id == user.id)
    )
    following_count = following_result.scalar() or 0

    # Check if current user is following this user
    is_following = None
    if current_user and current_user.id != user.id:
        follow_result = await db.execute(
            select(UserFollow).where(
                UserFollow.follower_id == current_user.id,
                UserFollow.following_id == user.id
            )
        )
        is_following = follow_result.scalar_one_or_none() is not None

    # Resolve profile picture and banner to signed URLs
    profile_picture_url = await StorageService.resolve_profile_picture(user.profile_picture)
    banner_image_url = await StorageService.resolve_banner_image(user.banner_image)

    return UserProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        profile_picture=profile_picture_url,
        banner_image=banner_image_url,
        bio=user.bio,
        created_at=user.created_at,
        review_count=stats.count or 0,
        avg_rating=round(float(stats.avg_rating), 1) if stats.avg_rating else None,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following,
    )


@router.patch(
    "/profile",
    response_model=UserProfileResponse,
    summary="Update current user profile",
)
async def update_profile(
    update_data: UserUpdate,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Update the current user's profile.

    - **username**: New username (optional)
    - **bio**: Profile bio (optional, max 500 chars)
    - **profile_picture**: Profile picture URL (optional)
    """
    # Check if new username is taken
    if update_data.username and update_data.username.lower() != current_user.username:
        result = await db.execute(
            select(User).where(User.username == update_data.username.lower())
        )
        if result.scalar_one_or_none():
            raise ConflictException("Username already taken")
        current_user.username = update_data.username.lower()

    # Check if new email is taken
    if update_data.email and update_data.email.lower() != current_user.email:
        result = await db.execute(
            select(User).where(User.email == update_data.email.lower())
        )
        if result.scalar_one_or_none():
            raise ConflictException("Email already registered")
        current_user.email = update_data.email.lower()

    # Update other fields
    if update_data.bio is not None:
        current_user.bio = update_data.bio

    if update_data.profile_picture is not None:
        current_user.profile_picture = update_data.profile_picture

    if update_data.banner_image is not None:
        current_user.banner_image = update_data.banner_image

    await db.commit()
    await db.refresh(current_user)

    # Get stats for response (reuse profile logic)
    return await get_user_profile(current_user.username, db, current_user)


@router.post(
    "/profile/{username}/follow",
    response_model=FollowResponse,
    summary="Follow a user",
)
async def follow_user(
    username: str,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Follow another user.
    """
    if current_user.username == username.lower():
        raise BadRequestException("You cannot follow yourself")

    # Get target user
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise NotFoundException("User not found")

    # Check if already following
    existing_follow = await db.execute(
        select(UserFollow).where(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == target_user.id
        )
    )
    if existing_follow.scalar_one_or_none():
        raise ConflictException("Already following this user")

    # Create follow relationship
    follow = UserFollow(
        follower_id=current_user.id,
        following_id=target_user.id
    )
    db.add(follow)

    # Create notification
    await NotificationService.create_follow_notification(
        db=db,
        actor=current_user,
        recipient_id=target_user.id,
    )

    await db.commit()

    # Invalidate current user's feed cache (now includes new user's reviews)
    await CacheInvalidation.on_follow_change(current_user.id)

    # Get updated follower count
    count_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.following_id == target_user.id)
    )
    followers_count = count_result.scalar() or 0

    return FollowResponse(
        success=True,
        message=f"Now following {target_user.username}",
        followers_count=followers_count,
    )


@router.post(
    "/profile/{username}/unfollow",
    response_model=FollowResponse,
    summary="Unfollow a user",
)
async def unfollow_user(
    username: str,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Unfollow a user.
    """
    # Get target user
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise NotFoundException("User not found")

    # Find existing follow
    follow_result = await db.execute(
        select(UserFollow).where(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == target_user.id
        )
    )
    follow = follow_result.scalar_one_or_none()

    if not follow:
        raise BadRequestException("Not following this user")

    # Remove follow
    await db.delete(follow)
    await db.commit()

    # Invalidate current user's feed cache (no longer includes unfollowed user's reviews)
    await CacheInvalidation.on_follow_change(current_user.id)

    # Get updated follower count
    count_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.following_id == target_user.id)
    )
    followers_count = count_result.scalar() or 0

    return FollowResponse(
        success=True,
        message=f"Unfollowed {target_user.username}",
        followers_count=followers_count,
    )


@router.get(
    "/profile/{username}/followers",
    response_model=PaginatedUsersResponse,
    summary="Get user's followers",
)
async def get_followers(
    username: str,
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get a paginated list of users following this user.
    """
    # Get user
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found")

    # Get total count
    total_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.following_id == user.id)
    )
    total = total_result.scalar() or 0

    # Get paginated followers
    offset = (page - 1) * per_page
    followers_result = await db.execute(
        select(UserFollow)
        .options(selectinload(UserFollow.follower))
        .where(UserFollow.following_id == user.id)
        .order_by(UserFollow.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    follows = followers_result.scalars().all()

    # Check which users current_user is following
    following_ids = set()
    if current_user:
        following_result = await db.execute(
            select(UserFollow.following_id).where(UserFollow.follower_id == current_user.id)
        )
        following_ids = set(row[0] for row in following_result.all())

    # Parallel profile picture resolution
    profile_pics = await asyncio.gather(*[
        StorageService.resolve_profile_picture(f.follower.profile_picture)
        for f in follows
    ])

    users = [
        UserListItem(
            id=f.follower.id,
            username=f.follower.username,
            profile_picture=profile_pic,
            bio=f.follower.bio,
            is_following=f.follower.id in following_ids if current_user else None,
        )
        for f, profile_pic in zip(follows, profile_pics)
    ]

    return PaginatedUsersResponse(
        users=users,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


@router.get(
    "/profile/{username}/following",
    response_model=PaginatedUsersResponse,
    summary="Get users that this user follows",
)
async def get_following(
    username: str,
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get a paginated list of users that this user follows.
    """
    # Get user
    result = await db.execute(
        select(User).where(User.username == username.lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found")

    # Get total count
    total_result = await db.execute(
        select(func.count()).select_from(UserFollow).where(UserFollow.follower_id == user.id)
    )
    total = total_result.scalar() or 0

    # Get paginated following
    offset = (page - 1) * per_page
    following_result = await db.execute(
        select(UserFollow)
        .options(selectinload(UserFollow.following))
        .where(UserFollow.follower_id == user.id)
        .order_by(UserFollow.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    follows = following_result.scalars().all()

    # Check which users current_user is following
    following_ids = set()
    if current_user:
        current_following_result = await db.execute(
            select(UserFollow.following_id).where(UserFollow.follower_id == current_user.id)
        )
        following_ids = set(row[0] for row in current_following_result.all())

    # Parallel profile picture resolution
    profile_pics = await asyncio.gather(*[
        StorageService.resolve_profile_picture(f.following.profile_picture)
        for f in follows
    ])

    users = [
        UserListItem(
            id=f.following.id,
            username=f.following.username,
            profile_picture=profile_pic,
            bio=f.following.bio,
            is_following=f.following.id in following_ids if current_user else None,
        )
        for f, profile_pic in zip(follows, profile_pics)
    ]

    return PaginatedUsersResponse(
        users=users,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


@router.get(
    "/suggested",
    response_model=PaginatedUsersResponse,
    summary="Get suggested users to follow",
)
async def get_suggested_users(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(5, ge=1, le=20),
):
    """
    Get suggested users to follow based on activity similarity.

    Algorithm considers:
    - Similar album ratings (users who rated same albums similarly)
    - Common review likes (users who liked the same reviews)
    - Recent activity (users who posted reviews recently)
    - Favorite albums overlap (shared favorite albums)

    For new users with no reviews, shows most recently active users.
    Results are cached for 15 minutes.
    """
    recommendations = await RecommendationService.get_recommended_users(
        db, current_user.id, limit
    )

    users = [
        UserListItem(
            id=rec.user_id,
            username=rec.username,
            profile_picture=rec.profile_picture,
            bio=rec.bio,
            is_following=False,
            followers_count=rec.followers_count,
        )
        for rec in recommendations
    ]

    return PaginatedUsersResponse(
        users=users,
        total=len(users),
        page=1,
        per_page=limit,
        has_next=False,
        has_prev=False,
    )


@router.post(
    "/profile/picture",
    response_model=UserProfileResponse,
    summary="Upload profile picture",
)
async def upload_profile_picture(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    """
    Upload a new profile picture for the current user.

    - Accepts JPG, PNG, WebP, and GIF images
    - Maximum file size: 5MB
    - Image is stored in Supabase Storage
    """
    settings = get_settings()

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

    # Check Supabase configuration
    if not settings.supabase_url:
        raise HTTPException(
            status_code=500,
            detail="Storage service not configured"
        )

    # Use service role key if available (bypasses RLS), otherwise fall back to anon key
    storage_key = settings.supabase_service_role_key or settings.supabase_key
    if not storage_key:
        raise HTTPException(
            status_code=500,
            detail="Storage service not configured"
        )

    try:
        bucket = "profile_pictures"

        # Generate unique filename
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{current_user.id}_{uuid.uuid4()}.{file_ext}"

        # Upload to Supabase Storage via REST API
        upload_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{filename}"

        async with httpx.AsyncClient() as client:
            # Delete old profile picture if exists
            if current_user.profile_picture:
                try:
                    old_path = current_user.profile_picture
                    # Handle both new format (bucket/filename) and legacy URLs
                    if old_path.startswith("http"):
                        old_filename = old_path.split(f"{bucket}/")[-1] if bucket in old_path else None
                    elif old_path.startswith(f"{bucket}/"):
                        old_filename = old_path.split(f"{bucket}/")[-1]
                    else:
                        old_filename = None

                    if old_filename:
                        delete_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{old_filename}"
                        await client.delete(
                            delete_url,
                            headers={
                                "Authorization": f"Bearer {storage_key}",
                                "apikey": storage_key,
                            }
                        )
                except Exception:
                    pass  # Ignore errors when deleting old file

            # Upload new file
            response = await client.post(
                upload_url,
                content=contents,
                headers={
                    "Authorization": f"Bearer {storage_key}",
                    "apikey": storage_key,
                    "Content-Type": file.content_type,
                }
            )

            if response.status_code not in (200, 201):
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to upload: {response.text}"
                )

        # Store just the path (bucket/filename) - we'll generate signed URLs when serving
        # Use explicit UPDATE for transaction pooler compatibility
        from sqlalchemy import update
        await db.execute(
            update(User)
            .where(User.id == current_user.id)
            .values(profile_picture=f"{bucket}/{filename}")
        )
        await db.commit()

        # Return updated profile
        return await get_user_profile(current_user.username, db, None)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )


@router.post(
    "/profile/banner",
    response_model=UserProfileResponse,
    summary="Upload banner image",
)
async def upload_banner_image(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    """
    Upload a new banner image for the current user.

    - Accepts JPG, PNG, WebP, and GIF images
    - Maximum file size: 5MB
    - Recommended aspect ratio: 3:1 (e.g., 1500x500)
    - Image is stored in Supabase Storage
    """
    settings = get_settings()

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

    # Check Supabase configuration
    if not settings.supabase_url:
        raise HTTPException(
            status_code=500,
            detail="Storage service not configured"
        )

    storage_key = settings.supabase_service_role_key or settings.supabase_key
    if not storage_key:
        raise HTTPException(
            status_code=500,
            detail="Storage service not configured"
        )

    try:
        bucket = "banner_images"

        # Generate unique filename
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{current_user.id}_{uuid.uuid4()}.{file_ext}"

        # Upload to Supabase Storage via REST API
        upload_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{filename}"

        async with httpx.AsyncClient() as client:
            # Delete old banner if exists
            if current_user.banner_image:
                try:
                    old_path = current_user.banner_image
                    if old_path.startswith(f"{bucket}/"):
                        old_filename = old_path.split(f"{bucket}/")[-1]
                        delete_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{old_filename}"
                        await client.delete(
                            delete_url,
                            headers={
                                "Authorization": f"Bearer {storage_key}",
                                "apikey": storage_key,
                            }
                        )
                except Exception:
                    pass

            # Upload new file
            response = await client.post(
                upload_url,
                content=contents,
                headers={
                    "Authorization": f"Bearer {storage_key}",
                    "apikey": storage_key,
                    "Content-Type": file.content_type,
                }
            )

            if response.status_code not in (200, 201):
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to upload: {response.text}"
                )

        # Store path - use explicit UPDATE for transaction pooler compatibility
        from sqlalchemy import update
        await db.execute(
            update(User)
            .where(User.id == current_user.id)
            .values(banner_image=f"{bucket}/{filename}")
        )
        await db.commit()

        return await get_user_profile(current_user.username, db, None)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )


@router.delete(
    "/account",
    response_model=MessageResponse,
    summary="Delete current user account",
)
async def delete_account(current_user: CurrentUser, db: DbSession):
    """
    Permanently delete the current user's account and all associated data.

    **Warning:** This action cannot be undone!
    """
    await db.delete(current_user)
    await db.commit()

    return MessageResponse(message="Account deleted successfully")
