import uuid
import httpx
from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.config import get_settings
from app.models.group import Group, GroupMember, GroupMessage
from app.schemas.group import (
    GroupCreate,
    GroupUpdate,
    GroupResponse,
    GroupListResponse,
    GroupMemberResponse,
    GroupMemberListResponse,
    GroupMessageResponse,
    GroupMessageListResponse,
    GroupDetailResponse,
)
from app.schemas.auth import MessageResponse
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    BadRequestException,
)
from app.dependencies import CurrentUser, OptionalUser, DbSession
from app.websockets.manager import manager
from app.services.storage_service import StorageService

router = APIRouter()


# ============== Helper Functions ==============

async def _get_group_member_count(db: DbSession, group_id: int) -> int:
    """Get member count for a group."""
    result = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
    )
    return result.scalar() or 0


async def _build_group_response(group: Group, db: DbSession) -> GroupResponse:
    """Build a GroupResponse with member count and resolved cover image URL."""
    member_count = await _get_group_member_count(db, group.id)

    # Resolve cover image to signed URL
    cover_image_url = None
    if group.cover_image:
        cover_image_url = await StorageService.get_signed_url(group.cover_image, expires_in=3600)

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        privacy=group.privacy,
        category=group.category,
        cover_image=cover_image_url,
        created_at=group.created_at,
        created_by_id=group.created_by_id,
        member_count=member_count,
    )


# ============== Group CRUD ==============

@router.post(
    "",
    response_model=GroupResponse,
    status_code=201,
    summary="Create a new group",
)
async def create_group(
    group_data: GroupCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Create a new group.

    The creator automatically becomes an admin member.
    """
    # Create group
    group = Group(
        name=group_data.name,
        description=group_data.description,
        privacy=group_data.privacy,
        category=group_data.category,
        created_by_id=current_user.id,
    )
    db.add(group)
    await db.flush()

    # Add creator as admin member
    member = GroupMember(
        group_id=group.id,
        user_id=current_user.id,
        role="admin",
    )
    db.add(member)
    await db.commit()
    await db.refresh(group)

    return await _build_group_response(group, db)


@router.get(
    "",
    response_model=GroupListResponse,
    summary="List all groups",
)
async def list_groups(
    db: DbSession,
    current_user: OptionalUser = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str = Query(None, description="Filter by category"),
    search: str = Query(None, description="Search by name"),
):
    """List all public groups with optional filters."""
    # Build query
    query = select(Group).where(Group.privacy == "public")
    count_query = select(func.count()).select_from(Group).where(Group.privacy == "public")

    if category:
        query = query.where(Group.category == category)
        count_query = count_query.where(Group.category == category)

    if search:
        query = query.where(Group.name.ilike(f"%{search}%"))
        count_query = count_query.where(Group.name.ilike(f"%{search}%"))

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated groups
    offset = (page - 1) * per_page
    result = await db.execute(
        query
        .order_by(Group.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    groups = result.scalars().all()

    # Build responses
    group_responses = []
    for group in groups:
        group_responses.append(await _build_group_response(group, db))

    return GroupListResponse(
        groups=group_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


@router.get(
    "/my-groups",
    response_model=GroupListResponse,
    summary="List groups I'm a member of",
)
async def list_my_groups(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List all groups the current user is a member of."""
    # Get user's group IDs
    membership_query = select(GroupMember.group_id).where(
        GroupMember.user_id == current_user.id
    )

    # Count total
    count_result = await db.execute(
        select(func.count()).select_from(GroupMember).where(
            GroupMember.user_id == current_user.id
        )
    )
    total = count_result.scalar() or 0

    # Get paginated groups
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Group)
        .where(Group.id.in_(membership_query))
        .order_by(Group.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    groups = result.scalars().all()

    # Build responses
    group_responses = []
    for group in groups:
        group_responses.append(await _build_group_response(group, db))

    return GroupListResponse(
        groups=group_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
        has_prev=page > 1,
    )


@router.get(
    "/{group_id}",
    response_model=GroupDetailResponse,
    summary="Get group details",
)
async def get_group(
    group_id: int,
    db: DbSession,
    current_user: OptionalUser = None,
):
    """Get detailed group information including members and recent messages."""
    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    # Check access for private groups
    is_member = False
    user_role = None
    if current_user:
        member_result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == current_user.id
            )
        )
        membership = member_result.scalar_one_or_none()
        is_member = membership is not None
        user_role = membership.role if membership else None

    if group.privacy == "private" and not is_member:
        raise ForbiddenException("This is a private group")

    # Get members
    members_result = await db.execute(
        select(GroupMember)
        .options(selectinload(GroupMember.user))
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
        .limit(50)
    )
    members = members_result.scalars().all()

    # Get online users
    online_user_ids = manager.get_online_users(group_id)

    # Build member responses with resolved profile pictures
    member_responses = []
    for m in members:
        profile_url = await StorageService.resolve_profile_picture(m.user.profile_picture)
        member_responses.append(
            GroupMemberResponse(
                user_id=m.user.id,
                username=m.user.username,
                profile_picture=profile_url,
                role=m.role,
                joined_at=m.joined_at,
                is_online=m.user.id in online_user_ids,
            )
        )

    # Get recent messages
    messages_result = await db.execute(
        select(GroupMessage)
        .options(selectinload(GroupMessage.user))
        .where(GroupMessage.group_id == group_id)
        .order_by(GroupMessage.created_at.desc())
        .limit(50)
    )
    messages = messages_result.scalars().all()

    # Build message responses with resolved profile pictures and image URLs
    message_responses = []
    for m in reversed(messages):  # Oldest first
        profile_url = await StorageService.resolve_profile_picture(m.user.profile_picture)
        # Resolve message image URL if present
        message_image_url = None
        if m.image_url:
            message_image_url = await StorageService.get_signed_url(m.image_url, expires_in=3600)
        message_responses.append(
            GroupMessageResponse(
                id=m.id,
                content=m.content,
                image_url=message_image_url,
                created_at=m.created_at,
                user_id=m.user.id,
                username=m.user.username,
                profile_picture=profile_url,
            )
        )

    return GroupDetailResponse(
        group=await _build_group_response(group, db),
        members=member_responses,
        recent_messages=message_responses,
        is_member=is_member,
        user_role=user_role,
    )


