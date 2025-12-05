"""
Pytest configuration and fixtures for AI Workforce Platform tests
"""

import asyncio
import os
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Set test environment before importing app modules
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["API_KEY"] = "test-api-key-with-32-characters-minimum"
os.environ["SECRET_KEY"] = "test-secret-key-with-32-characters-minimum"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["OPENAI_API_KEY"] = "test-openai-key"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session"""
    from src.core.database import Base

    # Create in-memory SQLite engine for tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client"""
    client = MagicMock()
    client.generate = AsyncMock(return_value="Test generated response")
    client.chat = AsyncMock(return_value=MagicMock(
        content="Test chat response",
        model="test-model",
        tokens_input=100,
        tokens_output=50,
        latency_ms=100,
        cost_estimate=0.001,
    ))
    client.stream = AsyncMock()
    client.get_embedding = AsyncMock(return_value=[0.1] * 1536)
    return client


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    """Create a mock cache manager"""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    cache.invalidate_tag = AsyncMock(return_value=0)
    return cache


@pytest.fixture
def mock_platform_client() -> MagicMock:
    """Create a mock platform client (Upwork, Fiverr, etc.)"""
    client = MagicMock()
    client.search_jobs = AsyncMock(return_value=[])
    client.submit_proposal = AsyncMock(return_value={"success": True, "proposal_id": "test-123"})
    client.withdraw_proposal = AsyncMock(return_value={"success": True})
    client.send_message = AsyncMock(return_value={"success": True})
    client.get_conversations = AsyncMock(return_value=[])
    return client


@pytest.fixture
def sample_agent_data() -> dict:
    """Sample data for creating an agent"""
    return {
        "name": "Test Agent",
        "email": f"test-{uuid4().hex[:8]}@example.com",
        "persona": {
            "name": "Alex Thompson",
            "title": "Senior Full Stack Developer",
            "experience_years": 8,
            "skills": ["Python", "JavaScript", "React", "FastAPI"],
            "bio": "Experienced developer with a passion for clean code.",
            "communication_style": "professional",
            "hourly_rate": 75.0,
        },
        "platforms": ["upwork", "fiverr"],
        "max_concurrent_jobs": 3,
    }


@pytest.fixture
def sample_job_data() -> dict:
    """Sample data for a discovered job"""
    return {
        "platform": "upwork",
        "platform_job_id": f"job-{uuid4().hex[:8]}",
        "title": "Build a FastAPI Backend",
        "description": "Need an experienced Python developer to build a REST API.",
        "budget_min": 1000.0,
        "budget_max": 2000.0,
        "budget_type": "fixed",
        "client_name": "Test Client",
        "client_rating": 4.8,
        "client_jobs_posted": 25,
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "job_type": "fixed",
        "duration_estimate": "1-2 weeks",
        "url": "https://example.com/job/123",
    }


@pytest.fixture
def sample_proposal_data() -> dict:
    """Sample data for a proposal"""
    return {
        "cover_letter": "I am excited to apply for this position...",
        "bid_amount": 1500.0,
        "estimated_duration": "10 days",
        "milestones": [
            {"title": "Project Setup", "amount": 300.0, "duration": "2 days"},
            {"title": "Core Development", "amount": 900.0, "duration": "5 days"},
            {"title": "Testing & Delivery", "amount": 300.0, "duration": "3 days"},
        ],
    }


@pytest.fixture
def auth_headers() -> dict:
    """Authentication headers for API tests"""
    return {"X-API-Key": os.environ["API_KEY"]}


@pytest_asyncio.fixture
async def test_client():
    """Create a test client for API tests"""
    from httpx import AsyncClient, ASGITransport
    from src.api.main import app

    # Use ASGITransport for testing
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_container():
    """Mock dependency injection container for testing"""
    from src.core.container import DependencyContainer

    container = DependencyContainer()

    # Clear any existing registrations
    container.clear_all()

    yield container

    # Cleanup
    container.clear_all()


# Utility fixtures for common test patterns


@pytest.fixture
def random_uuid() -> str:
    """Generate a random UUID string"""
    return str(uuid4())


@pytest.fixture
def freeze_time():
    """Fixture for freezing time in tests"""
    from datetime import datetime
    from unittest.mock import patch

    frozen_time = datetime(2024, 1, 15, 12, 0, 0)

    with patch("datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = frozen_time
        mock_datetime.utcnow.return_value = frozen_time
        yield frozen_time


# Markers for test categorization
def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "external: Tests requiring external services")
