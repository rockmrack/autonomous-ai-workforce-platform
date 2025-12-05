"""
Caching system with Redis backend
Supports multiple cache strategies and automatic invalidation
"""

import asyncio
import functools
import hashlib
import json
import pickle
from datetime import timedelta
from typing import Any, Callable, Optional, TypeVar, Union

import redis.asyncio as redis
import structlog

from config import settings

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class CacheManager:
    """
    Centralized cache management with Redis backend.

    Features:
    - Multiple serialization formats (JSON, pickle)
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

    def _serialize(self, value: Any, use_json: bool = True) -> bytes:
        """Serialize value for storage"""
        if use_json:
            return json.dumps(value, default=str).encode("utf-8")
        return pickle.dumps(value)

    def _deserialize(self, data: bytes, use_json: bool = True) -> Any:
        """Deserialize stored value"""
        if use_json:
            return json.loads(data.decode("utf-8"))
        return pickle.loads(data)

    async def get(
        self,
        key: str,
        namespace: Optional[str] = None,
        use_json: bool = True,
    ) -> Optional[Any]:
        """Get a value from cache"""
        full_key = self._make_key(key, namespace)
        try:
            data = await self.client.get(full_key)
            if data is None:
                return None
            return self._deserialize(data, use_json)
        except Exception as e:
            logger.warning("Cache get failed", key=full_key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[Union[int, timedelta]] = None,
        namespace: Optional[str] = None,
        use_json: bool = True,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Set a value in cache"""
        full_key = self._make_key(key, namespace)
        try:
            data = self._serialize(value, use_json)

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
        except Exception as e:
            logger.warning("Cache set failed", key=full_key, error=str(e))
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
        use_json: bool = True,
    ) -> Any:
        """Get from cache or compute and cache the result"""
        value = await self.get(key, namespace, use_json)
        if value is not None:
            return value

        # Compute value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        await self.set(key, value, ttl, namespace, use_json)
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