@router.patch(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Update a group",
)
async def update_group(
    group_id: int,
    update_data: GroupUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    """Update group settings. Only admins can update."""
    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    # Check if user is admin
    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin"
        )
    )
    if not member_result.scalar_one_or_none():
        raise ForbiddenException("Only admins can update the group")

    # Update fields
    if update_data.name is not None:
        group.name = update_data.name
    if update_data.description is not None:
        group.description = update_data.description
    if update_data.privacy is not None:
        group.privacy = update_data.privacy
    if update_data.category is not None:
        group.category = update_data.category
    if update_data.cover_image is not None:
        group.cover_image = update_data.cover_image

    await db.commit()
    await db.refresh(group)

    return await _build_group_response(group, db)


@router.delete(
    "/{group_id}",
    response_model=MessageResponse,
    summary="Delete a group",
)
async def delete_group(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Delete a group. Only the creator can delete."""
    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    if group.created_by_id != current_user.id:
        raise ForbiddenException("Only the creator can delete the group")

    await db.delete(group)
    await db.commit()

    return MessageResponse(message="Group deleted successfully")


@router.post(
    "/{group_id}/cover",
    response_model=GroupResponse,
    summary="Upload group cover image",
)
async def upload_group_cover(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    """
    Upload a cover image for the group.

    - Only admins can upload cover images
    - Accepts JPG, PNG, WebP, and GIF images
    - Maximum file size: 5MB
    """
    settings = get_settings()

    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    # Check if user is admin
    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin"
        )
    )
    if not member_result.scalar_one_or_none():
        raise ForbiddenException("Only admins can upload cover images")

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
        bucket = "groups_cover_images"

        # Generate unique filename
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{group_id}_{uuid.uuid4()}.{file_ext}"

        # Upload to Supabase Storage via REST API
        upload_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{filename}"

        async with httpx.AsyncClient() as client:
            # Delete old cover image if exists
            if group.cover_image:
                try:
                    old_path = group.cover_image
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

        # Store the path
        group.cover_image = f"{bucket}/{filename}"
        await db.commit()
        await db.refresh(group)

        return await _build_group_response(group, db)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )


@router.post(
    "/{group_id}/messages/image",
    summary="Upload image for group message",
)
async def upload_message_image(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    """
    Upload an image to be sent in a group message.

    - Only group members can upload images
    - Accepts JPG, PNG, WebP, and GIF images
    - Maximum file size: 5MB
    - Returns the image URL to be used in the message
    """
    settings = get_settings()

    # Verify membership
    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise ForbiddenException("Not a member of this group")

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
        bucket = "group_message_images"

        # Generate unique filename
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{group_id}/{current_user.id}_{uuid.uuid4()}.{file_ext}"

        # Upload to Supabase Storage via REST API
        upload_url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{filename}"

        async with httpx.AsyncClient() as client:
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

        # Get signed URL for the uploaded image
        image_path = f"{bucket}/{filename}"
        signed_url = await StorageService.get_signed_url(image_path, expires_in=86400)  # 24 hours

        return {"image_url": signed_url, "image_path": image_path}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image: {str(e)}"
        )


# ============== Membership ==============

@router.post(
    "/{group_id}/join",
    response_model=MessageResponse,
    summary="Join a group",
)
async def join_group(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Join a public group."""
    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    if group.privacy == "private":
        raise ForbiddenException("Cannot join a private group without invitation")

    # Check if already a member
    existing = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictException("Already a member of this group")

    # Add as member
    member = GroupMember(
        group_id=group_id,
        user_id=current_user.id,
        role="member",
    )
    db.add(member)
    await db.commit()

    return MessageResponse(message=f"Joined group '{group.name}'")


@router.post(
    "/{group_id}/leave",
    response_model=MessageResponse,
    summary="Leave a group",
)
async def leave_group(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """Leave a group."""
    # Get membership
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise BadRequestException("Not a member of this group")

    # Get group to check if user is creator
    group_result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = group_result.scalar_one()

    if group.created_by_id == current_user.id:
        raise BadRequestException("Group creator cannot leave. Delete the group instead.")

    await db.delete(membership)
    await db.commit()

    return MessageResponse(message="Left the group")


@router.get(
    "/{group_id}/members",
    response_model=GroupMemberListResponse,
    summary="Get group members",
)
async def get_group_members(
    group_id: int,
    db: DbSession,
    current_user: OptionalUser = None,
):
    """Get all members of a group."""
    # Get group
    result = await db.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise NotFoundException("Group not found")

    # Check access for private groups
    if group.privacy == "private" and current_user:
        member_check = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == current_user.id
            )
        )
        if not member_check.scalar_one_or_none():
            raise ForbiddenException("This is a private group")

    # Get members
    members_result = await db.execute(
        select(GroupMember)
        .options(selectinload(GroupMember.user))
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
    )
    members = members_result.scalars().all()

    # Get online users
    online_user_ids = manager.get_online_users(group_id)

    # Build member responses with resolved profile pictures
    member_responses = []
    for m in members:
        profile_url = await StorageService.resolve_profile_picture(m.user.profile_picture)
        member_responses.append(
            GroupMemberResponse(
                user_id=m.user.id,
                username=m.user.username,
                profile_picture=profile_url,
                role=m.role,
                joined_at=m.joined_at,
                is_online=m.user.id in online_user_ids,
            )
        )

    return GroupMemberListResponse(
        members=member_responses,
        total=len(member_responses),
    )


