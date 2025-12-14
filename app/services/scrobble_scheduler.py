"""Background scheduler for automatic scrobble syncing."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.oauth import OAuthAccount
from app.services.spotify_scrobble_service import SpotifyScrobbleService

logger = logging.getLogger(__name__)


async def sync_all_users_scrobbles():
    """
    Sync scrobbles for all users with Spotify connected.
    This runs periodically to build up listening history over time.
    """
    logger.info("Starting scheduled scrobble sync for all users...")

    async with AsyncSessionLocal() as db:
        # Get all users with Spotify OAuth connected
        result = await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == 'spotify',
                OAuthAccount.access_token.isnot(None)
            )
        )
        oauth_accounts = result.scalars().all()

        total_synced = 0
        users_synced = 0
        errors = 0

        for oauth in oauth_accounts:
            try:
                service = SpotifyScrobbleService(db)
                synced_count = await service.sync_scrobbles(oauth.user_id)

                if synced_count > 0:
                    total_synced += synced_count
                    users_synced += 1
                    logger.info(f"Synced {synced_count} scrobbles for user {oauth.user_id}")

            except Exception as e:
                errors += 1
                logger.error(f"Error syncing scrobbles for user {oauth.user_id}: {e}")
                continue

        logger.info(
            f"Scheduled sync complete: {total_synced} scrobbles synced "
            f"for {users_synced} users, {errors} errors"
        )


def setup_scheduler(app):
    """
    Setup the APScheduler for background tasks.
    Called from main.py on startup.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler()

    # Sync scrobbles every hour
    scheduler.add_job(
        sync_all_users_scrobbles,
        trigger=IntervalTrigger(hours=1),
        id='sync_scrobbles',
        name='Sync scrobbles for all users',
        replace_existing=True,
    )

    # Also run once on startup (after 30 seconds to let the app initialize)
    scheduler.add_job(
        sync_all_users_scrobbles,
        trigger='date',
        run_date=datetime.now(timezone.utc),
        id='sync_scrobbles_startup',
        name='Initial scrobble sync on startup',
    )

    scheduler.start()
    logger.info("Scrobble scheduler started - will sync every hour")

    return scheduler
