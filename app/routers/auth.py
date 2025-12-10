from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    TokenResponse,
    RefreshTokenRequest,
    PasswordChangeRequest,
    MessageResponse,
    PasswordResetRequest,
    PasswordResetConfirm,
)
from app.schemas.user import UserResponse
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
)
from app.core.exceptions import (
    BadRequestException,
    UnauthorizedException,
    ConflictException,
)
from app.dependencies import CurrentUser, DbSession
from app.services.storage_service import StorageService
from app.services.email_service import email_service

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(request: RegisterRequest, db: DbSession):
    """
    Register a new user account.

    - **username**: Unique username (3-50 chars, alphanumeric + underscore)
    - **email**: Valid email address
    - **password**: Password (min 6 characters)
    """
    # Check if username already exists
    result = await db.execute(
        select(User).where(User.username == request.username.lower())
    )
    if result.scalar_one_or_none():
        raise ConflictException("Username already taken")

    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    if result.scalar_one_or_none():
        raise ConflictException("Email already registered")

    # Create new user
    user = User(
        username=request.username.lower(),
        email=request.email.lower(),
        password_hash=hash_password(request.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and get JWT tokens",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return JWT tokens.

    Uses OAuth2 password flow:
    - **username**: Your username
    - **password**: Your password

    Returns access_token and refresh_token.
    """
    # Find user by username
    result = await db.execute(
        select(User).where(User.username == form_data.username.lower())
    )
    user = result.scalar_one_or_none()

    # Verify credentials
    if not user or not verify_password(form_data.password, user.password_hash):
        raise UnauthorizedException("Incorrect username or password")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Generate tokens
    access_token = create_access_token(subject=user.username)
    refresh_token = create_refresh_token(subject=user.username)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(request: RefreshTokenRequest, db: DbSession):
    """
    Get a new access token using a refresh token.

    - **refresh_token**: Valid refresh token from login
    """
    username = verify_refresh_token(request.refresh_token)
    if username is None:
        raise UnauthorizedException("Invalid or expired refresh token")

    # Verify user still exists and is active
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise UnauthorizedException("User not found")

    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    # Generate new tokens
    access_token = create_access_token(subject=user.username)
    new_refresh_token = create_refresh_token(subject=user.username)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change user password",
)
async def change_password(
    request: PasswordChangeRequest,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Change the current user's password.

    - **current_password**: Your current password
    - **new_password**: New password (min 6 characters)
    """
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise BadRequestException("Current password is incorrect")

    # Update password
    current_user.password_hash = hash_password(request.new_password)
    await db.commit()

    return MessageResponse(message="Password changed successfully")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user info",
)
async def get_me(current_user: CurrentUser):
    """
    Get the currently authenticated user's information.
    """
    # Resolve profile picture to signed URL
    profile_picture_url = await StorageService.resolve_profile_picture(current_user.profile_picture)

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        profile_picture=profile_picture_url,
        bio=current_user.bio,
        created_at=current_user.created_at,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
)
async def forgot_password(request: PasswordResetRequest, db: DbSession):
    """
    Request a password reset email.

    - **email**: The email address associated with your account

    Note: For security reasons, this endpoint always returns success
    even if the email doesn't exist in our system.
    """
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    user = result.scalar_one_or_none()

    # Always return success message (security: don't reveal if email exists)
    if user and user.is_active:
        # Generate reset token
        reset_token = create_password_reset_token(user.email)

        # Send email
        await email_service.send_password_reset_email(user.email, reset_token)

    return MessageResponse(
        message="If an account with this email exists, you will receive a password reset link shortly."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with token",
)
async def reset_password(request: PasswordResetConfirm, db: DbSession):
    """
    Reset password using a valid reset token.

    - **token**: The password reset token from the email
    - **new_password**: Your new password (min 6 characters)
    """
    # Verify the token
    email = verify_password_reset_token(request.token)
    if email is None:
        raise BadRequestException("Invalid or expired reset token")

    # Find the user
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise BadRequestException("Invalid or expired reset token")

    if not user.is_active:
        raise BadRequestException("User account is inactive")

    # Update password
    user.password_hash = hash_password(request.new_password)
    await db.commit()

    return MessageResponse(message="Password has been reset successfully")
