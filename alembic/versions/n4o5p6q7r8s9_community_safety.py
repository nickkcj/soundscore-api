"""Community safety records and realtime visibility for blocked users."""
from alembic import op
import sqlalchemy as sa

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("user_blocks",
        sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("blocker_id <> blocked_id", name="no_self_block"))
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])
    op.create_table("terms_acceptances",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.String(32), primary_key=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("content_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("details", sa.Text()), sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("resolution", sa.Text()),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("reporter_id", "target_type", "target_id", name="unique_content_report"))
    op.create_index("ix_content_reports_status", "content_reports", ["status"])
    # Deny direct access through Supabase; only the authenticated API accesses these records.
    for table in ("user_blocks", "terms_acceptances", "content_reports"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE FUNCTION public.soundscore_can_interact(other_id bigint)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
          SELECT EXISTS (SELECT 1 FROM public.users WHERE id = public.soundscore_realtime_user_id() AND is_active)
          AND NOT EXISTS (SELECT 1 FROM public.user_blocks WHERE
            (blocker_id = public.soundscore_realtime_user_id() AND blocked_id = other_id)
            OR (blocked_id = public.soundscore_realtime_user_id() AND blocker_id = other_id))
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.soundscore_is_conversation_participant(target_conversation_id bigint)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
          SELECT EXISTS (SELECT 1 FROM public.conversations c
            WHERE c.id = target_conversation_id
            AND public.soundscore_realtime_user_id() IN (c.user1_id, c.user2_id)
            AND public.soundscore_can_interact(CASE WHEN c.user1_id = public.soundscore_realtime_user_id() THEN c.user2_id ELSE c.user1_id END))
        $$
    """)
    op.execute("DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_messages")
    op.execute("""CREATE POLICY soundscore_realtime_select ON public.group_messages FOR SELECT TO authenticated
        USING (public.soundscore_is_group_member(group_id) AND public.soundscore_can_interact(user_id))""")
    op.execute("DROP POLICY IF EXISTS soundscore_realtime_select ON public.notifications")
    op.execute("""CREATE POLICY soundscore_realtime_select ON public.notifications FOR SELECT TO authenticated
        USING (recipient_id = public.soundscore_realtime_user_id() AND public.soundscore_can_interact(actor_id))""")


def downgrade():
    op.execute("DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_messages")
    op.execute("CREATE POLICY soundscore_realtime_select ON public.group_messages FOR SELECT TO authenticated USING (public.soundscore_is_group_member(group_id))")
    op.execute("DROP POLICY IF EXISTS soundscore_realtime_select ON public.notifications")
    op.execute("CREATE POLICY soundscore_realtime_select ON public.notifications FOR SELECT TO authenticated USING (recipient_id = public.soundscore_realtime_user_id())")
    op.execute("""CREATE OR REPLACE FUNCTION public.soundscore_is_conversation_participant(target_conversation_id bigint)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
        SELECT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = target_conversation_id
          AND public.soundscore_realtime_user_id() IN (c.user1_id, c.user2_id)) $$""")
    op.execute("DROP FUNCTION public.soundscore_can_interact(bigint)")
    op.drop_table("content_reports")
    op.drop_table("terms_acceptances")
    op.drop_table("user_blocks")
