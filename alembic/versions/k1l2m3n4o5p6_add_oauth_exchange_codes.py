"""add oauth exchange codes

Revision ID: k1l2m3n4o5p6
Revises: f6680074ec8c
Create Date: 2026-08-13 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "f6680074ec8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_exchange_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_oauth_exchange_codes_user_id", "oauth_exchange_codes", ["user_id"], unique=False)
    op.create_index("ix_oauth_exchange_codes_expires_at", "oauth_exchange_codes", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_oauth_exchange_codes_expires_at", table_name="oauth_exchange_codes")
    op.drop_index("ix_oauth_exchange_codes_user_id", table_name="oauth_exchange_codes")
    op.drop_table("oauth_exchange_codes")
