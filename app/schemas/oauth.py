"""OAuth schemas."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class OAuthAccountResponse(BaseModel):
    """Response schema for OAuth account."""
    id: int
    provider: str
    provider_email: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class LinkedAccountsResponse(BaseModel):
    """Response schema for linked OAuth accounts."""
    google: Optional[OAuthAccountResponse] = None
    spotify: Optional[OAuthAccountResponse] = None
    has_password: bool


class OAuthExchangeRequest(BaseModel):
    """Single-use authorization code returned to a native client."""

    code: str = Field(..., min_length=32, max_length=256)
