"""add listening sessions

Revision ID: f6680074ec8c
Revises: j0k1l2m3n4o5
Create Date: 2026-06-11 13:15:55.136167

NOTA: o autogenerate sugeriu drops de tabelas/índices que existem no banco
mas não no metadata (scrobbles, oauth_accounts, índices de performance
criados manualmente) — removidos daqui de propósito. Esta migração cria
apenas as tabelas da Listening Party.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6680074ec8c'
down_revision: Union[str, None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('listening_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('album_title', sa.String(length=300), nullable=False),
    sa.Column('album_artist', sa.String(length=300), nullable=False),
    sa.Column('album_cover_image', sa.String(length=500), nullable=True),
    sa.Column('album_spotify_id', sa.String(length=100), nullable=True),
    sa.Column('tracks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_track_index', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['host_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_listening_sessions_code'), 'listening_sessions', ['code'], unique=True)
    op.create_index(op.f('ix_listening_sessions_host_id'), 'listening_sessions', ['host_id'], unique=False)

    op.create_table('session_participants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['listening_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'user_id', name='unique_session_participant')
    )
    op.create_index(op.f('ix_session_participants_session_id'), 'session_participants', ['session_id'], unique=False)
    op.create_index(op.f('ix_session_participants_user_id'), 'session_participants', ['user_id'], unique=False)

    op.create_table('session_track_ratings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('track_index', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['listening_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'track_index', 'user_id', name='unique_session_track_vote')
    )
    op.create_index(op.f('ix_session_track_ratings_session_id'), 'session_track_ratings', ['session_id'], unique=False)
    op.create_index(op.f('ix_session_track_ratings_user_id'), 'session_track_ratings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_track_ratings_user_id'), table_name='session_track_ratings')
    op.drop_index(op.f('ix_session_track_ratings_session_id'), table_name='session_track_ratings')
    op.drop_table('session_track_ratings')
    op.drop_index(op.f('ix_session_participants_user_id'), table_name='session_participants')
    op.drop_index(op.f('ix_session_participants_session_id'), table_name='session_participants')
    op.drop_table('session_participants')
    op.drop_index(op.f('ix_listening_sessions_host_id'), table_name='listening_sessions')
    op.drop_index(op.f('ix_listening_sessions_code'), table_name='listening_sessions')
    op.drop_table('listening_sessions')
