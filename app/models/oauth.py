from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class OAuthAccount(Base):
    """OAuth account linked to a user."""

    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    provider: Mapped[str] = mapped_column(String(20))  # 'google' or 'spotify'
    provider_user_id: Mapped[str] = mapped_column(String(255))
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # OAuth tokens (needed for Spotify API access)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="unique_provider_account"),
        UniqueConstraint("user_id", "provider", name="unique_user_provider"),
    )

    # Relationship
    user: Mapped["User"] = relationship(back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<OAuthAccount {self.provider}:{self.provider_user_id}>"
