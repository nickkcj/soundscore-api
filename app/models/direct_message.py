"""Direct message models for 1:1 conversations between users."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Conversation(Base):
    """1:1 conversation between two users."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user1_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    user2_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="unique_conversation"),
        CheckConstraint("user1_id < user2_id", name="ordered_user_ids"),
    )

    # Relationships
    user1: Mapped["User"] = relationship(foreign_keys=[user1_id])
    user2: Mapped["User"] = relationship(foreign_keys=[user2_id])
    messages: Mapped[list["DirectMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.user1_id} <-> {self.user2_id}>"


class DirectMessage(Base):
    """Message in a 1:1 conversation."""

    __tablename__ = "direct_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    content: Mapped[str] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<DirectMessage {self.id} in conversation {self.conversation_id}>"
