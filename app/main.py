from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.routers import auth, users, reviews, feed, groups, chatbot, home, oauth, library
from app.websockets import group_chat
from app.services.cache_service import CacheService
from app.services.http_client import HTTPClientManager
from app.database import engine

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.
    Performs warmup to reduce cold start latency.
    """
    # Startup - warmup all connections
    logger.info(f"🚀 Starting {settings.app_name}...")

    # 1. Warmup database connection pool
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("✅ Database pool warmed up")
    except Exception as e:
        logger.error(f"❌ Database warmup failed: {e}")

    # 2. Warmup Redis connection
    try:
        await CacheService.initialize()
        client = await CacheService.get_client()
        await client.ping()
        logger.info("✅ Redis connection warmed up")
    except Exception as e:
        logger.warning(f"⚠️ Redis warmup failed (will use fallback): {e}")

    # 3. Warmup HTTP client pool
    try:
        await HTTPClientManager.warmup()
        logger.info("✅ HTTP client pool warmed up")
    except Exception as e:
        logger.warning(f"⚠️ HTTP client warmup failed: {e}")

    logger.info("🎵 SoundScore API ready to serve requests!")

    yield

    # Shutdown - cleanup connections
    logger.info(f"👋 Shutting down {settings.app_name}...")

    # Close HTTP client
    await HTTPClientManager.close()
    logger.info("✅ HTTP client closed")

    # Close Redis
    await CacheService.close()
    logger.info("✅ Redis connection closed")

    # Close database pool
    await engine.dispose()
    logger.info("✅ Database pool closed")


app = FastAPI(
    title=settings.app_name,
    description="API for SoundScore - A social platform for music lovers",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Session Middleware for OAuth state management
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key)

# CORS Middleware - configure for your frontend domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://soundscore.com.br",
        "https://www.soundscore.com.br",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(
    auth.router,
    prefix=f"{settings.api_v1_prefix}/auth",
    tags=["Authentication"]
)
app.include_router(
    users.router,
    prefix=f"{settings.api_v1_prefix}/users",
    tags=["Users"]
)
app.include_router(
    reviews.router,
    prefix=f"{settings.api_v1_prefix}/reviews",
    tags=["Reviews"]
)
app.include_router(
    feed.router,
    prefix=f"{settings.api_v1_prefix}/feed",
    tags=["Feed"]
)
app.include_router(
    groups.router,
    prefix=f"{settings.api_v1_prefix}/groups",
    tags=["Groups"]
)

# WebSocket routes
app.include_router(
    group_chat.router,
    tags=["WebSocket"]
)

# Chatbot
app.include_router(
    chatbot.router,
    prefix=f"{settings.api_v1_prefix}/chatbot",
    tags=["Chatbot"]
)

# Home (public endpoints for landing page)
app.include_router(
    home.router,
    prefix=f"{settings.api_v1_prefix}/home",
    tags=["Home"]
)

# OAuth
app.include_router(
    oauth.router,
    prefix=f"{settings.api_v1_prefix}/oauth",
    tags=["OAuth"]
)

# Library (scrobbling)
app.include_router(
    library.router,
    prefix=f"{settings.api_v1_prefix}/library",
    tags=["Library"]
)


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API info."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
