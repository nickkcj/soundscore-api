"""Add group_invites table and group_invite_id to notifications

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create group_invites table first
    op.create_table(
        'group_invites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False, unique=True, index=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('invitee_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('inviter_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('token', sa.String(500), nullable=False, unique=True, index=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Add group_invite_id column to notifications
    op.add_column(
        'notifications',
        sa.Column('group_invite_id', sa.Integer(), nullable=True)
    )

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_notifications_group_invite_id',
        'notifications',
        'group_invites',
        ['group_invite_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Add index for faster lookups
    op.create_index('ix_notifications_group_invite_id', 'notifications', ['group_invite_id'])


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_notifications_group_invite_id', table_name='notifications')

    # Drop foreign key constraint
    op.drop_constraint('fk_notifications_group_invite_id', 'notifications', type_='foreignkey')

    # Drop column
    op.drop_column('notifications', 'group_invite_id')

    # Drop group_invites table
    op.drop_table('group_invites')
