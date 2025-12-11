import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.feed import Notification


class Album(Base):
    """Album model storing Spotify album metadata."""

    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    artist: Mapped[str] = mapped_column(String(255))
    cover_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    release_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-generated summary

    # Relationships
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="album",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Album {self.title} by {self.artist}>"


class Review(Base):
    """User review of an album."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid_lib.uuid4,
        unique=True,
        index=True,
        nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    album_id: Mapped[int] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"),
        index=True
    )

    # Review content
    rating: Mapped[int] = mapped_column(Integer)  # 1-5 stars
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Unique constraint: user can only review an album once
    __table_args__ = (
        UniqueConstraint("user_id", "album_id", name="unique_user_album_review"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="reviews")
    album: Mapped["Album"] = relationship(back_populates="reviews")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan"
    )
    likes: Mapped[list["ReviewLike"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Review {self.user_id} -> {self.album_id} ({self.rating}★)>"


class Comment(Base):
    """Comment on a review. Supports nested replies."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"),
        index=True
    )

    # Comment content
    text: Mapped[str] = mapped_column(Text)

    # Self-referential for nested replies
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="comments")
    review: Mapped["Review"] = relationship(back_populates="comments")
    parent: Mapped[Optional["Comment"]] = relationship(
        back_populates="replies",
        remote_side="Comment.id"
    )
    replies: Mapped[list["Comment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan"
    )
    likes: Mapped[list["CommentLike"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Comment {self.id} by {self.user_id}>"


class ReviewLike(Base):
    """Like on a review."""

    __tablename__ = "review_likes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Unique constraint: user can only like a review once
    __table_args__ = (
        UniqueConstraint("user_id", "review_id", name="unique_user_review_like"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="review_likes")
    review: Mapped["Review"] = relationship(back_populates="likes")

    def __repr__(self) -> str:
        return f"<ReviewLike {self.user_id} -> {self.review_id}>"


class CommentLike(Base):
    """Like on a comment."""

    __tablename__ = "comment_likes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Unique constraint: user can only like a comment once
    __table_args__ = (
        UniqueConstraint("user_id", "comment_id", name="unique_user_comment_like"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="comment_likes")
    comment: Mapped["Comment"] = relationship(back_populates="likes")

    def __repr__(self) -> str:
        return f"<CommentLike {self.user_id} -> {self.comment_id}>"
