"""add oauth_accounts table

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2024-12-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create oauth_accounts table
    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('provider_user_id', sa.String(255), nullable=False),
        sa.Column('provider_email', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='unique_provider_account'),
        sa.UniqueConstraint('user_id', 'provider', name='unique_user_provider'),
    )
    op.create_index('idx_oauth_accounts_user_id', 'oauth_accounts', ['user_id'])
    op.create_index('idx_oauth_accounts_provider', 'oauth_accounts', ['provider', 'provider_user_id'])

    # Make password_hash nullable for OAuth-only users
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(255),
                    nullable=True)


def downgrade() -> None:
    # Make password_hash required again
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(255),
                    nullable=False)

    # Drop oauth_accounts table
    op.drop_index('idx_oauth_accounts_provider', table_name='oauth_accounts')
    op.drop_index('idx_oauth_accounts_user_id', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
