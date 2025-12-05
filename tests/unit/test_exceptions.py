"""Unit tests for Custom Exceptions"""

import pytest

from src.core.exceptions import (
    WorkforceException,
    AgentNotFoundError,
    AgentBusyError,
    JobNotFoundError,
    JobExpiredError,
    PlatformRateLimitError,
    QualityCheckFailedError,
    LLMProviderError,
    ConfigurationError,
    DatabaseConnectionError,
    InvalidInputError,
    CircuitBreakerOpenError,
)


@pytest.mark.unit
class TestWorkforceException:
    """Tests for base WorkforceException"""

    def test_basic_creation(self):
        """Exception can be created with message"""
        exc = WorkforceException("Test error")
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.code == "UNKNOWN_ERROR"
        assert exc.recoverable is True

    def test_with_code_and_details(self):
        """Exception accepts code and details"""
        exc = WorkforceException(
            "Custom error",
            code="CUSTOM_ERROR",
            details={"key": "value"},
            recoverable=False,
        )
        assert exc.code == "CUSTOM_ERROR"
        assert exc.details == {"key": "value"}
        assert exc.recoverable is False

    def test_to_dict(self):
        """to_dict returns correct structure"""
        exc = WorkforceException(
            "Test",
            code="TEST",
            details={"foo": "bar"},
        )
        result = exc.to_dict()

        assert result["error"] == "TEST"
        assert result["message"] == "Test"
        assert result["details"] == {"foo": "bar"}
        assert "recoverable" in result


@pytest.mark.unit
class TestAgentExceptions:
    """Tests for Agent-related exceptions"""

    def test_agent_not_found(self):
        """AgentNotFoundError has correct properties"""
        exc = AgentNotFoundError("agent-123")
        assert exc.code == "AGENT_NOT_FOUND"
        assert exc.agent_id == "agent-123"
        assert exc.recoverable is False
        assert "agent-123" in str(exc)

    def test_agent_busy(self):
        """AgentBusyError includes job count"""
        exc = AgentBusyError("agent-456", current_jobs=3)
        assert exc.code == "AGENT_BUSY"
        assert exc.details["current_jobs"] == 3
        assert exc.recoverable is True


@pytest.mark.unit
class TestJobExceptions:
    """Tests for Job-related exceptions"""

    def test_job_not_found(self):
        """JobNotFoundError has correct properties"""
        exc = JobNotFoundError("job-789")
        assert exc.code == "JOB_NOT_FOUND"
        assert exc.job_id == "job-789"
        assert exc.recoverable is False

    def test_job_expired(self):
        """JobExpiredError is not recoverable"""
        exc = JobExpiredError("job-expired")
        assert exc.code == "JOB_EXPIRED"
        assert exc.recoverable is False


@pytest.mark.unit
class TestPlatformExceptions:
    """Tests for Platform-related exceptions"""

    def test_platform_rate_limit(self):
        """PlatformRateLimitError includes retry info"""
        exc = PlatformRateLimitError("upwork", retry_after=60)
        assert exc.code == "PLATFORM_RATE_LIMIT"
        assert exc.platform == "upwork"
        assert exc.retry_after == 60
        assert exc.details["retry_after_seconds"] == 60
        assert exc.recoverable is True


@pytest.mark.unit
class TestQualityExceptions:
    """Tests for Quality-related exceptions"""

    def test_quality_check_failed(self):
        """QualityCheckFailedError includes failed checks"""
        failed_checks = [
            {"check": "grammar", "score": 0.6},
            {"check": "plagiarism", "score": 0.3},
        ]
        exc = QualityCheckFailedError("job-123", failed_checks)
        assert exc.code == "QUALITY_CHECK_FAILED"
        assert exc.failed_checks == failed_checks
        assert exc.recoverable is True


@pytest.mark.unit
class TestLLMExceptions:
    """Tests for LLM-related exceptions"""

    def test_llm_provider_error(self):
        """LLMProviderError includes provider and error"""
        exc = LLMProviderError("anthropic", "Rate limit exceeded")
        assert exc.code == "LLM_PROVIDER_ERROR"
        assert exc.details["provider"] == "anthropic"
        assert "anthropic" in str(exc)


@pytest.mark.unit
class TestDatabaseExceptions:
    """Tests for Database-related exceptions"""

    def test_database_connection_error(self):
        """DatabaseConnectionError is recoverable"""
        exc = DatabaseConnectionError("Connection refused")
        assert exc.code == "DATABASE_CONNECTION_ERROR"
        assert exc.recoverable is True


@pytest.mark.unit
class TestValidationExceptions:
    """Tests for Validation-related exceptions"""

    def test_invalid_input(self):
        """InvalidInputError includes field info"""
        exc = InvalidInputError("email", "Invalid format", value="not-an-email")
        assert exc.code == "INVALID_INPUT"
        assert exc.details["field"] == "email"
        assert exc.details["reason"] == "Invalid format"


@pytest.mark.unit
class TestExternalServiceExceptions:
    """Tests for External Service exceptions"""

    def test_circuit_breaker_open(self):
        """CircuitBreakerOpenError includes service info"""
        exc = CircuitBreakerOpenError("openai", failures=5, timeout=60.0)
        assert exc.code == "CIRCUIT_BREAKER_OPEN"
        assert exc.details["service"] == "openai"
        assert exc.details["failures"] == 5
        assert exc.recoverable is True
