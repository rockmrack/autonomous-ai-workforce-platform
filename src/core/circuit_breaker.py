"""
Circuit Breaker Pattern Implementation
Prevents cascading failures when external services are unavailable
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Type, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes to close from half-open
    timeout: float = 30.0  # Seconds before trying again (open -> half-open)
    excluded_exceptions: tuple[Type[Exception], ...] = ()  # Don't count these as failures


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""

    def __init__(self, name: str, state: CircuitState, retry_after: float):
        self.name = name
        self.state = state
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is {state.value}. "
            f"Retry after {retry_after:.1f} seconds."
        )


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests are rejected immediately
    - HALF_OPEN: Testing if service recovered, limited requests allowed

    Usage:
        breaker = CircuitBreaker("external_api")

        @breaker
        async def call_external_api():
            ...

        # Or manual usage:
        async with breaker:
            await call_external_api()
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._last_state_change = time.time()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current state, checking for timeout transition"""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_state_change >= self.config.timeout:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state"""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._stats.consecutive_successes = 0

        logger.info(
            "Circuit breaker state change",
            name=self.name,
            old_state=old_state.value,
            new_state=new_state.value,
        )

    def _record_success(self) -> None:
        """Record a successful call"""
        self._stats.total_calls += 1
        self._stats.successful_calls += 1
        self._stats.last_success_time = time.time()
        self._stats.consecutive_failures = 0
        self._stats.consecutive_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            if self._stats.consecutive_successes >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _record_failure(self, error: Exception) -> None:
        """Record a failed call"""
        # Check if this exception type should be excluded
        if isinstance(error, self.config.excluded_exceptions):
            return

        self._stats.total_calls += 1
        self._stats.failed_calls += 1
        self._stats.last_failure_time = time.time()
        self._stats.consecutive_successes = 0
        self._stats.consecutive_failures += 1

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes back to open
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self._stats.consecutive_failures >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def _check_state(self) -> None:
        """Check if requests should be allowed"""
        state = self.state  # This triggers timeout check

        if state == CircuitState.OPEN:
            retry_after = max(
                0,
                self.config.timeout - (time.time() - self._last_state_change)
            )
            self._stats.rejected_calls += 1
            raise CircuitBreakerError(self.name, state, retry_after)

    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry"""
        async with self._lock:
            self._check_state()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit"""
        async with self._lock:
            if exc_type is None:
                self._record_success()
            elif exc_val is not None:
                self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator for protecting functions"""
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                async with self:
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> T:
                # For sync functions, we need to handle state without async lock
                self._check_state()
                try:
                    result = func(*args, **kwargs)
                    self._record_success()
                    return result
                except Exception as e:
                    self._record_failure(e)
                    raise
            return sync_wrapper

    def reset(self) -> None:
        """Manually reset the circuit breaker"""
        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._last_state_change = time.time()
        logger.info("Circuit breaker reset", name=self.name)

    def to_dict(self) -> dict:
        """Get circuit breaker status as dict"""
        return {
            "name": self.name,
            "state": self.state.value,
            "stats": {
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "consecutive_failures": self._stats.consecutive_failures,
                "consecutive_successes": self._stats.consecutive_successes,
            },
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "success_threshold": self.config.success_threshold,
                "timeout": self.config.timeout,
            },
        }


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Usage:
        registry = CircuitBreakerRegistry()

        # Get or create a breaker
        breaker = registry.get("external_api")

        # Get all breakers status
        status = registry.get_all_status()
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _breakers: dict[str, CircuitBreaker]

    def __new__(cls) -> "CircuitBreakerRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._breakers = {}
        return cls._instance

    def get(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker by name"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get_all_status(self) -> dict[str, dict]:
        """Get status of all circuit breakers"""
        return {name: breaker.to_dict() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers"""
        for breaker in self._breakers.values():
            breaker.reset()


# Singleton instance
circuit_breaker_registry = CircuitBreakerRegistry()


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    success_threshold: int = 2,
    timeout: float = 30.0,
    excluded_exceptions: tuple[Type[Exception], ...] = (),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator factory for creating circuit breaker protected functions.

    Usage:
        @circuit_breaker("openai_api", failure_threshold=3, timeout=60)
        async def call_openai(prompt: str):
            ...
    """
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        success_threshold=success_threshold,
        timeout=timeout,
        excluded_exceptions=excluded_exceptions,
    )
    breaker = circuit_breaker_registry.get(name, config)
    return breaker
