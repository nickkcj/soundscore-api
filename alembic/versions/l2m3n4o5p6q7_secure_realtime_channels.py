"""secure realtime channels

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-20 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("group_messages", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.add_column("direct_messages", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_group_messages_user_client_id",
        "group_messages",
        ["group_id", "user_id", "client_id"],
    )
    op.create_unique_constraint(
        "uq_direct_messages_sender_client_id",
        "direct_messages",
        ["conversation_id", "sender_id", "client_id"],
    )
    statements = (
        """
        CREATE OR REPLACE FUNCTION public.soundscore_realtime_user_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SET search_path = ''
        AS $$
          SELECT NULLIF(
            NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'app_user_id',
            ''
          )::bigint
        $$
        """,
        """
        CREATE OR REPLACE FUNCTION public.soundscore_is_group_member(target_group_id bigint)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT EXISTS (
            SELECT 1
            FROM public.group_members membership
            WHERE membership.group_id = target_group_id
              AND membership.user_id = public.soundscore_realtime_user_id()
          )
        $$
        """,
        """
        CREATE OR REPLACE FUNCTION public.soundscore_is_conversation_participant(target_conversation_id bigint)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT EXISTS (
            SELECT 1
            FROM public.conversations conversation
            WHERE conversation.id = target_conversation_id
              AND public.soundscore_realtime_user_id() IN (
                conversation.user1_id,
                conversation.user2_id
              )
          )
        $$
        """,
        """
        CREATE OR REPLACE FUNCTION public.soundscore_is_session_participant(target_code text)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT EXISTS (
            SELECT 1
            FROM public.listening_sessions session
            JOIN public.session_participants participant
              ON participant.session_id = session.id
            WHERE session.code = upper(target_code)
              AND participant.user_id = public.soundscore_realtime_user_id()
          )
        $$
        """,
        "ALTER TABLE public.group_messages ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.group_members ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.direct_messages ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_messages",
        """
        CREATE POLICY soundscore_realtime_select
          ON public.group_messages
          FOR SELECT
          TO authenticated
          USING (public.soundscore_is_group_member(group_id))
        """,
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_members",
        """
        CREATE POLICY soundscore_realtime_select
          ON public.group_members
          FOR SELECT
          TO authenticated
          USING (public.soundscore_is_group_member(group_id))
        """,
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.direct_messages",
        """
        CREATE POLICY soundscore_realtime_select
          ON public.direct_messages
          FOR SELECT
          TO authenticated
          USING (public.soundscore_is_conversation_participant(conversation_id))
        """,
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.notifications",
        """
        CREATE POLICY soundscore_realtime_select
          ON public.notifications
          FOR SELECT
          TO authenticated
          USING (recipient_id = public.soundscore_realtime_user_id())
        """,
    )
    for statement in statements:
        op.execute(statement)

    op.execute(
        """
        DO $outer$
        BEGIN
          IF to_regclass('realtime.messages') IS NOT NULL THEN
            EXECUTE 'DROP POLICY IF EXISTS soundscore_mobile_receive ON realtime.messages';
            EXECUTE 'DROP POLICY IF EXISTS soundscore_mobile_send ON realtime.messages';

            EXECUTE $policy$
              CREATE POLICY soundscore_mobile_receive
              ON realtime.messages
              FOR SELECT
              TO authenticated
              USING (
                CASE
                  WHEN realtime.topic() LIKE 'group:%' THEN
                    public.soundscore_is_group_member(
                      (SELECT id FROM public.groups WHERE uuid::text = substring(realtime.topic() from 7))
                    )
                  WHEN realtime.topic() ~ '^dm:inbox:[0-9]+$' THEN
                    public.soundscore_realtime_user_id() = substring(realtime.topic() from 10)::bigint
                  WHEN realtime.topic() ~ '^dm:[0-9]+$' THEN
                    public.soundscore_is_conversation_participant(substring(realtime.topic() from 4)::bigint)
                  WHEN realtime.topic() LIKE 'listening:%' THEN
                    public.soundscore_is_session_participant(substring(realtime.topic() from 11))
                  WHEN realtime.topic() LIKE 'session:%' THEN
                    public.soundscore_is_session_participant(substring(realtime.topic() from 9))
                  WHEN realtime.topic() ~ '^notifications:user:[0-9]+$' THEN
                    public.soundscore_realtime_user_id() = substring(realtime.topic() from 20)::bigint
                  ELSE false
                END
              )
            $policy$;

            EXECUTE $policy$
              CREATE POLICY soundscore_mobile_send
              ON realtime.messages
              FOR INSERT
              TO authenticated
              WITH CHECK (
                extension IN ('broadcast', 'presence')
                AND CASE
                  WHEN realtime.topic() LIKE 'group:%' THEN
                    public.soundscore_is_group_member(
                      (SELECT id FROM public.groups WHERE uuid::text = substring(realtime.topic() from 7))
                    )
                  WHEN realtime.topic() ~ '^dm:inbox:[0-9]+$' THEN
                    public.soundscore_realtime_user_id() = substring(realtime.topic() from 10)::bigint
                  WHEN realtime.topic() ~ '^dm:[0-9]+$' THEN
                    public.soundscore_is_conversation_participant(substring(realtime.topic() from 4)::bigint)
                  WHEN realtime.topic() LIKE 'listening:%' THEN
                    public.soundscore_is_session_participant(substring(realtime.topic() from 11))
                  WHEN realtime.topic() LIKE 'session:%' THEN
                    public.soundscore_is_session_participant(substring(realtime.topic() from 9))
                  WHEN realtime.topic() ~ '^notifications:user:[0-9]+$' THEN
                    public.soundscore_realtime_user_id() = substring(realtime.topic() from 20)::bigint
                  ELSE false
                END
              )
            $policy$;
          END IF;
        END
        $outer$;
        """
    )

    op.execute(
        """
        DO $outer$
        DECLARE
          table_name text;
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
            FOREACH table_name IN ARRAY ARRAY['group_messages', 'group_members', 'direct_messages', 'notifications']
            LOOP
              IF NOT EXISTS (
                SELECT 1
                FROM pg_publication_tables
                WHERE pubname = 'supabase_realtime'
                  AND schemaname = 'public'
                  AND tablename = table_name
              ) THEN
                EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE public.%I', table_name);
              END IF;
            END LOOP;
          END IF;
        END
        $outer$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $outer$
        BEGIN
          IF to_regclass('realtime.messages') IS NOT NULL THEN
            EXECUTE 'DROP POLICY IF EXISTS soundscore_mobile_receive ON realtime.messages';
            EXECUTE 'DROP POLICY IF EXISTS soundscore_mobile_send ON realtime.messages';
          END IF;
        END
        $outer$
        """
    )

    for statement in (
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.direct_messages",
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.notifications",
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_members",
        "DROP POLICY IF EXISTS soundscore_realtime_select ON public.group_messages",
        "DROP FUNCTION IF EXISTS public.soundscore_is_session_participant(text)",
        "DROP FUNCTION IF EXISTS public.soundscore_is_conversation_participant(bigint)",
        "DROP FUNCTION IF EXISTS public.soundscore_is_group_member(bigint)",
        "DROP FUNCTION IF EXISTS public.soundscore_realtime_user_id()",
    ):
        op.execute(statement)

    op.drop_constraint("uq_direct_messages_sender_client_id", "direct_messages", type_="unique")
    op.drop_constraint("uq_group_messages_user_client_id", "group_messages", type_="unique")
    op.drop_column("direct_messages", "client_id")
    op.drop_column("group_messages", "client_id")

    # Publication membership is intentionally retained on downgrade. Removing a
    # table that may have been published before this migration would interrupt
    # already-deployed web clients.
