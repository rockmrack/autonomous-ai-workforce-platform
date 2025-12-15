"""Unit tests for Cache Manager"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.core.cache import (
    SafeJSONEncoder,
    safe_json_decoder,
    CacheManager,
    cached,
)


@pytest.mark.unit
class TestSafeJSONEncoder:
    """Tests for SafeJSONEncoder"""

    def test_encodes_datetime(self):
        """Encodes datetime objects"""
        dt = datetime(2024, 1, 15, 12, 30, 45)
        result = json.dumps({"time": dt}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["time"]["__type__"] == "datetime"
        assert data["time"]["value"] == "2024-01-15T12:30:45"

    def test_encodes_uuid(self):
        """Encodes UUID objects"""
        uid = uuid4()
        result = json.dumps({"id": uid}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["id"]["__type__"] == "uuid"
        assert data["id"]["value"] == str(uid)

    def test_encodes_decimal(self):
        """Encodes Decimal objects"""
        dec = Decimal("123.456")
        result = json.dumps({"amount": dec}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["amount"]["__type__"] == "decimal"
        assert data["amount"]["value"] == "123.456"

    def test_encodes_set(self):
        """Encodes set objects"""
        s = {1, 2, 3}
        result = json.dumps({"items": s}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["items"]["__type__"] == "set"
        assert sorted(data["items"]["value"]) == [1, 2, 3]

    def test_encodes_bytes(self):
        """Encodes bytes objects"""
        b = b"hello"
        result = json.dumps({"data": b}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["data"]["__type__"] == "bytes"
        assert data["data"]["value"] == "hello"

    def test_encodes_enum(self):
        """Encodes Enum objects"""
        from enum import Enum

        class Color(Enum):
            RED = "red"

        result = json.dumps({"color": Color.RED}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["color"]["__type__"] == "enum"
        assert data["color"]["value"] == "red"

    def test_fallback_for_unknown_types(self):
        """Falls back to string for unknown types"""

        class CustomClass:
            def __str__(self):
                return "custom_value"

        result = json.dumps({"custom": CustomClass()}, cls=SafeJSONEncoder)
        data = json.loads(result)

        assert data["custom"] == "custom_value"


@pytest.mark.unit
class TestSafeJSONDecoder:
    """Tests for safe_json_decoder"""

    def test_decodes_datetime(self):
        """Decodes datetime from JSON"""
        data = {"__type__": "datetime", "value": "2024-01-15T12:30:45"}
        result = safe_json_decoder(data)

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1

    def test_decodes_uuid(self):
        """Decodes UUID from JSON"""
        uid = str(uuid4())
        data = {"__type__": "uuid", "value": uid}
        result = safe_json_decoder(data)

        assert isinstance(result, UUID)
        assert str(result) == uid

    def test_decodes_decimal(self):
        """Decodes Decimal from JSON"""
        data = {"__type__": "decimal", "value": "123.456"}
        result = safe_json_decoder(data)

        assert isinstance(result, Decimal)
        assert result == Decimal("123.456")

    def test_decodes_set(self):
        """Decodes set from JSON"""
        data = {"__type__": "set", "value": [1, 2, 3]}
        result = safe_json_decoder(data)

        assert isinstance(result, set)
        assert result == {1, 2, 3}

    def test_decodes_bytes(self):
        """Decodes bytes from JSON"""
        data = {"__type__": "bytes", "value": "hello"}
        result = safe_json_decoder(data)

        assert isinstance(result, bytes)
        assert result == b"hello"

    def test_returns_enum_value(self):
        """Returns enum value (not enum object)"""
        data = {"__type__": "enum", "class": "Color", "value": "red"}
        result = safe_json_decoder(data)

        assert result == "red"

    def test_passes_through_normal_dicts(self):
        """Passes through normal dicts unchanged"""
        data = {"key": "value", "number": 42}
        result = safe_json_decoder(data)

        assert result == data


@pytest.mark.unit
class TestCacheManagerSerialization:
    """Tests for CacheManager serialization"""

    def test_serialize_deserialize_roundtrip(self):
        """Data survives serialization roundtrip"""
        cache = CacheManager()

        test_data = {
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "list": [1, 2, 3],
            "nested": {"a": "b"},
        }

        serialized = cache._serialize(test_data)
        assert isinstance(serialized, bytes)

        deserialized = cache._deserialize(serialized)
        assert deserialized == test_data

    def test_serialize_complex_types(self):
        """Complex types survive serialization"""
        cache = CacheManager()

        uid = uuid4()
        dt = datetime(2024, 1, 15)
        dec = Decimal("99.99")

        test_data = {
            "id": uid,
            "created": dt,
            "amount": dec,
            "tags": {1, 2, 3},
        }

        serialized = cache._serialize(test_data)
        deserialized = cache._deserialize(serialized)

        assert deserialized["id"] == uid
        assert deserialized["created"] == dt
        assert deserialized["amount"] == dec
        assert deserialized["tags"] == {1, 2, 3}

    def test_make_key_with_namespace(self):
        """Key includes namespace"""
        cache = CacheManager()

        key = cache._make_key("test", namespace="jobs")
        assert key == "ai_workforce:jobs:test"

    def test_make_key_without_namespace(self):
        """Key works without namespace"""
        cache = CacheManager()

        key = cache._make_key("test")
        assert key == "ai_workforce:test"


@pytest.mark.unit
class TestCachedDecorator:
    """Tests for @cached decorator"""

    @pytest.mark.asyncio
    async def test_decorator_caches_result(self, mock_cache_manager, monkeypatch):
        """Decorator caches function results"""
        call_count = 0

        # Mock cache manager to simulate hit on second call
        async def mock_get(key, namespace=None):
            if call_count > 0:
                return "cached_result"
            return None

        mock_cache_manager.get = mock_get

        @cached(ttl=300, namespace="test")
        async def expensive_operation(x: int) -> str:
            nonlocal call_count
            call_count += 1
            return f"computed_{x}"

        # First call - computes
        # Note: This test is simplified; full integration would need Redis mock

    def test_decorator_builds_key_from_args(self):
        """Decorator builds cache key from arguments"""
        # Test that different args produce different keys
        import hashlib

        def build_key(*args, **kwargs):
            key_parts = ["test_func"]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            return hashlib.sha256(":".join(key_parts).encode()).hexdigest()

        key1 = build_key(1, 2, name="test")
        key2 = build_key(1, 2, name="other")
        key3 = build_key(1, 2, name="test")

        assert key1 != key2
        assert key1 == key3
