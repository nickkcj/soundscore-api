from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        subject: The subject (usually username) to encode in the token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT access token
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode = {
        "sub": subject,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    """
    Create a JWT refresh token.

    Args:
        subject: The subject (usually username) to encode in the token

    Returns:
        Encoded JWT refresh token
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    to_encode = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token to decode

    Returns:
        Decoded payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[str]:
    """
    Verify an access token and return the subject.

    Args:
        token: The JWT access token

    Returns:
        The subject (username) if valid, None otherwise
    """
    payload = decode_token(token)
    if payload is None:
        return None

    if payload.get("type") != "access":
        return None

    return payload.get("sub")


def verify_refresh_token(token: str) -> Optional[str]:
    """
    Verify a refresh token and return the subject.

    Args:
        token: The JWT refresh token

    Returns:
        The subject (username) if valid, None otherwise
    """
    payload = decode_token(token)
    if payload is None:
        return None

    if payload.get("type") != "refresh":
        return None

    return payload.get("sub")


def create_password_reset_token(email: str) -> str:
    """
    Create a JWT token for password reset.

    Args:
        email: The email address to encode in the token

    Returns:
        Encoded JWT password reset token
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_token_expire_minutes
    )
    to_encode = {
        "sub": email,
        "exp": expire,
        "type": "password_reset",
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_password_reset_token(token: str) -> Optional[str]:
    """
    Verify a password reset token and return the email.

    Args:
        token: The JWT password reset token

    Returns:
        The email if valid, None otherwise
    """
    payload = decode_token(token)
    if payload is None:
        return None

    if payload.get("type") != "password_reset":
        return None

    return payload.get("sub")
