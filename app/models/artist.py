"""Artist model storing Spotify artist metadata and AI-generated bios."""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Artist(Base):
    """Artist model storing Spotify artist metadata."""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    genres: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Comma-separated
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI-generated bio

    def __repr__(self) -> str:
        return f"<Artist {self.name}>"
