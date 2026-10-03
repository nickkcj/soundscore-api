"""Create the disposable baseline for the actual moderation migration smoke."""
import os
import asyncio
if os.environ.get("DATABASE_URL") != "postgresql+asyncpg://postgres:local-qa-only@127.0.0.1:55439/soundscore_qa":
    raise SystemExit("Use only the disposable soundscore QA database on port 55439")
# Do not use external production services from a developer's .env during QA.
for service in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET", "RESEND_API_KEY", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_OAUTH_CLIENT_ID", "SPOTIFY_OAUTH_CLIENT_SECRET", "GOOGLE_API_KEY", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
 os.environ[service] = ""
os.environ["REDIS_URL"] = "redis://127.0.0.1:55440"
from app.main import app  # Registers all mapped models, including scrobbles.
from app.database import Base, engine
from sqlalchemy import text

async def main():
    async with engine.begin() as connection:
        for statement in (
            "CREATE ROLE authenticated",
            "CREATE FUNCTION public.soundscore_realtime_user_id() RETURNS bigint LANGUAGE sql AS $$ SELECT 0::bigint $$",
            "CREATE FUNCTION public.soundscore_is_group_member(bigint) RETURNS boolean LANGUAGE sql AS $$ SELECT false $$",
        ):
            await connection.execute(text(statement))
        tables = [table for name, table in Base.metadata.tables.items()
                  if name not in ("user_blocks", "content_reports", "terms_acceptances")]
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    await engine.dispose()

asyncio.run(main())
