"""
Listening Party: sala temporária para ouvir um álbum em grupo,
dar nota 0-10 por track às cegas e revelar quando todos votarem.

O áudio toca fora do app (Discord/Spotify de cada um) — aqui fica
o "placar": estado da sessão, votos e o reveal.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ListeningSession(Base):
    """Sala de listening party de um álbum."""

    __tablename__ = "listening_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Código curto usado na URL de convite (ex: /session/XK4P2)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)

    # Álbum: spotify_id é opcional de propósito — em lançamentos o álbum
    # muitas vezes ainda não está na API; o host cola a tracklist na mão
    # e vincula o spotify_id depois (destrava "publicar como review")
    album_title: Mapped[str] = mapped_column(String(300))
    album_artist: Mapped[str] = mapped_column(String(300))
    album_cover_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    album_spotify_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Lista de nomes das tracks, na ordem do álbum
    tracks: Mapped[list] = mapped_column(JSONB)

    host_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # lobby -> active -> finished
    status: Mapped[str] = mapped_column(String(20), default="lobby")
    current_track_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    host: Mapped["User"] = relationship(foreign_keys=[host_id])
    participants: Mapped[list["SessionParticipant"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["SessionTrackRating"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ListeningSession {self.code} - {self.album_title}>"


class SessionParticipant(Base):
    """Quem entrou na sala (host incluso)."""

    __tablename__ = "session_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="unique_session_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("listening_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ListeningSession"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship()


class SessionTrackRating(Base):
    """Voto de um participante em uma track (0-10 + comentário)."""

    __tablename__ = "session_track_ratings"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "track_index", "user_id", name="unique_session_track_vote"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("listening_sessions.id", ondelete="CASCADE"), index=True
    )
    track_index: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)  # 0-10
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ListeningSession"] = relationship(back_populates="ratings")
    user: Mapped["User"] = relationship()
