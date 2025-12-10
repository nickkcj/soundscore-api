"""Add image_url to group_messages

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'group_messages',
        sa.Column('image_url', sa.String(500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('group_messages', 'image_url')
