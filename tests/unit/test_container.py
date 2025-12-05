"""Unit tests for Dependency Injection Container"""

import pytest

from src.core.container import DependencyContainer


class MockService:
    """Mock service for testing"""
    def __init__(self, value: str = "default"):
        self.value = value


class AnotherService:
    """Another mock service"""
    def __init__(self, dependency: MockService):
        self.dependency = dependency


@pytest.mark.unit
class TestDependencyContainer:
    """Tests for DependencyContainer"""

    def test_register_singleton(self):
        """Can register and resolve a singleton"""
        container = DependencyContainer()
        container.clear_all()

        instance = MockService("singleton")
        container.register_singleton(MockService, instance)

        resolved = container.resolve(MockService)
        assert resolved is instance
        assert resolved.value == "singleton"

    def test_register_factory(self):
        """Can register and resolve via factory"""
        container = DependencyContainer()
        container.clear_all()

        container.register_factory(MockService, lambda: MockService("factory"))

        resolved = container.resolve(MockService)
        assert resolved.value == "factory"

    def test_factory_creates_new_instances(self):
        """Non-singleton factory creates new instances"""
        container = DependencyContainer()
        container.clear_all()

        container.register_factory(MockService, lambda: MockService("new"))

        instance1 = container.resolve(MockService)
        instance2 = container.resolve(MockService)

        assert instance1 is not instance2

    def test_singleton_factory(self):
        """Singleton factory reuses instance"""
        container = DependencyContainer()
        container.clear_all()

        container.register_factory(
            MockService,
            lambda: MockService("singleton-factory"),
            singleton=True
        )

        instance1 = container.resolve(MockService)
        instance2 = container.resolve(MockService)

        assert instance1 is instance2

    def test_override(self):
        """Override takes precedence"""
        container = DependencyContainer()
        container.clear_all()

        original = MockService("original")
        override = MockService("override")

        container.register_singleton(MockService, original)
        container.override(MockService, override)

        resolved = container.resolve(MockService)
        assert resolved is override

    def test_clear_overrides(self):
        """clear_overrides removes overrides"""
        container = DependencyContainer()
        container.clear_all()

        original = MockService("original")
        override = MockService("override")

        container.register_singleton(MockService, original)
        container.override(MockService, override)
        container.clear_overrides()

        resolved = container.resolve(MockService)
        assert resolved is original

    def test_clear_all(self):
        """clear_all removes all registrations"""
        container = DependencyContainer()

        container.register_singleton(MockService, MockService())
        container.clear_all()

        with pytest.raises(KeyError):
            container.resolve(MockService)

    def test_resolve_unregistered_raises(self):
        """Resolving unregistered type raises KeyError"""
        container = DependencyContainer()
        container.clear_all()

        with pytest.raises(KeyError) as exc_info:
            container.resolve(MockService)

        assert "MockService" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_test_scope_context_manager(self):
        """test_scope clears overrides on exit"""
        container = DependencyContainer()
        container.clear_all()

        original = MockService("original")
        container.register_singleton(MockService, original)

        async with container.test_scope():
            container.override(MockService, MockService("test"))
            resolved = container.resolve(MockService)
            assert resolved.value == "test"

        # After scope, override should be cleared
        resolved = container.resolve(MockService)
        assert resolved is original

    def test_dependency_injection_chain(self):
        """Dependencies can depend on other dependencies"""
        container = DependencyContainer()
        container.clear_all()

        container.register_factory(
            MockService,
            lambda: MockService("base"),
            singleton=True
        )
        container.register_factory(
            AnotherService,
            lambda: AnotherService(container.resolve(MockService))
        )

        service = container.resolve(AnotherService)
        assert service.dependency.value == "base"