# ============== Messages ==============

@router.get(
    "/{group_id}/messages",
    response_model=GroupMessageListResponse,
    summary="Get group messages",
)
async def get_group_messages(
    group_id: int,
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    """Get paginated messages for a group. Must be a member."""
    # Verify membership
    member_result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id
        )
    )
    if not member_result.scalar_one_or_none():
        raise ForbiddenException("Not a member of this group")

    # Get total
    total_result = await db.execute(
        select(func.count()).select_from(GroupMessage).where(
            GroupMessage.group_id == group_id
        )
    )
    total = total_result.scalar() or 0

    # Get paginated messages (newest first, then reverse for display)
    offset = (page - 1) * per_page
    result = await db.execute(
        select(GroupMessage)
        .options(selectinload(GroupMessage.user))
        .where(GroupMessage.group_id == group_id)
        .order_by(GroupMessage.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    messages = result.scalars().all()

    # Build message responses with resolved profile pictures and image URLs
    message_responses = []
    for m in reversed(messages):
        profile_url = await StorageService.resolve_profile_picture(m.user.profile_picture)
        # Resolve message image URL if present
        message_image_url = None
        if m.image_url:
            message_image_url = await StorageService.get_signed_url(m.image_url, expires_in=3600)
        message_responses.append(
            GroupMessageResponse(
                id=m.id,
                content=m.content,
                image_url=message_image_url,
                created_at=m.created_at,
                user_id=m.user.id,
                username=m.user.username,
                profile_picture=profile_url,
            )
        )

    return GroupMessageListResponse(
        messages=message_responses,
        total=total,
        page=page,
        per_page=per_page,
        has_next=offset + per_page < total,
    )
