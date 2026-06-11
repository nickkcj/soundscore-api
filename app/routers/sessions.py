"""
Listening Party — rotas da sala de escuta em grupo.

Regras centrais:
- Notas 0-10 por track, às cegas: as notas dos outros só aparecem no
  estado quando a track está "revelada" (todos os participantes votaram
  ou o host já avançou além dela). O anti-cheat é server-side: o GET de
  estado simplesmente não inclui o que ainda não foi revelado.
- O áudio toca fora do app; aqui é o placar. A sincronização entre
  clientes acontece via canal Supabase (Presence + broadcasts disparados
  pelos próprios clients após cada ação REST).
"""
import secrets
import string
from datetime import datetime, timezone
from statistics import pstdev
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.listening_session import (
    ListeningSession,
    SessionParticipant,
    SessionTrackRating,
)
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    BadRequestException,
    ConflictException,
)
from app.dependencies import CurrentUser, DbSession
from app.services.storage_service import StorageService

router = APIRouter()

# Sem caracteres ambíguos (0/O, 1/I/L)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_TRACKS = 60


# ============== Schemas ==============

class SessionCreate(BaseModel):
    album_title: str = Field(..., min_length=1, max_length=300)
    album_artist: str = Field(..., min_length=1, max_length=300)
    album_cover_image: Optional[str] = Field(None, max_length=500)
    album_spotify_id: Optional[str] = Field(None, max_length=100)
    tracks: list[str] = Field(..., min_length=1, max_length=MAX_TRACKS)


class RatingSubmit(BaseModel):
    track_index: int = Field(..., ge=0)
    rating: int = Field(..., ge=0, le=10)
    comment: Optional[str] = Field(None, max_length=1000)


class LinkSpotify(BaseModel):
    spotify_id: str = Field(..., min_length=1, max_length=100)


class ParticipantOut(BaseModel):
    user_id: int
    username: str
    profile_picture: Optional[str] = None
    is_host: bool = False


class RevealedRating(BaseModel):
    user_id: int
    username: str
    rating: int
    comment: Optional[str] = None


class TrackState(BaseModel):
    index: int
    name: str
    revealed: bool
    votes_count: int
    my_rating: Optional[int] = None
    my_comment: Optional[str] = None
    # Só preenchido quando revealed=True
    ratings: list[RevealedRating] = []
    avg_rating: Optional[float] = None


class SessionSummary(BaseModel):
    """Estatísticas do gran finale (status=finished)."""
    avg_by_track: list[Optional[float]]
    avg_by_user: list[dict]  # {user_id, username, avg}
    best_track_index: Optional[int] = None
    most_divisive_track_index: Optional[int] = None
    album_avg: Optional[float] = None


class SessionState(BaseModel):
    code: str
    status: str
    album_title: str
    album_artist: str
    album_cover_image: Optional[str]
    album_spotify_id: Optional[str]
    host_id: int
    is_host: bool
    is_participant: bool
    current_track_index: int
    created_at: datetime
    participants: list[ParticipantOut]
    tracks: list[TrackState]
    summary: Optional[SessionSummary] = None


class SessionListItem(BaseModel):
    code: str
    status: str
    album_title: str
    album_artist: str
    album_cover_image: Optional[str]
    participants_count: int
    created_at: datetime


# ============== Helpers ==============

