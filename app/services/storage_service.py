import httpx
from app.config import get_settings
from app.services.cache_service import CacheService, CacheKeys


class StorageService:
    """Service for handling Supabase Storage operations with signed URLs."""

    @staticmethod
    async def get_signed_url(path: str, expires_in: int = 3600) -> str | None:
        """
        Generate a signed URL for a storage object.

        Args:
            path: The storage path (e.g., 'profile_pictures/1_uuid.webp')
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Signed URL string or None if generation fails
        """
        if not path:
            return None

        settings = get_settings()
        if not settings.supabase_url:
            return None

        storage_key = settings.supabase_service_role_key or settings.supabase_key
        if not storage_key:
            return None

        # Split path into bucket and file path
        parts = path.split("/", 1)
        if len(parts) != 2:
            return None

        bucket, file_path = parts

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.supabase_url}/storage/v1/object/sign/{bucket}/{file_path}",
                    json={"expiresIn": expires_in},
                    headers={
                        "Authorization": f"Bearer {storage_key}",
                        "apikey": storage_key,
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    signed_path = data.get("signedURL", "")
                    if signed_path:
                        return f"{settings.supabase_url}/storage/v1{signed_path}"

                return None
        except Exception:
            return None

    @staticmethod
    async def resolve_profile_picture(path: str | None) -> str | None:
        """
        Resolve a profile picture path to a usable URL.

        If the path is already a full URL, return it as-is.
        If it's a storage path, generate a signed URL (cached for 45 min).
        """
        if not path:
            return None

        # If it's already a full URL (legacy data), return as-is
        if path.startswith("http://") or path.startswith("https://"):
            return path

        # Check cache first (URLs are valid for 1 hour, cache for 45 min)
        cache_key = f"{CacheKeys.SIGNED_URL}{path}"
        cached_url = await CacheService.get(cache_key)
        if cached_url:
            return cached_url

        # Generate signed URL for storage path
        url = await StorageService.get_signed_url(path, expires_in=3600)
        if url:
            await CacheService.set(cache_key, url, ttl=2700)  # 45 minutes
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
