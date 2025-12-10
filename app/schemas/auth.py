from pydantic import BaseModel, EmailStr, Field, field_validator
import re


class RegisterRequest(BaseModel):
    """Schema for user registration."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v.lower()


class LoginRequest(BaseModel):
    """Schema for user login."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for decoded JWT token payload."""
    sub: str  # username
    exp: int
    type: str  # "access" or "refresh"


class RefreshTokenRequest(BaseModel):
    """Schema for refreshing access token."""
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    """Schema for changing password."""
    current_password: str
    new_password: str = Field(..., min_length=6)


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class PasswordResetRequest(BaseModel):
    """Schema para solicitar reset de senha."""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema para confirmar reset de senha."""
    token: str
    new_password: str = Field(..., min_length=6)
