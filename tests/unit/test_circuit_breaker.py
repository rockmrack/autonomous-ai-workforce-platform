"""Unit tests for Circuit Breaker"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitState,
    circuit_breaker,
)


@pytest.mark.unit
class TestCircuitBreaker:
    """Tests for CircuitBreaker class"""

    def test_initial_state_is_closed(self):
        """Circuit breaker starts in closed state"""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    def test_transitions_to_open_after_failures(self):
        """Circuit opens after reaching failure threshold"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        # Simulate failures
        for _ in range(3):
            breaker._record_failure(Exception("test error"))

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    def test_rejects_calls_when_open(self):
        """Open circuit rejects calls"""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=60)
        breaker = CircuitBreaker("test", config)

        # Force open
        breaker._record_failure(Exception("test error"))

        with pytest.raises(CircuitBreakerError) as exc_info:
            breaker._check_state()

        assert exc_info.value.name == "test"
        assert exc_info.value.state == CircuitState.OPEN

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit transitions to half-open after timeout"""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.1)
        breaker = CircuitBreaker("test", config)

        # Force open
        breaker._record_failure(Exception("test error"))
        assert breaker._state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # State property should trigger transition
        assert breaker.state == CircuitState.HALF_OPEN

    def test_closes_after_successes_in_half_open(self):
        """Circuit closes after success threshold in half-open"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout=0.01
        )
        breaker = CircuitBreaker("test", config)

        # Force to half-open
        breaker._record_failure(Exception("test error"))
        time.sleep(0.02)
        _ = breaker.state  # Trigger transition

        assert breaker.state == CircuitState.HALF_OPEN

        # Record successes
        breaker._record_success()
        assert breaker.state == CircuitState.HALF_OPEN

        breaker._record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        """Circuit reopens on failure in half-open state"""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.01)
        breaker = CircuitBreaker("test", config)

        # Force to half-open
        breaker._record_failure(Exception("test error"))
        time.sleep(0.02)
        _ = breaker.state

        assert breaker.state == CircuitState.HALF_OPEN

        # Another failure
        breaker._record_failure(Exception("test error"))
        assert breaker.state == CircuitState.OPEN

    def test_reset_clears_state(self):
        """Reset returns circuit to closed state"""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        # Force open
        breaker._record_failure(Exception("test error"))
        assert breaker.is_open

        breaker.reset()

        assert breaker.is_closed
        assert breaker.stats.total_calls == 0

    def test_excluded_exceptions_not_counted(self):
        """Excluded exceptions don't count as failures"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            excluded_exceptions=(ValueError,)
        )
        breaker = CircuitBreaker("test", config)

        # ValueError should be excluded
        breaker._record_failure(ValueError("ignored"))
        assert breaker.stats.consecutive_failures == 0

        # Other exceptions should count
        breaker._record_failure(RuntimeError("counted"))
        assert breaker.stats.consecutive_failures == 1

    def test_to_dict_output(self):
        """to_dict returns correct structure"""
        breaker = CircuitBreaker("test")
        result = breaker.to_dict()

        assert result["name"] == "test"
        assert result["state"] == "closed"
        assert "stats" in result
        assert "config" in result

    @pytest.mark.asyncio
    async def test_async_context_manager_success(self):
        """Async context manager records success"""
        breaker = CircuitBreaker("test")

        async with breaker:
            pass

        assert breaker.stats.successful_calls == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_failure(self):
        """Async context manager records failure"""
        breaker = CircuitBreaker("test")

        with pytest.raises(RuntimeError):
            async with breaker:
                raise RuntimeError("test error")

        assert breaker.stats.failed_calls == 1

    @pytest.mark.asyncio
    async def test_decorator_protects_async_function(self):
        """Decorator protects async functions"""
        breaker = CircuitBreaker("test")

        @breaker
        async def protected_func():
            return "success"

        result = await protected_func()
        assert result == "success"
        assert breaker.stats.successful_calls == 1


@pytest.mark.unit
class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry"""

    def test_get_creates_new_breaker(self):
        """get() creates a new breaker if not exists"""
        registry = CircuitBreakerRegistry()
        registry._breakers.clear()

        breaker = registry.get("new-service")
        assert breaker.name == "new-service"

    def test_get_returns_same_breaker(self):
        """get() returns the same breaker for same name"""
        registry = CircuitBreakerRegistry()
        registry._breakers.clear()

        breaker1 = registry.get("service")
        breaker2 = registry.get("service")

        assert breaker1 is breaker2

    def test_get_all_status(self):
        """get_all_status returns all breakers"""
        registry = CircuitBreakerRegistry()
        registry._breakers.clear()

        registry.get("service1")
        registry.get("service2")

        status = registry.get_all_status()
        assert "service1" in status
        assert "service2" in status

    def test_reset_all(self):
        """reset_all resets all breakers"""
        registry = CircuitBreakerRegistry()
        registry._breakers.clear()

        breaker = registry.get("service", CircuitBreakerConfig(failure_threshold=1))
        breaker._record_failure(Exception("test"))
        assert breaker.is_open

        registry.reset_all()
        assert breaker.is_closed


@pytest.mark.unit
class TestCircuitBreakerDecorator:
    """Tests for circuit_breaker decorator factory"""

    @pytest.mark.asyncio
    async def test_decorator_creates_breaker(self):
        """Decorator creates circuit breaker"""
        @circuit_breaker("test-decorator", failure_threshold=3)
        async def test_func():
            return "result"

        result = await test_func()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_decorator_opens_on_failures(self):
        """Decorator opens circuit on failures"""
        call_count = 0

        @circuit_breaker("test-failures", failure_threshold=2, timeout=60)
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        # First two calls should go through and fail
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await failing_func()

        # Third call should be rejected by circuit breaker
        with pytest.raises(CircuitBreakerError):
            await failing_func()

        # Only 2 actual calls made
        assert call_count == 2