async def _get_session(db, code: str) -> ListeningSession:
    result = await db.execute(
        select(ListeningSession)
        .options(
            selectinload(ListeningSession.participants).selectinload(SessionParticipant.user),
            selectinload(ListeningSession.ratings).selectinload(SessionTrackRating.user),
        )
        # populate_existing: refetch dentro do mesmo request recarrega as
        # relações (sem isso, o estado retornado após um INSERT vem stale)
        .execution_options(populate_existing=True)
        .where(ListeningSession.code == code.upper())
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundException("Session not found")
    return session


def _is_revealed(session: ListeningSession, track_index: int, votes: int) -> bool:
    """Track revelada: host avançou além dela, sessão acabou, ou todos votaram."""
    if session.status == "finished":
        return True
    if track_index < session.current_track_index:
        return True
    participant_count = len(session.participants)
    return participant_count > 0 and votes >= participant_count


async def _build_state(db, session: ListeningSession, user_id: int) -> SessionState:
    participant_ids = {p.user_id for p in session.participants}
    is_participant = user_id in participant_ids

    participants = []
    for p in session.participants:
        pic = await StorageService.resolve_profile_picture(p.user.profile_picture)
        participants.append(ParticipantOut(
            user_id=p.user_id,
            username=p.user.username,
            profile_picture=pic,
            is_host=p.user_id == session.host_id,
        ))

    # Agrupa votos por track
    by_track: dict[int, list[SessionTrackRating]] = {}
    for r in session.ratings:
        by_track.setdefault(r.track_index, []).append(r)

    tracks: list[TrackState] = []
    for i, name in enumerate(session.tracks):
        votes = by_track.get(i, [])
        revealed = _is_revealed(session, i, len(votes))
        mine = next((r for r in votes if r.user_id == user_id), None)

        state = TrackState(
            index=i,
            name=name,
            revealed=revealed,
            votes_count=len(votes),
            my_rating=mine.rating if mine else None,
            my_comment=mine.comment if mine else None,
        )
        if revealed and votes:
            state.ratings = [
                RevealedRating(
                    user_id=r.user_id,
                    username=r.user.username,
                    rating=r.rating,
                    comment=r.comment,
                )
                for r in sorted(votes, key=lambda r: r.user_id)
            ]
            state.avg_rating = round(sum(r.rating for r in votes) / len(votes), 1)
        tracks.append(state)

    summary = None
    if session.status == "finished":
        summary = _build_summary(session, by_track)

    return SessionState(
        code=session.code,
        status=session.status,
        album_title=session.album_title,
        album_artist=session.album_artist,
        album_cover_image=session.album_cover_image,
        album_spotify_id=session.album_spotify_id,
        host_id=session.host_id,
        is_host=user_id == session.host_id,
        is_participant=is_participant,
        current_track_index=session.current_track_index,
        created_at=session.created_at,
        participants=participants,
        tracks=tracks,
        summary=summary,
    )


def _build_summary(session: ListeningSession, by_track: dict) -> SessionSummary:
    n_tracks = len(session.tracks)

    avg_by_track: list[Optional[float]] = []
    divisiveness: list[Optional[float]] = []
    for i in range(n_tracks):
        votes = [r.rating for r in by_track.get(i, [])]
        avg_by_track.append(round(sum(votes) / len(votes), 1) if votes else None)
        divisiveness.append(round(pstdev(votes), 2) if len(votes) > 1 else None)

    user_votes: dict[int, list[SessionTrackRating]] = {}
    for votes in by_track.values():
        for r in votes:
            user_votes.setdefault(r.user_id, []).append(r)
    avg_by_user = [
        {
            "user_id": uid,
            "username": votes[0].user.username,
            "avg": round(sum(r.rating for r in votes) / len(votes), 1),
        }
        for uid, votes in user_votes.items()
    ]

    rated = [(i, avg) for i, avg in enumerate(avg_by_track) if avg is not None]
    best = max(rated, key=lambda x: x[1])[0] if rated else None
    contested = [(i, d) for i, d in enumerate(divisiveness) if d is not None]
    divisive = max(contested, key=lambda x: x[1])[0] if contested else None
    all_avgs = [avg for _, avg in rated]
    album_avg = round(sum(all_avgs) / len(all_avgs), 1) if all_avgs else None

    return SessionSummary(
        avg_by_track=avg_by_track,
        avg_by_user=sorted(avg_by_user, key=lambda u: -u["avg"]),
        best_track_index=best,
        most_divisive_track_index=divisive,
        album_avg=album_avg,
    )


# ============== Routes ==============

@router.post("", response_model=SessionState, status_code=201, summary="Create listening session")
async def create_session(data: SessionCreate, current_user: CurrentUser, db: DbSession):
    tracks = [t.strip() for t in data.tracks if t.strip()]
    if not tracks:
        raise BadRequestException("Tracklist cannot be empty")

    # Gera código único (tentativas suficientes para nunca colidir na prática)
    for _ in range(10):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        exists = await db.execute(
            select(ListeningSession.id).where(ListeningSession.code == code)
        )
        if not exists.scalar_one_or_none():
            break
    else:
        raise ConflictException("Could not generate session code, try again")

    session = ListeningSession(
        code=code,
        album_title=data.album_title.strip(),
        album_artist=data.album_artist.strip(),
        album_cover_image=data.album_cover_image,
        album_spotify_id=data.album_spotify_id,
        tracks=tracks,
        host_id=current_user.id,
    )
    db.add(session)
    await db.flush()
    db.add(SessionParticipant(session_id=session.id, user_id=current_user.id))
    await db.flush()

    session = await _get_session(db, code)
    return await _build_state(db, session, current_user.id)


@router.get("/mine", response_model=list[SessionListItem], summary="My sessions")
async def my_sessions(current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(ListeningSession, func.count(SessionParticipant.id))
        .join(SessionParticipant, SessionParticipant.session_id == ListeningSession.id)
        .where(ListeningSession.id.in_(
            select(SessionParticipant.session_id).where(
                SessionParticipant.user_id == current_user.id
            )
        ))
        .group_by(ListeningSession.id)
        .order_by(ListeningSession.created_at.desc())
        .limit(30)
    )
    return [
        SessionListItem(
            code=s.code,
            status=s.status,
            album_title=s.album_title,
            album_artist=s.album_artist,
            album_cover_image=s.album_cover_image,
            participants_count=count,
            created_at=s.created_at,
        )
        for s, count in result.all()
    ]


@router.get("/{code}", response_model=SessionState, summary="Get session state")
async def get_session_state(code: str, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    return await _build_state(db, session, current_user.id)


@router.post("/{code}/join", response_model=SessionState, summary="Join session")
async def join_session(code: str, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.status == "finished":
        raise BadRequestException("This session has already finished")

    already = any(p.user_id == current_user.id for p in session.participants)
    if not already:
        db.add(SessionParticipant(session_id=session.id, user_id=current_user.id))
        await db.flush()
        session = await _get_session(db, code)

    return await _build_state(db, session, current_user.id)


@router.post("/{code}/start", response_model=SessionState, summary="Start session (host)")
async def start_session(code: str, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.host_id != current_user.id:
        raise ForbiddenException("Only the host can start the session")
    if session.status != "lobby":
        raise BadRequestException("Session already started")

    session.status = "active"
    session.current_track_index = 0
    await db.flush()
    return await _build_state(db, session, current_user.id)


@router.post("/{code}/ratings", response_model=SessionState, summary="Submit track rating")
async def submit_rating(code: str, data: RatingSubmit, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.status != "active":
        raise BadRequestException("Session is not active")
    if not any(p.user_id == current_user.id for p in session.participants):
        raise ForbiddenException("Join the session before voting")
    if data.track_index >= len(session.tracks):
        raise BadRequestException("Invalid track index")
    if data.track_index > session.current_track_index:
        raise BadRequestException("Cannot vote on a future track")

    existing = next(
        (r for r in session.ratings
         if r.user_id == current_user.id and r.track_index == data.track_index),
        None,
    )
    if existing:
        # Permite editar só enquanto a track não foi revelada
        votes = sum(1 for r in session.ratings if r.track_index == data.track_index)
        if _is_revealed(session, data.track_index, votes):
            raise ConflictException("This track has already been revealed")
        existing.rating = data.rating
        existing.comment = data.comment
    else:
        db.add(SessionTrackRating(
            session_id=session.id,
            track_index=data.track_index,
            user_id=current_user.id,
            rating=data.rating,
            comment=data.comment,
        ))
    await db.flush()

    session = await _get_session(db, code)
    return await _build_state(db, session, current_user.id)


@router.post("/{code}/advance", response_model=SessionState, summary="Next track (host)")
async def advance_track(code: str, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.host_id != current_user.id:
        raise ForbiddenException("Only the host can advance tracks")
    if session.status != "active":
        raise BadRequestException("Session is not active")

    if session.current_track_index >= len(session.tracks) - 1:
        session.status = "finished"
        session.finished_at = datetime.now(timezone.utc)
    else:
        session.current_track_index += 1
    await db.flush()
    return await _build_state(db, session, current_user.id)


@router.post("/{code}/finish", response_model=SessionState, summary="End session early (host)")
async def finish_session(code: str, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.host_id != current_user.id:
        raise ForbiddenException("Only the host can finish the session")
    if session.status == "finished":
        raise BadRequestException("Session already finished")

    session.status = "finished"
    session.finished_at = datetime.now(timezone.utc)
    await db.flush()
    return await _build_state(db, session, current_user.id)


@router.post("/{code}/link-spotify", response_model=SessionState, summary="Link Spotify album (host)")
async def link_spotify(code: str, data: LinkSpotify, current_user: CurrentUser, db: DbSession):
    session = await _get_session(db, code)
    if session.host_id != current_user.id:
        raise ForbiddenException("Only the host can link the album")

    session.album_spotify_id = data.spotify_id
    await db.flush()
    return await _build_state(db, session, current_user.id)
