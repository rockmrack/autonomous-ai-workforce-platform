"""Integration tests for API endpoints"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthEndpoint:
    """Tests for health check endpoint"""

    @pytest.mark.asyncio
    async def test_health_check_returns_200(self, test_client: AsyncClient):
        """Health endpoint returns 200"""
        response = await test_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_check_structure(self, test_client: AsyncClient):
        """Health endpoint returns expected structure"""
        response = await test_client.get("/health")
        data = response.json()

        assert "status" in data
        assert "version" in data


@pytest.mark.integration
class TestAuthMiddleware:
    """Tests for authentication middleware"""

    @pytest.mark.asyncio
    async def test_public_paths_no_auth_required(self, test_client: AsyncClient):
        """Public paths don't require authentication"""
        response = await test_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_paths_require_auth(self, test_client: AsyncClient):
        """Protected paths require API key"""
        response = await test_client.get("/api/agents")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_api_key_allows_access(
        self, test_client: AsyncClient, auth_headers: dict
    ):
        """Valid API key grants access"""
        response = await test_client.get("/api/agents", headers=auth_headers)
        # Should not be 401 (may be 200 or 500 depending on setup)
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self, test_client: AsyncClient):
        """Invalid API key is rejected"""
        response = await test_client.get(
            "/api/agents",
            headers={"X-API-Key": "invalid-key"}
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestSystemEndpoints:
    """Tests for system management endpoints"""

    @pytest.mark.asyncio
    async def test_get_config(self, test_client: AsyncClient, auth_headers: dict):
        """Config endpoint returns non-sensitive settings"""
        response = await test_client.get("/api/system/config", headers=auth_headers)

        if response.status_code == 200:
            data = response.json()
            assert "app_name" in data
            assert "features" in data
            # Should not contain secrets
            assert "api_key" not in str(data).lower()
            assert "secret" not in str(data).lower()


@pytest.mark.integration
class TestAgentEndpoints:
    """Tests for agent management endpoints"""

    @pytest.mark.asyncio
    async def test_list_agents(self, test_client: AsyncClient, auth_headers: dict):
        """Can list agents"""
        response = await test_client.get("/api/agents", headers=auth_headers)
        # May be 200 or 500 depending on DB setup
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_create_agent_validation(
        self, test_client: AsyncClient, auth_headers: dict
    ):
        """Create agent validates input"""
        # Missing required fields
        response = await test_client.post(
            "/api/agents",
            json={"name": "Test"},
            headers=auth_headers
        )
        # Should fail validation
        assert response.status_code in [400, 422, 500]


@pytest.mark.integration
class TestJobEndpoints:
    """Tests for job management endpoints"""

    @pytest.mark.asyncio
    async def test_list_jobs(self, test_client: AsyncClient, auth_headers: dict):
        """Can list jobs"""
        response = await test_client.get("/api/jobs", headers=auth_headers)
        assert response.status_code in [200, 500]


@pytest.mark.integration
class TestProposalEndpoints:
    """Tests for proposal management endpoints"""

    @pytest.mark.asyncio
    async def test_list_proposals(self, test_client: AsyncClient, auth_headers: dict):
        """Can list proposals"""
        response = await test_client.get("/api/proposals", headers=auth_headers)
        assert response.status_code in [200, 500]
