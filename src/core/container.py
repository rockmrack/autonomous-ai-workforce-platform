"""
Dependency Injection Container

Provides centralized dependency management for services,
enabling easier testing and configuration.
"""

from typing import Any, Callable, Dict, Optional, Type, TypeVar
import asyncio
from contextlib import asynccontextmanager
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class DependencyContainer:
    """
    Simple dependency injection container.

    Features:
    - Singleton and factory registrations
    - Async initialization support
    - Scoped dependencies
    - Easy testing with overrides

    Usage:
        container = DependencyContainer()

        # Register singleton
        container.register_singleton(DatabaseManager, db_manager)

        # Register factory
        container.register_factory(LLMClient, lambda: LLMClient())

        # Resolve
        db = container.resolve(DatabaseManager)
    """

    _instance: Optional["DependencyContainer"] = None

    def __new__(cls) -> "DependencyContainer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._singletons: Dict[Type, Any] = {}
            cls._instance._factories: Dict[Type, Callable[[], Any]] = {}
            cls._instance._overrides: Dict[Type, Any] = {}
            cls._instance._initialized = False
        return cls._instance

    def register_singleton(self, interface: Type[T], instance: T) -> None:
        """Register a singleton instance"""
        self._singletons[interface] = instance
        logger.debug("Registered singleton", interface=interface.__name__)

    def register_factory(
        self,
        interface: Type[T],
        factory: Callable[[], T],
        singleton: bool = False
    ) -> None:
        """
        Register a factory function.

        Args:
            interface: The type to register
            factory: Factory function that creates instances
            singleton: If True, cache the first instance created
        """
        if singleton:
            def singleton_factory():
                if interface not in self._singletons:
                    self._singletons[interface] = factory()
                return self._singletons[interface]
            self._factories[interface] = singleton_factory
        else:
            self._factories[interface] = factory
        logger.debug("Registered factory", interface=interface.__name__, singleton=singleton)

    def resolve(self, interface: Type[T]) -> T:
        """
        Resolve a dependency.

        Priority: overrides > singletons > factories
        """
        # Check overrides first (for testing)
        if interface in self._overrides:
            return self._overrides[interface]

        # Check singletons
        if interface in self._singletons:
            return self._singletons[interface]

        # Check factories
        if interface in self._factories:
            return self._factories[interface]()

        raise KeyError(f"No registration found for {interface.__name__}")

    def override(self, interface: Type[T], instance: T) -> None:
        """Override a dependency (useful for testing)"""
        self._overrides[interface] = instance
        logger.debug("Overriding dependency", interface=interface.__name__)

    def clear_overrides(self) -> None:
        """Clear all overrides"""
        self._overrides.clear()

    def clear_all(self) -> None:
        """Clear all registrations"""
        self._singletons.clear()
        self._factories.clear()
        self._overrides.clear()
        self._initialized = False

    @asynccontextmanager
    async def test_scope(self):
        """
        Context manager for test isolation.

        Usage:
            async with container.test_scope():
                container.override(Service, MockService())
                # tests run here
            # overrides automatically cleared
        """
        try:
            yield self
        finally:
            self.clear_overrides()

    async def initialize(self) -> None:
        """Initialize all registered services that need async setup"""
        if self._initialized:
            return

        logger.info("Initializing dependency container")

        # Import here to avoid circular imports
        from src.core.database import db_manager
        from src.core.cache import cache_manager
        from src.llm.client import LLMClient, get_llm_client
        from src.agents.manager import AgentManager
        from src.discovery.discoverer import JobDiscoverer
        from src.bidding.submitter import ProposalSubmitter
        from src.orchestration.scheduler import WorkforceScheduler

        # Register core services
        self.register_singleton(type(db_manager), db_manager)
        self.register_singleton(type(cache_manager), cache_manager)

        # Register LLM client
        self.register_factory(LLMClient, get_llm_client, singleton=True)

        # Register managers with lazy initialization
        self.register_factory(
            AgentManager,
            lambda: AgentManager(
                llm_client=self.resolve(LLMClient)
            ),
            singleton=True
        )

        self.register_factory(
            JobDiscoverer,
            lambda: JobDiscoverer(),
            singleton=True
        )

        self.register_factory(
            ProposalSubmitter,
            lambda: ProposalSubmitter(
                llm_client=self.resolve(LLMClient)
            ),
            singleton=True
        )

        self.register_factory(
            WorkforceScheduler,
            lambda: WorkforceScheduler(),
            singleton=True
        )

        self._initialized = True
        logger.info("Dependency container initialized")

    async def shutdown(self) -> None:
        """Cleanup all services"""
        logger.info("Shutting down dependency container")

        # Cleanup cache
        from src.core.cache import CacheManager
        if CacheManager in self._singletons:
            cache = self._singletons[CacheManager]
            await cache.close()

        # Cleanup database
        from src.core.database import DatabaseManager
        if DatabaseManager in self._singletons:
            db = self._singletons[DatabaseManager]
            await db.close()

        self._initialized = False


# Global container instance
container = DependencyContainer()


def get_container() -> DependencyContainer:
    """Get the global container instance"""
    return container


# FastAPI dependency injection helpers
def get_db_manager():
    """FastAPI dependency for database manager"""
    from src.core.database import DatabaseManager
    return container.resolve(DatabaseManager)


def get_cache_manager():
    """FastAPI dependency for cache manager"""
    from src.core.cache import CacheManager
    return container.resolve(CacheManager)


def get_llm_client():
    """FastAPI dependency for LLM client"""
    from src.llm.client import LLMClient
    return container.resolve(LLMClient)


def get_agent_manager():
    """FastAPI dependency for agent manager"""
    from src.agents.manager import AgentManager
    return container.resolve(AgentManager)


def get_job_discoverer():
    """FastAPI dependency for job discoverer"""
    from src.discovery.discoverer import JobDiscoverer
    return container.resolve(JobDiscoverer)


def get_proposal_submitter():
    """FastAPI dependency for proposal submitter"""
    from src.bidding.submitter import ProposalSubmitter
    return container.resolve(ProposalSubmitter)


def get_scheduler():
    """FastAPI dependency for scheduler"""
    from src.orchestration.scheduler import WorkforceScheduler
    return container.resolve(WorkforceScheduler)
