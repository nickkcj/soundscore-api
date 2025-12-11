from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Create async engine - optimized for serverless (Railway/Vercel)
# Lower pool settings to avoid connection exhaustion on cold starts
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # Log SQL queries in debug mode
    pool_pre_ping=True,   # Check connection health before using
    pool_size=3,          # Reduced for serverless - prevents connection exhaustion
    max_overflow=5,       # Reduced for serverless - max 8 connections per instance
    pool_timeout=10,      # Fail fast if can't get connection
    pool_recycle=300,     # Recycle connections every 5 min to avoid stale connections
    connect_args={
        "statement_cache_size": 0,           # Required for pgbouncer (Supabase)
        "prepared_statement_cache_size": 0,  # Also required for pgbouncer
        "command_timeout": 30,               # Query timeout
    },
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def get_db():
    """
    Dependency that provides a database session.

    Usage in FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
