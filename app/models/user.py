from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.review import Review, Comment, ReviewLike, CommentLike
    from app.models.feed import Notification
    from app.models.group import GroupMember, GroupMessage
    from app.models.chatbot import ChatMessage
    from app.models.oauth import OAuthAccount
    from app.models.scrobble import Scrobble


class User(Base):
    """User model for authentication and profiles."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Nullable for OAuth-only users

    # Profile
    profile_picture: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    banner_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Relationships
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    review_likes: Mapped[list["ReviewLike"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    comment_likes: Mapped[list["CommentLike"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    notifications_received: Mapped[list["Notification"]] = relationship(
        back_populates="recipient",
        foreign_keys="Notification.recipient_id",
        cascade="all, delete-orphan"
    )
    notifications_sent: Mapped[list["Notification"]] = relationship(
        back_populates="actor",
        foreign_keys="Notification.actor_id",
        cascade="all, delete-orphan"
    )
    group_memberships: Mapped[list["GroupMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    group_messages: Mapped[list["GroupMessage"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    scrobbles: Mapped[list["Scrobble"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # Self-referential relationships for follows
    following: Mapped[list["UserFollow"]] = relationship(
        back_populates="follower",
        foreign_keys="UserFollow.follower_id",
        cascade="all, delete-orphan"
    )
    followers: Mapped[list["UserFollow"]] = relationship(
        back_populates="following",
        foreign_keys="UserFollow.following_id",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class UserFollow(Base):
    """User follow/following relationship."""

    __tablename__ = "user_follows"

    id: Mapped[int] = mapped_column(primary_key=True)
    follower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    following_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Unique constraint: user can only follow someone once
    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="unique_follow"),
    )

    # Relationships
    follower: Mapped["User"] = relationship(
        back_populates="following",
        foreign_keys=[follower_id]
    )
    following: Mapped["User"] = relationship(
        back_populates="followers",
        foreign_keys=[following_id]
    )

    def __repr__(self) -> str:
        return f"<UserFollow {self.follower_id} -> {self.following_id}>"
