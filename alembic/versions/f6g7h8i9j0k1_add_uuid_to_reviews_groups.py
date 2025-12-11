"""Add UUID columns to reviews and groups

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add uuid column to reviews (nullable first)
    op.add_column(
        'reviews',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Add uuid column to groups (nullable first)
    op.add_column(
        'groups',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Generate UUIDs for existing records using PostgreSQL's gen_random_uuid()
    op.execute("UPDATE reviews SET uuid = gen_random_uuid() WHERE uuid IS NULL")
    op.execute("UPDATE groups SET uuid = gen_random_uuid() WHERE uuid IS NULL")

    # Make columns non-nullable
    op.alter_column('reviews', 'uuid', nullable=False)
    op.alter_column('groups', 'uuid', nullable=False)

    # Add unique constraints
    op.create_unique_constraint('uq_reviews_uuid', 'reviews', ['uuid'])
    op.create_unique_constraint('uq_groups_uuid', 'groups', ['uuid'])

    # Create indexes for fast lookups
    op.create_index('ix_reviews_uuid', 'reviews', ['uuid'])
    op.create_index('ix_groups_uuid', 'groups', ['uuid'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_groups_uuid', table_name='groups')
    op.drop_index('ix_reviews_uuid', table_name='reviews')

    # Drop unique constraints
    op.drop_constraint('uq_groups_uuid', 'groups', type_='unique')
    op.drop_constraint('uq_reviews_uuid', 'reviews', type_='unique')

    # Drop columns
    op.drop_column('groups', 'uuid')
    op.drop_column('reviews', 'uuid')
