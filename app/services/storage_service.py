import logging
from io import BytesIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings
from app.services.cache_service import CacheService, CacheKeys

logger = logging.getLogger(__name__)

settings = get_settings()

_s3_client = None


def _get_s3_client():
    """Lazy-init a reusable boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            endpoint_url=f"https://s3.{settings.aws_region}.amazonaws.com",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )
    return _s3_client


class StorageService:
    """Service for handling AWS S3 storage operations."""

    @staticmethod
    def upload_file(key: str, data: bytes, content_type: str) -> None:
        """
        Upload a file to S3.

        Args:
            key: The S3 object key (e.g., 'profile_pictures/1_uuid.webp')
            data: File content as bytes
            content_type: MIME type (e.g., 'image/webp')
        """
        client = _get_s3_client()
        client.upload_fileobj(
            BytesIO(data),
            settings.aws_s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    @staticmethod
    def delete_file(key: str) -> None:
        """
        Delete a file from S3. Silently ignores if file doesn't exist.

        Args:
            key: The S3 object key (e.g., 'profile_pictures/1_uuid.webp')
        """
        try:
            client = _get_s3_client()
            client.delete_object(Bucket=settings.aws_s3_bucket, Key=key)
        except ClientError as e:
            logger.warning(f"Failed to delete S3 object {key}: {e}")

    @staticmethod
    async def get_signed_url(path: str, expires_in: int = 3600) -> str | None:
        """
        Generate a presigned URL for an S3 object.

        Args:
            path: The S3 key (e.g., 'profile_pictures/1_uuid.webp')
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL string or None if generation fails
        """
        if not path:
            return None

        try:
            client = _get_s3_client()
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.aws_s3_bucket, "Key": path},
                ExpiresIn=expires_in,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL for {path}: {e}")
            return None

    @staticmethod
    async def resolve_profile_picture(path: str | None) -> str | None:
        """
        Resolve a profile picture path to a usable URL.

        If the path is already a full URL, return it as-is.
        If it's a storage path, generate a presigned URL (cached for 45 min).
        """
        if not path:
            return None

        # Legacy full URLs - return as-is
        if path.startswith("http://") or path.startswith("https://"):
            return path

        # Check cache first (URLs valid for 1h, cache for 45 min)
        cache_key = f"{CacheKeys.SIGNED_URL}{path}"
        cached_url = await CacheService.get(cache_key)
        if cached_url:
            return cached_url

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

        cache_key = f"{CacheKeys.SIGNED_URL}{path}"
        cached_url = await CacheService.get(cache_key)
        if cached_url:
            return cached_url

        url = await StorageService.get_signed_url(path, expires_in=3600)
        if url:
            await CacheService.set(cache_key, url, ttl=2700)  # 45 minutes
        return url
