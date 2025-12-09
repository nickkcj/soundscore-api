from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, users, reviews, feed, groups, chatbot, home
from app.websockets import group_chat

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.
    """
    # Startup
    print(f"🚀 Starting {settings.app_name}...")
    yield
    # Shutdown
    print(f"👋 Shutting down {settings.app_name}...")


app = FastAPI(
    title=settings.app_name,
    description="API for SoundScore - A social platform for music lovers",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware - configure for your frontend domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else ["https://yourdomain.com"],
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
