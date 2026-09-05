import pytest

from app.services import storage_service
from app.services.storage_service import StorageService

CDN = "assets.test.cloudfront.net"


@pytest.fixture
def routed(monkeypatch):
    """Resolve asset URLs with a known CDN and a stubbed signer/cache."""
    monkeypatch.setattr(storage_service.settings, "cloudfront_domain", CDN)

    async def fake_sign(path: str, expires_in: int = 3600) -> str:
        return f"signed://{path}"

    async def no_cache(*args, **kwargs):
        return None

    async def noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(StorageService, "get_signed_url", fake_sign)
    monkeypatch.setattr(storage_service.CacheService, "get", no_cache)
    monkeypatch.setattr(storage_service.CacheService, "set", noop)
    return StorageService.resolve_asset_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "profile_pictures/2_uuid.webp",
        "banner_images/2_uuid.webp",
        "groups_cover_images/1_uuid.webp",
        "session_covers/2_uuid.webp",
    ],
)
async def test_public_prefixes_get_a_stable_cdn_url(routed, path) -> None:
    assert await routed(path) == f"https://{CDN}/{path}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "dm_images/9_uuid.jpg",
        "group_message_images/3/1_uuid.jpg",
    ],
)
async def test_message_attachments_stay_signed(routed, path) -> None:
    """DM and group chat images are private: they must never hit the CDN."""
    resolved = await routed(path)

    assert resolved == f"signed://{path}"
    assert CDN not in resolved


@pytest.mark.asyncio
async def test_unknown_prefix_fails_closed(routed) -> None:
    """A prefix nobody declared public must be treated as private."""
    assert await routed("some_new_prefix/x.jpg") == "signed://some_new_prefix/x.jpg"


@pytest.mark.asyncio
async def test_external_urls_pass_through(routed) -> None:
    assert await routed("https://i.scdn.co/image/abc") == "https://i.scdn.co/image/abc"


@pytest.mark.asyncio
async def test_empty_path_resolves_to_none(routed) -> None:
    assert await routed(None) is None
    assert await routed("") is None


@pytest.mark.asyncio
async def test_without_cdn_configured_public_assets_stay_signed(routed, monkeypatch) -> None:
    """Falling back to presigned URLs keeps the app working before the CDN exists."""
    monkeypatch.setattr(storage_service.settings, "cloudfront_domain", None)

    assert await routed("profile_pictures/2_uuid.webp") == "signed://profile_pictures/2_uuid.webp"
