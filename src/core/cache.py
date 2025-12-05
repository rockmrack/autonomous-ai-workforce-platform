"""
Caching system with Redis backend
Supports multiple cache strategies and automatic invalidation
"""

import asyncio
import functools
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, TypeVar, Union
from uuid import UUID

import redis.asyncio as redis
import structlog

from config import settings

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles common non-serializable types safely"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}
        if isinstance(obj, UUID):
            return {"__type__": "uuid", "value": str(obj)}
        if isinstance(obj, Decimal):
            return {"__type__": "decimal", "value": str(obj)}
        if isinstance(obj, Enum):
            return {"__type__": "enum", "class": obj.__class__.__name__, "value": obj.value}
        if isinstance(obj, bytes):
            return {"__type__": "bytes", "value": obj.decode("utf-8", errors="replace")}
        if isinstance(obj, set):
            return {"__type__": "set", "value": list(obj)}
        # Fallback for other types
        try:
            return str(obj)
        except Exception:
            return f"<non-serializable: {type(obj).__name__}>"


def safe_json_decoder(dct: dict) -> Any:
    """Custom JSON decoder that restores special types"""
    if "__type__" in dct:
        type_name = dct["__type__"]
        value = dct.get("value")

        if type_name == "datetime":
            return datetime.fromisoformat(value)
        if type_name == "uuid":
            return UUID(value)
        if type_name == "decimal":
            return Decimal(value)
        if type_name == "set":
            return set(value)
        if type_name == "bytes":
            return value.encode("utf-8")
        # For enum, return just the value (we lose the enum class info)
        if type_name == "enum":
            return value

    return dct


