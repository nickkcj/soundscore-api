"""add push devices

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-08-20 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_push_devices_user_id"), "push_devices", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_push_devices_user_id"), table_name="push_devices")
    op.drop_table("push_devices")
