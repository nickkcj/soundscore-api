from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.review import Review, Comment


class Notification(Base):
    """User notification for reviews, comments, likes, follows."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Who receives the notification
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )

    # Who triggered the notification
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )

    # Notification type: "like", "comment", "follow", "review"
    notification_type: Mapped[str] = mapped_column(String(50), index=True)

    # Optional references to related content
    review_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    comment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Notification message
    message: Mapped[str] = mapped_column(Text)

    # Status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # Relationships
    recipient: Mapped["User"] = relationship(
        back_populates="notifications_received",
        foreign_keys=[recipient_id]
    )
    actor: Mapped["User"] = relationship(
        back_populates="notifications_sent",
        foreign_keys=[actor_id]
    )
    review: Mapped[Optional["Review"]] = relationship(back_populates="notifications")
    comment: Mapped[Optional["Comment"]] = relationship(back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.notification_type} for {self.recipient_id}>"
