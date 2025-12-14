"""OAuth schemas."""

from pydantic import BaseModel
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