class CacheManager:
    """
    Centralized cache management with Redis backend.

    Features:
    - Safe JSON serialization (no pickle - security risk)
    - Automatic key namespacing
    - TTL management
    - Cache tags for group invalidation
    - Distributed locking
    """

    _instance: Optional["CacheManager"] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self, redis_url: Optional[str] = None) -> None:
        """Initialize Redis connection"""
        url = redis_url or settings.redis.cache_url
        self._client = redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=False,  # We handle encoding ourselves
        )
        logger.info("Cache manager initialized", url=url)

    async def close(self) -> None:
        """Close Redis connection"""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        if not self._client:
            raise RuntimeError("Cache not initialized. Call initialize() first.")
        return self._client

    def _make_key(self, key: str, namespace: Optional[str] = None) -> str:
        """Create a namespaced cache key"""
        prefix = f"ai_workforce:{namespace}:" if namespace else "ai_workforce:"
        return f"{prefix}{key}"

    def _serialize(self, value: Any) -> bytes:
        """
        Serialize value for storage using safe JSON encoding.
        Note: pickle has been removed due to security risks (arbitrary code execution).
        """
        return json.dumps(value, cls=SafeJSONEncoder).encode("utf-8")

    def _deserialize(self, data: bytes) -> Any:
        """
        Deserialize stored value using safe JSON decoding.
        Note: pickle has been removed due to security risks.
        """
        return json.loads(data.decode("utf-8"), object_hook=safe_json_decoder)

    async def get(
        self,
        key: str,
        namespace: Optional[str] = None,
    ) -> Optional[Any]:
        """Get a value from cache"""
        full_key = self._make_key(key, namespace)
        try:
            data = await self.client.get(full_key)
            if data is None:
                return None
            return self._deserialize(data)
        except json.JSONDecodeError as e:
            logger.warning("Cache deserialization failed", key=full_key, error=str(e))
            # Delete corrupted cache entry
            await self.client.delete(full_key)
            return None
        except redis.RedisError as e:
            logger.warning("Cache get failed (Redis error)", key=full_key, error=str(e))
            return None
        except Exception as e:
            logger.error("Cache get failed (unexpected)", key=full_key, error=str(e), exc_info=True)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[Union[int, timedelta]] = None,
        namespace: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Set a value in cache"""
        full_key = self._make_key(key, namespace)
        try:
            data = self._serialize(value)

            if isinstance(ttl, timedelta):
                ttl = int(ttl.total_seconds())

            await self.client.set(full_key, data, ex=ttl)

            # Track tags for group invalidation
            if tags:
                for tag in tags:
                    tag_key = self._make_key(f"tag:{tag}", "system")
                    await self.client.sadd(tag_key, full_key)
                    if ttl:
                        await self.client.expire(tag_key, ttl + 3600)

            return True
        except (TypeError, ValueError) as e:
            logger.warning("Cache serialization failed", key=full_key, error=str(e))
            return False
        except redis.RedisError as e:
            logger.warning("Cache set failed (Redis error)", key=full_key, error=str(e))
            return False
        except Exception as e:
            logger.error("Cache set failed (unexpected)", key=full_key, error=str(e), exc_info=True)
            return False

    async def delete(self, key: str, namespace: Optional[str] = None) -> bool:
        """Delete a value from cache"""
        full_key = self._make_key(key, namespace)
        try:
            await self.client.delete(full_key)
            return True
        except Exception as e:
            logger.warning("Cache delete failed", key=full_key, error=str(e))
            return False

    async def invalidate_tag(self, tag: str) -> int:
        """Invalidate all cache entries with a specific tag"""
        tag_key = self._make_key(f"tag:{tag}", "system")
        try:
            keys = await self.client.smembers(tag_key)
            if keys:
                await self.client.delete(*keys, tag_key)
                return len(keys)
            return 0
        except Exception as e:
            logger.warning("Cache tag invalidation failed", tag=tag, error=str(e))
            return 0

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: Optional[Union[int, timedelta]] = None,
        namespace: Optional[str] = None,
    ) -> Any:
        """Get from cache or compute and cache the result"""
        value = await self.get(key, namespace)
        if value is not None:
            return value

        # Compute value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        await self.set(key, value, ttl, namespace)
        return value

    async def increment(
        self,
        key: str,
        amount: int = 1,
        namespace: Optional[str] = None,
    ) -> int:
        """Increment a counter"""
        full_key = self._make_key(key, namespace)
        try:
            return await self.client.incrby(full_key, amount)
        except Exception as e:
            logger.warning("Cache increment failed", key=full_key, error=str(e))
            return 0

    async def acquire_lock(
        self,
        name: str,
        timeout: int = 30,
        blocking_timeout: Optional[int] = None,
    ) -> Optional["redis.lock.Lock"]:
        """Acquire a distributed lock"""
        lock_key = self._make_key(name, "locks")
        lock = self.client.lock(
            lock_key,
            timeout=timeout,
            blocking_timeout=blocking_timeout,
        )
        if await lock.acquire():
            return lock
        return None

    async def health_check(self) -> dict:
        """Check cache health"""
        try:
            await self.client.ping()
            info = await self.client.info("memory")
            return {
                "healthy": True,
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}


# Singleton instance
cache_manager = CacheManager()


def cached(
    ttl: Optional[Union[int, timedelta]] = 300,
    namespace: Optional[str] = None,
    key_builder: Optional[Callable[..., str]] = None,
    tags: Optional[list[str]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to cache function results.

    Usage:
        @cached(ttl=300, namespace="jobs")
        async def get_job(job_id: str) -> Job:
            ...

        @cached(ttl=3600, key_builder=lambda x, y: f"{x}:{y}")
        async def compute_something(x: int, y: int) -> int:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            # Build cache key
            if key_builder:
                key = key_builder(*args, **kwargs)
            else:
                # Default key from function name and args
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key = hashlib.md5(":".join(key_parts).encode()).hexdigest()

            # Try cache
            result = await cache_manager.get(key, namespace)
            if result is not None:
                return result

            # Compute and cache
            result = await func(*args, **kwargs)
            await cache_manager.set(key, result, ttl, namespace, tags=tags)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return asyncio.run(async_wrapper(*args, **kwargs))

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
