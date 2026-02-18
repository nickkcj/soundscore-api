"""Artist router for fetching artist details, albums, and AI-generated bios."""

from fastapi import APIRouter
from sqlalchemy import select, func

from app.models.artist import Artist
from app.models.review import Album, Review
from app.schemas.artist import ArtistDetailResponse, ArtistAlbumItem
from app.core.exceptions import NotFoundException
from app.dependencies import OptionalUser, DbSession
from app.services.spotify_service import spotify_service
from app.services.gemini_service import gemini_service

router = APIRouter()


@router.get(
    "/{spotify_id}/details",
    response_model=ArtistDetailResponse,
    summary="Get artist details",
)
async def get_artist_details(
    spotify_id: str,
    db: DbSession,
    current_user: OptionalUser = None,
):
    """
    Get complete artist details from Spotify plus SoundScore album stats.

    - Fetches artist info and discography from Spotify
    - Returns avg rating and review count per album from SoundScore
    - Generates AI bio on first access (cached in DB)
    """
    # Fetch artist details from Spotify
    spotify_data = await spotify_service.get_artist(spotify_id)
    if not spotify_data:
        raise NotFoundException("Artist not found on Spotify")

    # Fetch artist albums from Spotify
    spotify_albums = await spotify_service.get_artist_albums(spotify_id)

    # Check if artist exists in our database
    artist_result = await db.execute(
        select(Artist).where(Artist.spotify_id == spotify_id)
    )
    artist = artist_result.scalar_one_or_none()

    summary = artist.summary if artist else None

    # Generate bio if not exists
    if not summary:
        try:
            summary = gemini_service.generate_artist_bio(
                name=spotify_data["name"],
                genres=spotify_data.get("genres", []),
                popularity=spotify_data.get("popularity", 0),
            )

            if summary and artist:
                artist.summary = summary
                await db.commit()
            elif summary and not artist:
                new_artist = Artist(
                    spotify_id=spotify_id,
                    name=spotify_data["name"],
                    image_url=spotify_data.get("image_url"),
                    genres=", ".join(spotify_data.get("genres", [])),
                    summary=summary,
                )
                db.add(new_artist)
                await db.commit()
        except Exception:
            pass

    # Get SoundScore stats for each album
    album_items = []
    if spotify_albums:
        # Fetch all album spotify_ids that exist in our DB
        album_spotify_ids = [a["spotify_id"] for a in spotify_albums]
        album_stats_result = await db.execute(
            select(
                Album.spotify_id,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("review_count"),
            )
            .join(Review, Review.album_id == Album.id)
            .where(Album.spotify_id.in_(album_spotify_ids))
            .group_by(Album.spotify_id)
        )
        stats_map = {
            row.spotify_id: {
                "avg_rating": round(float(row.avg_rating), 1) if row.avg_rating else None,
                "review_count": row.review_count or 0,
            }
            for row in album_stats_result.all()
        }

        for sa in spotify_albums:
            stats = stats_map.get(sa["spotify_id"], {})
            album_items.append(
                ArtistAlbumItem(
                    spotify_id=sa["spotify_id"],
                    title=sa["title"],
                    cover_image=sa.get("cover_image"),
                    release_date=sa.get("release_date"),
                    avg_rating=stats.get("avg_rating"),
                    review_count=stats.get("review_count", 0),
                )
            )

    return ArtistDetailResponse(
        spotify_id=spotify_data["spotify_id"],
        name=spotify_data["name"],
        image_url=spotify_data.get("image_url"),
        genres=spotify_data.get("genres", []),
        popularity=spotify_data.get("popularity", 0),
        followers=spotify_data.get("followers", 0),
        spotify_url=spotify_data.get("spotify_url", ""),
        summary=summary,
        albums=album_items,
    )
