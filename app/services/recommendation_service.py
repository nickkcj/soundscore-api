"""
User Recommendation Service for SoundScore.

Provides activity-based user recommendations considering:
- Similar album ratings (users who rated same albums similarly)
- Common review likes (users who liked the same reviews)
- Recent activity (users who posted reviews recently)
- Favorite albums overlap (shared favorite albums)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserFollow
from app.models.review import Review, ReviewLike
from app.services.cache_service import CacheService, CacheKeys
from app.services.storage_service import StorageService


# Scoring weights
RATING_SIMILARITY_WEIGHT = 0.35
SHARED_LIKES_WEIGHT = 0.25
RECENT_ACTIVITY_WEIGHT = 0.20
FAVORITE_OVERLAP_WEIGHT = 0.20

# Configuration
CACHE_TTL = 900  # 15 minutes
RECENT_ACTIVITY_DAYS = 30
MAX_CANDIDATES = 100


@dataclass
class ScoredUser:
    """User with computed recommendation score."""
    user_id: int
    username: str
    profile_picture: Optional[str]
    bio: Optional[str]
    followers_count: int
    score: float
    rating_similarity: float
    shared_likes: int
    recent_reviews: int
    favorite_overlap: int


class RecommendationService:
    """Service for generating activity-based user recommendations."""

    @classmethod
    async def get_recommended_users(
        cls,
        db: AsyncSession,
        current_user_id: int,
        limit: int = 5,
    ) -> list[ScoredUser]:
        """
        Get recommended users based on activity similarity.

        Uses caching with 15-minute TTL.
        For new users without reviews, returns recently active users.
        """
        # Check cache first
        cache_key = f"{CacheKeys.USER_SUGGESTIONS}{current_user_id}:{limit}"
        cached = await CacheService.get_json(cache_key)
        if cached:
            return [ScoredUser(**u) for u in cached]

        try:
            # Check if user has reviews (cold start detection)
            has_reviews = await cls._user_has_reviews(db, current_user_id)

            if not has_reviews:
                # Cold start: return recently active users
                recommendations = await cls._get_recently_active_users(
                    db, current_user_id, limit
                )
            else:
                # Normal flow: compute similarity scores
                recommendations = await cls._compute_recommendations(
                    db, current_user_id, limit
                )

            # Cache results
            cache_data = [
                {
                    "user_id": r.user_id,
                    "username": r.username,
                    "profile_picture": r.profile_picture,
                    "bio": r.bio,
                    "followers_count": r.followers_count,
                    "score": r.score,
                    "rating_similarity": r.rating_similarity,
                    "shared_likes": r.shared_likes,
                    "recent_reviews": r.recent_reviews,
                    "favorite_overlap": r.favorite_overlap,
                }
                for r in recommendations
            ]
            await CacheService.set_json(cache_key, cache_data, ttl=CACHE_TTL)

            return recommendations

        except Exception:
            # Fallback to recently active users on any error
            return await cls._get_recently_active_users(db, current_user_id, limit)

    @staticmethod
    async def _user_has_reviews(db: AsyncSession, user_id: int) -> bool:
        """Check if user has any reviews."""
        result = await db.execute(
            select(func.count()).select_from(Review).where(Review.user_id == user_id)
        )
        return (result.scalar() or 0) > 0

    @classmethod
    async def _get_excluded_user_ids(
        cls, db: AsyncSession, current_user_id: int
    ) -> set[int]:
        """Get IDs of users to exclude (self + already following)."""
        following_result = await db.execute(
            select(UserFollow.following_id).where(
                UserFollow.follower_id == current_user_id
            )
        )
        excluded_ids = {row[0] for row in following_result.all()}
        excluded_ids.add(current_user_id)
        return excluded_ids

    @classmethod
    async def _get_recently_active_users(
        cls,
        db: AsyncSession,
        current_user_id: int,
        limit: int,
    ) -> list[ScoredUser]:
        """
        Fallback for cold start: get most recently active users.

        Returns users sorted by most recent review activity.
        """
        excluded_ids = await cls._get_excluded_user_ids(db, current_user_id)

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=RECENT_ACTIVITY_DAYS)

        # Subquery for follower counts
        follower_counts = (
            select(
                UserFollow.following_id.label("user_id"),
                func.count(UserFollow.id).label("followers_count"),
            )
            .group_by(UserFollow.following_id)
            .subquery()
        )

        # Subquery for recent activity per user
        recent_activity = (
            select(
                Review.user_id,
                func.max(Review.created_at).label("last_review"),
                func.count(Review.id).label("review_count"),
            )
            .where(Review.created_at >= thirty_days_ago)
            .group_by(Review.user_id)
            .subquery()
        )

        # If no recent activity, extend to all-time
        check_result = await db.execute(
            select(func.count()).select_from(recent_activity)
        )
        has_recent_activity = (check_result.scalar() or 0) > 0

        if has_recent_activity:
            # Main query: users with recent activity
            result = await db.execute(
                select(
                    User,
                    follower_counts.c.followers_count,
                    recent_activity.c.review_count,
                )
                .outerjoin(follower_counts, User.id == follower_counts.c.user_id)
                .join(recent_activity, User.id == recent_activity.c.user_id)
                .where(User.id.notin_(excluded_ids))
                .order_by(recent_activity.c.last_review.desc())
                .limit(limit)
            )
        else:
            # Fallback: all-time activity
            all_time_activity = (
                select(
                    Review.user_id,
                    func.max(Review.created_at).label("last_review"),
                    func.count(Review.id).label("review_count"),
                )
                .group_by(Review.user_id)
                .subquery()
            )
            result = await db.execute(
                select(
                    User,
                    follower_counts.c.followers_count,
                    all_time_activity.c.review_count,
                )
                .outerjoin(follower_counts, User.id == follower_counts.c.user_id)
                .join(all_time_activity, User.id == all_time_activity.c.user_id)
                .where(User.id.notin_(excluded_ids))
                .order_by(all_time_activity.c.last_review.desc())
                .limit(limit)
            )

        rows = result.all()

        if not rows:
            return []

        # Resolve profile pictures in parallel
        profile_pics = await asyncio.gather(
            *[
                StorageService.resolve_profile_picture(user.profile_picture)
                for user, _, _ in rows
            ]
        )

        return [
            ScoredUser(
                user_id=user.id,
                username=user.username,
                profile_picture=profile_pic,
                bio=user.bio,
                followers_count=followers_count or 0,
                score=0.0,  # No similarity score for cold start
                rating_similarity=0.0,
                shared_likes=0,
                recent_reviews=review_count or 0,
                favorite_overlap=0,
            )
            for (user, followers_count, review_count), profile_pic in zip(
                rows, profile_pics
            )
        ]

    @classmethod
    async def _compute_recommendations(
        cls,
        db: AsyncSession,
        current_user_id: int,
        limit: int,
    ) -> list[ScoredUser]:
        """Compute recommendations using multi-factor scoring."""
        excluded_ids = await cls._get_excluded_user_ids(db, current_user_id)

        # Get current user's reviews
        current_user_reviews = await db.execute(
            select(Review.album_id, Review.rating, Review.is_favorite).where(
                Review.user_id == current_user_id
            )
        )
        user_reviews = {
            row[0]: (row[1], row[2]) for row in current_user_reviews.all()
        }
        user_album_ids = set(user_reviews.keys())
        user_favorite_albums = {
            aid for aid, (_, fav) in user_reviews.items() if fav
        }

        # Get current user's liked reviews
        current_user_likes = await db.execute(
            select(ReviewLike.review_id).where(ReviewLike.user_id == current_user_id)
        )
        user_liked_reviews = {row[0] for row in current_user_likes.all()}

        # Get candidate users (active in last 30 days or with shared albums)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=RECENT_ACTIVITY_DAYS)

        candidates_query = await db.execute(
            select(User.id)
            .distinct()
            .join(Review, Review.user_id == User.id)
            .where(
                User.id.notin_(excluded_ids),
                Review.created_at >= thirty_days_ago,
            )
            .limit(MAX_CANDIDATES)
        )
        candidate_ids = [row[0] for row in candidates_query.all()]

        if not candidate_ids:
            # No active candidates, fallback to recently active
            return await cls._get_recently_active_users(db, current_user_id, limit)

        # Compute scores for all candidates
        scores = await cls._batch_compute_scores(
            db,
            candidate_ids,
            user_album_ids,
            user_reviews,
            user_favorite_albums,
            user_liked_reviews,
        )

        # Get top user IDs by score
        top_user_ids = sorted(
            scores.keys(), key=lambda uid: scores[uid]["total"], reverse=True
        )[:limit]

        if not top_user_ids:
            return await cls._get_recently_active_users(db, current_user_id, limit)

        # Load user details
        users_result = await db.execute(select(User).where(User.id.in_(top_user_ids)))
        users_map = {u.id: u for u in users_result.scalars().all()}

        # Get follower counts
        follower_counts_result = await db.execute(
            select(UserFollow.following_id, func.count(UserFollow.id))
            .where(UserFollow.following_id.in_(top_user_ids))
            .group_by(UserFollow.following_id)
        )
        follower_counts = dict(follower_counts_result.all())

        # Resolve profile pictures in parallel
        profile_pics = await asyncio.gather(
            *[
                StorageService.resolve_profile_picture(users_map[uid].profile_picture)
                for uid in top_user_ids
                if uid in users_map
            ]
        )

        # Build response maintaining score order
        result = []
        pic_idx = 0
        for uid in top_user_ids:
            if uid not in users_map:
                continue
            user = users_map[uid]
            result.append(
                ScoredUser(
                    user_id=uid,
                    username=user.username,
                    profile_picture=profile_pics[pic_idx] if pic_idx < len(profile_pics) else None,
                    bio=user.bio,
                    followers_count=follower_counts.get(uid, 0),
                    score=scores[uid]["total"],
                    rating_similarity=scores[uid]["rating_sim"],
                    shared_likes=scores[uid]["shared_likes"],
                    recent_reviews=scores[uid]["recent_reviews"],
                    favorite_overlap=scores[uid]["favorite_overlap"],
                )
            )
            pic_idx += 1

        return result

    @classmethod
    async def _batch_compute_scores(
        cls,
        db: AsyncSession,
        candidate_ids: list[int],
        user_album_ids: set[int],
        user_reviews: dict[int, tuple[int, bool]],
        user_favorite_albums: set[int],
        user_liked_reviews: set[int],
    ) -> dict[int, dict]:
        """Batch compute all similarity factors for candidates."""
        scores = {
            uid: {
                "total": 0.0,
                "rating_sim": 0.0,
                "shared_likes": 0,
                "recent_reviews": 0,
                "favorite_overlap": 0,
            }
            for uid in candidate_ids
        }

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=RECENT_ACTIVITY_DAYS)

        # Query 1: Get all reviews from candidates
        reviews_result = await db.execute(
            select(
                Review.user_id,
                Review.album_id,
                Review.rating,
                Review.is_favorite,
                Review.created_at,
            ).where(Review.user_id.in_(candidate_ids))
        )

        candidate_reviews: dict[int, list] = {}
        for row in reviews_result.all():
            uid, aid, rating, is_fav, created = row
            if uid not in candidate_reviews:
                candidate_reviews[uid] = []
            candidate_reviews[uid].append((aid, rating, is_fav, created))

        # Query 2: Get all likes from candidates
        likes_result = await db.execute(
            select(ReviewLike.user_id, ReviewLike.review_id).where(
                ReviewLike.user_id.in_(candidate_ids)
            )
        )

        candidate_likes: dict[int, set] = {}
        for uid, rid in likes_result.all():
            if uid not in candidate_likes:
                candidate_likes[uid] = set()
            candidate_likes[uid].add(rid)

        # Compute scores for each candidate
        for uid in candidate_ids:
            reviews = candidate_reviews.get(uid, [])
            likes = candidate_likes.get(uid, set())

            # Factor 1: Rating similarity
            rating_diffs = []
            for aid, rating, _, _ in reviews:
                if aid in user_album_ids:
                    user_rating, _ = user_reviews[aid]
                    # Similarity: 1 - (|diff| / 4) where max diff is 4 (5-1)
                    similarity = 1 - (abs(rating - user_rating) / 4)
                    rating_diffs.append(similarity)

            avg_rating_sim = sum(rating_diffs) / len(rating_diffs) if rating_diffs else 0.0

            # Factor 2: Shared likes
            shared_likes = len(likes.intersection(user_liked_reviews))
            normalized_shared_likes = min(shared_likes / 10, 1.0)

            # Factor 3: Recent activity
            recent_count = sum(
                1 for _, _, _, created in reviews
                if created and created >= thirty_days_ago
            )
            normalized_recent = min(recent_count / 5, 1.0)

            # Factor 4: Favorite album overlap
            candidate_favorites = {aid for aid, _, is_fav, _ in reviews if is_fav}
            favorite_overlap = len(
                candidate_favorites.intersection(user_favorite_albums)
            )
            normalized_favorite = min(favorite_overlap / 3, 1.0)

            # Compute weighted total score
            total_score = (
                RATING_SIMILARITY_WEIGHT * avg_rating_sim
                + SHARED_LIKES_WEIGHT * normalized_shared_likes
                + RECENT_ACTIVITY_WEIGHT * normalized_recent
                + FAVORITE_OVERLAP_WEIGHT * normalized_favorite
            )

            scores[uid] = {
                "total": total_score,
                "rating_sim": avg_rating_sim,
                "shared_likes": shared_likes,
                "recent_reviews": recent_count,
                "favorite_overlap": favorite_overlap,
            }

        return scores

    @staticmethod
    async def invalidate_user_suggestions(user_id: int | None = None) -> None:
        """
        Invalidate recommendation cache.

        Args:
            user_id: If provided, invalidates only that user's suggestions.
                     If None, invalidates all suggestion caches.
        """
        if user_id:
            await CacheService.delete_pattern(
                f"{CacheKeys.USER_SUGGESTIONS}{user_id}:*"
            )
        else:
            await CacheService.delete_pattern(f"{CacheKeys.USER_SUGGESTIONS}*")
