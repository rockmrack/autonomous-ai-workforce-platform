"""
FastAPI Application - Main API for the AI Workforce Platform
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from config import settings
from src.core.database import init_db, close_db
from src.core.cache import cache_manager
from src.core.exceptions import WorkforceException
from src.core.container import container, get_container
from src.orchestration.scheduler import workforce_scheduler
from src.api.middleware.auth import AuthMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - startup and shutdown events"""
    # Startup
    logger.info("Starting AI Workforce Platform")

    # Initialize database
    await init_db()

    # Initialize cache
    await cache_manager.initialize()

    # Initialize dependency container
    await container.initialize()

    # Start scheduler (if enabled)
    if settings.features.auto_bidding:
        await workforce_scheduler.start()

    logger.info("AI Workforce Platform started")

    yield

    # Shutdown
    logger.info("Shutting down AI Workforce Platform")

    # Stop scheduler
    await workforce_scheduler.stop()

    # Shutdown container (handles cache and db cleanup)
    await container.shutdown()

    logger.info("AI Workforce Platform stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="AI Workforce Platform",
        description="Autonomous AI agent management and orchestration",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
    )

    # Authentication middleware (must be added before CORS)
    app.add_middleware(
        AuthMiddleware,
        api_key=settings.api_key.get_secret_value(),
    )

    # CORS middleware - use configured allowed origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    )

    # Exception handlers
    @app.exception_handler(WorkforceException)
    async def workforce_exception_handler(
        request: Request,
        exc: WorkforceException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400 if exc.recoverable else 500,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error("Unhandled exception", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    # Include routers
    from .routes import agents, jobs, proposals, system
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(proposals.router, prefix="/api/proposals", tags=["proposals"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "version": "2.0.0",
            "scheduler_running": workforce_scheduler.is_running,
        }

    return app


# Create app instance
app = create_app()
