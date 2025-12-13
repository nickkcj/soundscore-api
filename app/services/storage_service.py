import logging

from app.config import get_settings
from app.services.cache_service import CacheService, CacheKeys
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)


class StorageService:
    """Service for handling Supabase Storage operations with signed URLs."""

    @staticmethod
    async def get_signed_url(path: str, expires_in: int = 3600) -> str | None:
        """
        Generate a signed URL for a storage object.
        Uses the global HTTP client for connection pooling.

        Args:
            path: The storage path (e.g., 'profile_pictures/1_uuid.webp')
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Signed URL string or None if generation fails
        """
        logger.info(f"[StorageService] get_signed_url called with path: {path}")

        if not path:
            logger.warning("[StorageService] Path is empty/None")
            return None

        settings = get_settings()
        logger.info(f"[StorageService] supabase_url: {settings.supabase_url[:30] if settings.supabase_url else 'None'}...")

        if not settings.supabase_url:
            logger.warning("[StorageService] supabase_url is not set")
            return None

        storage_key = settings.supabase_service_role_key or settings.supabase_key
        if not storage_key:
            logger.warning("[StorageService] No storage key available (service_role_key and supabase_key are both None)")
            return None

        logger.info(f"[StorageService] Using storage key: {storage_key[:10]}...")

        # Split path into bucket and file path
        parts = path.split("/", 1)
        if len(parts) != 2:
            logger.warning(f"[StorageService] Invalid path format: {path}")
            return None

        bucket, file_path = parts
        logger.info(f"[StorageService] bucket: {bucket}, file_path: {file_path}")

        try:
            client = get_http_client()
            url = f"{settings.supabase_url}/storage/v1/object/sign/{bucket}/{file_path}"
            logger.info(f"[StorageService] Making POST request to: {url}")

            response = await client.post(
                url,
                json={"expiresIn": expires_in},
                headers={
                    "Authorization": f"Bearer {storage_key}",
                    "apikey": storage_key,
                    "Content-Type": "application/json",
                },
            )

            logger.info(f"[StorageService] Response status: {response.status_code}")
            logger.info(f"[StorageService] Response body: {response.text[:200] if response.text else 'empty'}")

            if response.status_code == 200:
                data = response.json()
                signed_path = data.get("signedURL", "")
                if signed_path:
                    full_url = f"{settings.supabase_url}/storage/v1{signed_path}"
                    logger.info(f"[StorageService] Generated signed URL successfully")
                    return full_url
                else:
                    logger.warning("[StorageService] Response 200 but no signedURL in response")

            logger.warning(f"[StorageService] Failed to get signed URL, status: {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"[StorageService] Exception in get_signed_url: {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def resolve_profile_picture(path: str | None) -> str | None:
        """
        Resolve a profile picture path to a usable URL.

        If the path is already a full URL, return it as-is.
        If it's a storage path, generate a signed URL (cached for 45 min).
        """
        logger.info(f"[StorageService] resolve_profile_picture called with path: {path}")

        if not path:
            logger.info("[StorageService] Path is None/empty, returning None")
            return None

        # If it's already a full URL (legacy data), return as-is
        if path.startswith("http://") or path.startswith("https://"):
            logger.info("[StorageService] Path is already a URL, returning as-is")
            return path

        # Check cache first (URLs are valid for 1 hour, cache for 45 min)
        cache_key = f"{CacheKeys.SIGNED_URL}{path}"
        cached_url = await CacheService.get(cache_key)
        if cached_url:
            logger.info("[StorageService] Found cached URL")
            return cached_url

        logger.info("[StorageService] No cache, generating signed URL...")
        # Generate signed URL for storage path
        url = await StorageService.get_signed_url(path, expires_in=3600)
        if url:
            logger.info("[StorageService] Signed URL generated, caching...")
            await CacheService.set(cache_key, url, ttl=2700)  # 45 minutes
        else:
            logger.warning("[StorageService] Failed to generate signed URL")
        return url

    @staticmethod
    async def resolve_banner_image(path: str | None) -> str | None:
        """
        Resolve a banner image path to a usable URL.

        Same logic as profile picture with caching.
        """
        if not path:
            return None

        if path.startswith("http://") or path.startswith("https://"):
            return path

        # Check cache first
        cache_key = f"{CacheKeys.SIGNED_URL}{path}"
        cached_url = await CacheService.get(cache_key)
        if cached_url:
            return cached_url

        url = await StorageService.get_signed_url(path, expires_in=3600)
        if url:
            await CacheService.set(cache_key, url, ttl=2700)  # 45 minutes
        return url
