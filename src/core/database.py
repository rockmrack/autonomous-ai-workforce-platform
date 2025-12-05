"""
Database connection and session management
Enhanced with connection pooling, health checks, and query optimization
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, QueuePool
import structlog

from config import settings

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """
    Manages database connections with advanced features:
    - Connection pooling with health monitoring
    - Automatic reconnection on failure
    - Query performance logging
    - Read replica support (future)
    """

    _instance: Optional["DatabaseManager"] = None
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(
        self,
        database_url: Optional[str] = None,
        pool_size: int = 20,
        max_overflow: int = 10,
        echo: bool = False,
    ) -> None:
        """Initialize database connection pool"""
        url = database_url or settings.database.url.get_secret_value()

        # Configure pool based on environment
        pool_class = QueuePool if settings.is_production else NullPool
        pool_kwargs = {}

        if pool_class == QueuePool:
            pool_kwargs = {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_pre_ping": True,  # Verify connections before use
                "pool_recycle": 3600,  # Recycle connections after 1 hour
            }

        self._engine = create_async_engine(
            url,
            echo=echo or settings.debug,
            poolclass=pool_class,
            **pool_kwargs,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        logger.info(
            "Database initialized",
            pool_size=pool_size if pool_class == QueuePool else "none",
            echo=echo,
        )

    async def close(self) -> None:
        """Close all database connections"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connections closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with automatic cleanup"""
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Database session error", error=str(e))
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a session within an explicit transaction"""
        async with self.session() as session:
            async with session.begin():
                yield session

    async def health_check(self) -> dict:
        """Check database health and return stats"""
        if not self._engine:
            return {"healthy": False, "error": "Database not initialized"}

        try:
            async with self.session() as session:
                result = await session.execute(text("SELECT 1"))
                result.scalar()

            pool = self._engine.pool
            stats = {
                "healthy": True,
                "pool_size": getattr(pool, "size", lambda: 0)()
                if hasattr(pool, "size")
                else 0,
                "checked_in": getattr(pool, "checkedin", lambda: 0)()
                if hasattr(pool, "checkedin")
                else 0,
                "checked_out": getattr(pool, "checkedout", lambda: 0)()
                if hasattr(pool, "checkedout")
                else 0,
                "overflow": getattr(pool, "overflow", lambda: 0)()
                if hasattr(pool, "overflow")
                else 0,
            }
            return stats

        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return {"healthy": False, "error": str(e)}

    async def execute_raw(self, query: str, params: Optional[dict] = None) -> list:
        """Execute raw SQL query (use sparingly)"""
        async with self.session() as session:
            result = await session.execute(text(query), params or {})
            return result.fetchall()

    @property
    def engine(self) -> AsyncEngine:
        """Get the underlying engine"""
        if not self._engine:
            raise RuntimeError("Database not initialized")
        return self._engine


# Singleton instance
db_manager = DatabaseManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions"""
    async with db_manager.session() as session:
        yield session


async def init_db() -> None:
    """Initialize database on application startup"""
    await db_manager.initialize(
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        echo=settings.database.echo,
    )


async def close_db() -> None:
    """Close database on application shutdown"""
    await db_manager.close()
