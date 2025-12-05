"""
Intelligent Rate Limiter
Manages rate limits with human-like patterns and adaptive backoff
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

import structlog

from src.core.cache import cache_manager
from src.core.events import event_bus

logger = structlog.get_logger(__name__)


class RateLimiter:
    """
    Intelligent rate limiter with human-like timing patterns.

    Features:
    - Per-platform, per-action rate limits
    - Adaptive backoff on rate limit detection
    - Human-like timing variance
    - Automatic recovery
    """

    # Default rate limits per platform
    DEFAULT_LIMITS = {
        "upwork": {
            "proposal_submit": {"per_minute": 1, "per_hour": 10, "per_day": 30},
            "profile_view": {"per_minute": 5, "per_hour": 50, "per_day": 200},
            "message_send": {"per_minute": 3, "per_hour": 30, "per_day": 100},
            "job_search": {"per_minute": 2, "per_hour": 20, "per_day": 100},
        },
        "fiverr": {
            "proposal_submit": {"per_minute": 1, "per_hour": 8, "per_day": 25},
            "message_send": {"per_minute": 2, "per_hour": 20, "per_day": 80},
        },
        "reddit": {
            "post_create": {"per_minute": 1, "per_hour": 5, "per_day": 20},
            "comment_create": {"per_minute": 2, "per_hour": 15, "per_day": 50},
        },
        "default": {
            "default": {"per_minute": 5, "per_hour": 50, "per_day": 200},
        },
    }

    def __init__(self):
        self.backoff_base = 60  # Base backoff in seconds
        self.max_backoff = 3600  # Max backoff (1 hour)

    async def check_and_wait(
        self,
        platform: str,
        action: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """
        Check rate limit and wait if necessary.

        Returns True if action can proceed, False if blocked.
        """
        key = self._make_key(platform, action, agent_id)

        # Check if in backoff
        backoff_key = f"{key}:backoff"
        backoff_until = await cache_manager.get(backoff_key)

        if backoff_until:
            backoff_dt = datetime.fromisoformat(backoff_until)
            if datetime.utcnow() < backoff_dt:
                wait_seconds = (backoff_dt - datetime.utcnow()).total_seconds()
                logger.info(
                    "In backoff period",
                    platform=platform,
                    action=action,
                    wait_seconds=wait_seconds,
                )
                return False

        # Get limits
        limits = self._get_limits(platform, action)

        # Check current counts
        counts = await self._get_counts(key)

        # Check against limits
        if counts["minute"] >= limits["per_minute"]:
            await self._wait_with_jitter(60)
            return await self.check_and_wait(platform, action, agent_id)

        if counts["hour"] >= limits["per_hour"]:
            logger.warning(
                "Hourly rate limit reached",
                platform=platform,
                action=action,
            )
            return False

        if counts["day"] >= limits["per_day"]:
            logger.warning(
                "Daily rate limit reached",
                platform=platform,
                action=action,
            )
            return False

        # Add human-like delay before action
        await self._human_delay()

        # Increment counts
        await self._increment_counts(key)

        return True

    async def record_rate_limit_hit(
        self,
        platform: str,
        action: str,
        agent_id: Optional[str] = None,
    ) -> None:
        """
        Record that we hit a rate limit and initiate backoff.
        """
        key = self._make_key(platform, action, agent_id)

        # Get current backoff multiplier
        multiplier_key = f"{key}:multiplier"
        multiplier = await cache_manager.get(multiplier_key) or 1.0

        # Calculate backoff time
        backoff_seconds = min(
            self.backoff_base * multiplier,
            self.max_backoff,
        )

        # Add jitter
        backoff_seconds *= random.uniform(0.8, 1.2)

        backoff_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)

        # Store backoff
        backoff_key = f"{key}:backoff"
        await cache_manager.set(
            backoff_key,
            backoff_until.isoformat(),
            ttl=int(backoff_seconds) + 60,
        )

        # Increase multiplier for next time
        await cache_manager.set(
            multiplier_key,
            multiplier * 2,
            ttl=3600 * 24,  # Reset after 24 hours
        )

        logger.warning(
            "Rate limit hit - entering backoff",
            platform=platform,
            action=action,
            backoff_seconds=backoff_seconds,
            multiplier=multiplier,
        )

        # Emit event
        await event_bus.emit(
            "safety.rate_limit_hit",
            {
                "platform": platform,
                "action": action,
                "agent_id": agent_id,
                "backoff_seconds": backoff_seconds,
            },
        )

    async def get_wait_time(
        self,
        platform: str,
        action: str,
        agent_id: Optional[str] = None,
    ) -> float:
        """
        Get recommended wait time before next action.
        Returns 0 if action can proceed immediately.
        """
        key = self._make_key(platform, action, agent_id)

        # Check backoff
        backoff_key = f"{key}:backoff"
        backoff_until = await cache_manager.get(backoff_key)

        if backoff_until:
            backoff_dt = datetime.fromisoformat(backoff_until)
            if datetime.utcnow() < backoff_dt:
                return (backoff_dt - datetime.utcnow()).total_seconds()

        # Check minute limit
        limits = self._get_limits(platform, action)
        counts = await self._get_counts(key)

        if counts["minute"] >= limits["per_minute"]:
            # Calculate time until minute resets
            minute_reset = await cache_manager.get(f"{key}:minute:reset")
            if minute_reset:
                reset_dt = datetime.fromisoformat(minute_reset)
                return max(0, (reset_dt - datetime.utcnow()).total_seconds())
            return 60

        return 0

    async def reset_backoff(
        self,
        platform: str,
        action: str,
        agent_id: Optional[str] = None,
    ) -> None:
        """
        Reset backoff state after successful operations.
        """
        key = self._make_key(platform, action, agent_id)

        # Clear backoff
        await cache_manager.delete(f"{key}:backoff")

        # Decrease multiplier
        multiplier_key = f"{key}:multiplier"
        current = await cache_manager.get(multiplier_key) or 1.0
        new_multiplier = max(1.0, current * 0.5)
        await cache_manager.set(multiplier_key, new_multiplier, ttl=3600 * 24)

    def _make_key(
        self,
        platform: str,
        action: str,
        agent_id: Optional[str],
    ) -> str:
        """Create cache key for rate limit state"""
        if agent_id:
            return f"ratelimit:{platform}:{action}:{agent_id}"
        return f"ratelimit:{platform}:{action}"

    def _get_limits(self, platform: str, action: str) -> dict:
        """Get rate limits for platform/action"""
        platform_limits = self.DEFAULT_LIMITS.get(
            platform,
            self.DEFAULT_LIMITS["default"],
        )
        return platform_limits.get(action, platform_limits.get("default", {
            "per_minute": 5,
            "per_hour": 50,
            "per_day": 200,
        }))

    async def _get_counts(self, key: str) -> dict:
        """Get current rate limit counts"""
        now = datetime.utcnow()

        # Get minute count
        minute_count = await cache_manager.get(f"{key}:minute:count") or 0

        # Check if minute window has passed
        minute_reset = await cache_manager.get(f"{key}:minute:reset")
        if minute_reset:
            reset_dt = datetime.fromisoformat(minute_reset)
            if now >= reset_dt:
                minute_count = 0
                await cache_manager.set(
                    f"{key}:minute:reset",
                    (now + timedelta(minutes=1)).isoformat(),
                    ttl=120,
                )
        else:
            await cache_manager.set(
                f"{key}:minute:reset",
                (now + timedelta(minutes=1)).isoformat(),
                ttl=120,
            )

        # Get hour count
        hour_count = await cache_manager.get(f"{key}:hour:count") or 0

        # Get day count
        day_count = await cache_manager.get(f"{key}:day:count") or 0

        return {
            "minute": minute_count,
            "hour": hour_count,
            "day": day_count,
        }

    async def _increment_counts(self, key: str) -> None:
        """Increment rate limit counters"""
        await cache_manager.increment(f"{key}:minute:count")
        await cache_manager.increment(f"{key}:hour:count")
        await cache_manager.increment(f"{key}:day:count")

    async def _wait_with_jitter(self, base_seconds: float) -> None:
        """Wait with random jitter"""
        jitter = random.uniform(0.5, 1.5)
        await asyncio.sleep(base_seconds * jitter)

    async def _human_delay(self) -> None:
        """Add human-like delay before actions"""
        # Random delay between 0.5 and 3 seconds
        delay = random.uniform(0.5, 3.0)

        # Occasionally longer pauses (like someone thinking)
        if random.random() < 0.1:
            delay += random.uniform(2, 8)

        await asyncio.sleep(delay)


# Singleton instance
rate_limiter = RateLimiter()
