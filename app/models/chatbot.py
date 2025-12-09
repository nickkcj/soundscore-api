from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ChatMessage(Base):
    """AI chatbot conversation history."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )

    # Conversation content
    message: Mapped[str] = mapped_column(Text)  # User's message
    response: Mapped[str] = mapped_column(Text)  # AI response

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="chat_messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.id} by {self.user_id}>"
