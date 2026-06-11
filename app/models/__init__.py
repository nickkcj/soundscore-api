# Import all models so Alembic can detect them
from app.models.user import User, UserFollow
from app.models.review import Album, Review, Comment, ReviewLike
from app.models.feed import Notification
from app.models.group import Group, GroupMember, GroupMessage, GroupInvite
from app.models.chatbot import ChatMessage
from app.models.artist import Artist
from app.models.direct_message import Conversation, DirectMessage
from app.models.listening_session import (
    ListeningSession,
    SessionParticipant,
    SessionTrackRating,
)

__all__ = [
    "User",
    "UserFollow",
    "Album",
    "Review",
    "Comment",
    "ReviewLike",
    "Notification",
    "Group",
    "GroupMember",
    "GroupMessage",
    "GroupInvite",
    "ChatMessage",
    "Artist",
    "Conversation",
    "DirectMessage",
    "ListeningSession",
    "SessionParticipant",
    "SessionTrackRating",
]
