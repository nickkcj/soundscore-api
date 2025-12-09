"""add_summary_to_albums

Revision ID: a1b2c3d4e5f6
Revises: 9316d8665695
Create Date: 2025-12-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9316d8665695'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('albums', sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('albums', 'summary')
