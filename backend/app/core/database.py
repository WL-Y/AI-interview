"""Database connection helpers (PostgreSQL + Redis)."""

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# ── PostgreSQL ────────────────────────────────────────────
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a SQLAlchemy async session."""
    async with async_session_factory() as session:
        yield session


# ── Redis ─────────────────────────────────────────────────
redis_pool: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Return (lazily initialise) the Redis connection pool."""
    global redis_pool
    if redis_pool is None:
        redis_pool = redis.from_url(settings.redis_url, decode_responses=True)
    return redis_pool
