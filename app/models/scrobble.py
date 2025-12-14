from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, func, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Scrobble(Base):
    """Scrobble - a track played by a user."""

    __tablename__ = "scrobbles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    track_id: Mapped[str] = mapped_column(String(50))  # Spotify track ID
    track_name: Mapped[str] = mapped_column(String(255))
    artist_name: Mapped[str] = mapped_column(String(255))
    album_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    album_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "track_id", "played_at", name="unique_scrobble"),
    )

    # Relationship
    user: Mapped["User"] = relationship(back_populates="scrobbles")

    def __repr__(self) -> str:
        return f"<Scrobble {self.track_name} by {self.artist_name}>"
