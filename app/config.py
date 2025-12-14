from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "SoundScore API"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str

    # JWT Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Spotify API (for music data)
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None

    # Google Gemini API
    google_api_key: Optional[str] = None

    # OAuth - Google
    google_oauth_client_id: Optional[str] = None
    google_oauth_client_secret: Optional[str] = None

    # OAuth - Spotify (can reuse spotify_client_id/secret if same app)
    spotify_oauth_client_id: Optional[str] = None
    spotify_oauth_client_secret: Optional[str] = None

    # Backend URL (for OAuth callbacks)
    backend_url: str = "http://localhost:8000"

    # Supabase Storage
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    supabase_service_role_key: Optional[str] = None  # Bypasses RLS - use for server-side uploads
    supabase_bucket_profiles: str = "profiles"
    supabase_bucket_groups: str = "groups"

    # File uploads
    max_upload_size_mb: int = 5
    allowed_image_types: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # Email (Resend)
    resend_api_key: Optional[str] = None
    frontend_url: str = "http://localhost:3000"
    password_reset_token_expire_minutes: int = 15

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
