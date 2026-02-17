"""
AWS Lambda handler for syncing Spotify scrobbles.

Self-contained function that:
1. Fetches all users with Spotify OAuth connected
2. Refreshes expired tokens
3. Fetches recently played tracks from Spotify API
4. Upserts scrobbles into the database

Environment variables required:
  - DATABASE_URL: PostgreSQL connection string (postgresql://user:pass@host:port/db)
  - SPOTIFY_OAUTH_CLIENT_ID: Spotify OAuth app client ID
  - SPOTIFY_OAUTH_CLIENT_SECRET: Spotify OAuth app client secret

Deploy:
  - Runtime: Python 3.12
  - Timeout: 5 minutes
  - Memory: 256 MB
  - Trigger: EventBridge schedule rule -> rate(1 hour)
  - Layer: psycopg2-binary, requests
"""

import os
import logging
from datetime import datetime, timezone, timedelta

import psycopg2
import psycopg2.extras
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATABASE_URL = os.environ["DATABASE_URL"]
SPOTIFY_CLIENT_ID = os.environ["SPOTIFY_OAUTH_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_OAUTH_CLIENT_SECRET"]

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


def get_db_connection():
    """Create a PostgreSQL connection from DATABASE_URL."""
    # Convert async URL format if needed (remove +asyncpg)
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def get_spotify_users(conn):
    """Fetch all users with active Spotify OAuth tokens."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, user_id, access_token, refresh_token, token_expires_at
            FROM oauth_accounts
            WHERE provider = 'spotify' AND access_token IS NOT NULL
        """)
        return cur.fetchall()


def refresh_token_if_needed(conn, oauth):
    """Refresh Spotify access token if expired or about to expire."""
    expires_at = oauth["token_expires_at"]
    if not expires_at:
        return True

    # Make timezone-aware comparison
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return True  # Still valid

    if not oauth["refresh_token"]:
        return False

    resp = requests.post(SPOTIFY_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": oauth["refresh_token"],
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    })

    if resp.status_code != 200:
        logger.error(f"Token refresh failed for oauth {oauth['id']}: {resp.text}")
        return False

    data = resp.json()
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE oauth_accounts
            SET access_token = %s,
                refresh_token = COALESCE(%s, refresh_token),
                token_expires_at = %s
            WHERE id = %s
        """, (
            data["access_token"],
            data.get("refresh_token"),
            new_expires_at,
            oauth["id"],
        ))
    conn.commit()

    # Update in-memory token for subsequent API calls
    oauth["access_token"] = data["access_token"]
    return True


def get_recently_played(access_token, limit=50):
    """Fetch recently played tracks from Spotify API."""
    resp = requests.get(
        f"{SPOTIFY_API_BASE}/me/player/recently-played",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"limit": min(limit, 50)},
    )

    if resp.status_code != 200:
        return []

    tracks = []
    for item in resp.json().get("items", []):
        track = item["track"]
        images = track["album"].get("images", [])
        tracks.append({
            "track_id": track["id"],
            "track_name": track["name"],
            "artist_name": ", ".join(a["name"] for a in track["artists"]),
            "album_name": track["album"]["name"],
            "album_image_url": images[0]["url"] if images else None,
            "duration_ms": track["duration_ms"],
            "played_at": item["played_at"],
        })
    return tracks


def upsert_scrobbles(conn, user_id, tracks):
    """Insert scrobbles, skipping duplicates via ON CONFLICT DO NOTHING."""
    synced = 0
    with conn.cursor() as cur:
        for track in tracks:
            played_at = datetime.fromisoformat(
                track["played_at"].replace("Z", "+00:00")
            )
            cur.execute("""
                INSERT INTO scrobbles
                    (user_id, track_id, track_name, artist_name,
                     album_name, album_image_url, duration_ms, played_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT unique_scrobble DO NOTHING
            """, (
                user_id,
                track["track_id"],
                track["track_name"],
                track["artist_name"],
                track["album_name"],
                track["album_image_url"],
                track["duration_ms"],
                played_at,
            ))
            if cur.rowcount > 0:
                synced += 1
    conn.commit()
    return synced


def handler(event, context):
    """Lambda entry point. Syncs scrobbles for all Spotify-connected users."""
    logger.info("Starting scrobble sync...")

    conn = get_db_connection()
    try:
        oauth_accounts = get_spotify_users(conn)
        logger.info(f"Found {len(oauth_accounts)} Spotify-connected users")

        total_synced = 0
        users_synced = 0
        errors = 0

        for oauth in oauth_accounts:
            try:
                if not refresh_token_if_needed(conn, oauth):
                    logger.warning(f"Skipping user {oauth['user_id']}: token refresh failed")
                    errors += 1
                    continue

                tracks = get_recently_played(oauth["access_token"])
                if not tracks:
                    continue

                synced = upsert_scrobbles(conn, oauth["user_id"], tracks)
                if synced > 0:
                    total_synced += synced
                    users_synced += 1
                    logger.info(f"Synced {synced} scrobbles for user {oauth['user_id']}")

            except Exception as e:
                errors += 1
                logger.error(f"Error syncing user {oauth['user_id']}: {e}")
                continue

        result = {
            "total_synced": total_synced,
            "users_synced": users_synced,
            "errors": errors,
            "total_accounts": len(oauth_accounts),
        }
        logger.info(f"Sync complete: {result}")
        return result

    finally:
        conn.close()
