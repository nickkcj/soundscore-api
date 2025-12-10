"""Add performance indexes

Revision ID: d4e5f6g7h8i9
Revises: b2c3d4e5f6g7
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for faster notification queries (unread by recipient)
    op.create_index(
        'ix_notifications_recipient_read_created',
        'notifications',
        ['recipient_id', 'is_read', 'created_at'],
        postgresql_ops={'created_at': 'DESC'},
        if_not_exists=True
    )

    # Composite index for faster review duplicate check
    op.create_index(
        'ix_reviews_user_album',
        'reviews',
        ['user_id', 'album_id'],
        unique=True,
        if_not_exists=True
    )

    # Index for faster chatbot message pagination
    op.create_index(
        'ix_chat_messages_user_created',
        'chat_messages',
        ['user_id', 'created_at'],
        postgresql_ops={'created_at': 'DESC'},
        if_not_exists=True
    )

    # Index for faster review likes count queries
    op.create_index(
        'ix_review_likes_review_id',
        'review_likes',
        ['review_id'],
        if_not_exists=True
    )

    # Index for faster comment count queries
    op.create_index(
        'ix_comments_review_id',
        'comments',
        ['review_id'],
        if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index('ix_comments_review_id', table_name='comments')
    op.drop_index('ix_review_likes_review_id', table_name='review_likes')
    op.drop_index('ix_chat_messages_user_created', table_name='chat_messages')
    op.drop_index('ix_reviews_user_album', table_name='reviews')
    op.drop_index('ix_notifications_recipient_read_created', table_name='notifications')
