"""add scrobbles table and oauth tokens

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2024-12-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add token columns to oauth_accounts
    op.add_column('oauth_accounts', sa.Column('access_token', sa.Text(), nullable=True))
    op.add_column('oauth_accounts', sa.Column('refresh_token', sa.Text(), nullable=True))
    op.add_column('oauth_accounts', sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True))

    # Create scrobbles table
    op.create_table(
        'scrobbles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.String(50), nullable=False),
        sa.Column('track_name', sa.String(255), nullable=False),
        sa.Column('artist_name', sa.String(255), nullable=False),
        sa.Column('album_name', sa.String(255), nullable=True),
        sa.Column('album_image_url', sa.String(500), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('played_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'track_id', 'played_at', name='unique_scrobble'),
    )
    op.create_index('idx_scrobbles_user_played', 'scrobbles', ['user_id', 'played_at'])
    op.create_index('idx_scrobbles_user_artist', 'scrobbles', ['user_id', 'artist_name'])


def downgrade() -> None:
    # Drop scrobbles table
    op.drop_index('idx_scrobbles_user_artist', table_name='scrobbles')
    op.drop_index('idx_scrobbles_user_played', table_name='scrobbles')
    op.drop_table('scrobbles')

    # Remove token columns from oauth_accounts
    op.drop_column('oauth_accounts', 'token_expires_at')
    op.drop_column('oauth_accounts', 'refresh_token')
    op.drop_column('oauth_accounts', 'access_token')
