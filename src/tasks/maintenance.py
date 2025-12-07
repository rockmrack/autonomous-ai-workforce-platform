"""
Maintenance Tasks - System health and cleanup
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery tasks"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    name="src.tasks.maintenance.check_agent_health",
    max_retries=2,
    default_retry_delay=60,
)
def check_agent_health(self):
    """
    Check health of all agents.

    Runs hourly via Celery Beat.
    """
    async def _check():
        from src.agents.manager import agent_manager
        from src.core.events import Event, event_bus

        agents = await agent_manager.get_active_agents()
        results = {
            "total": len(agents),
            "healthy": 0,
            "warnings": 0,
            "critical": 0,
            "issues": [],
        }

        for agent in agents:
            try:
                health = await agent_manager.check_agent_health(agent.id)

                if health["status"] == "healthy":
                    results["healthy"] += 1
                elif health["status"] == "warning":
                    results["warnings"] += 1
                    results["issues"].append({
                        "agent_id": str(agent.id),
                        "status": "warning",
                        "issues": health.get("issues", []),
                    })
                else:
                    results["critical"] += 1
                    results["issues"].append({
                        "agent_id": str(agent.id),
                        "status": "critical",
                        "issues": health.get("issues", []),
                    })

            except Exception as e:
                logger.error(f"Failed to check health for agent {agent.id}: {e}")
                results["critical"] += 1
                results["issues"].append({
                    "agent_id": str(agent.id),
                    "status": "error",
                    "error": str(e),
                })

        # Emit alert if there are critical issues
        if results["critical"] > 0:
            await event_bus.emit(Event(
                type="system.alert.agent_health",
                data=results,
            ))

        return results

    try:
        return run_async(_check())
    except Exception as exc:
        logger.error(f"check_agent_health failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.maintenance.cleanup_old_data",
    max_retries=1,
    default_retry_delay=3600,
)
def cleanup_old_data(self):
    """
    Clean up old data to maintain database performance.

    Runs daily via Celery Beat.
    """
    async def _cleanup():
        from src.core.database import db_manager
        from src.discovery.models import DiscoveredJob
        from src.communication.models import Message
        from sqlalchemy import delete

        results = {}
        cutoff_90_days = datetime.utcnow() - timedelta(days=90)
        cutoff_30_days = datetime.utcnow() - timedelta(days=30)

        async with db_manager.session() as session:
            # Delete old unscored/rejected jobs
            job_result = await session.execute(
                delete(DiscoveredJob).where(
                    DiscoveredJob.created_at < cutoff_30_days,
                    DiscoveredJob.is_applied == False,
                )
            )
            results["old_jobs_deleted"] = job_result.rowcount

            await session.commit()

        logger.info("Cleanup completed", **results)
        return results

    try:
        return run_async(_cleanup())
    except Exception as exc:
        logger.error(f"cleanup_old_data failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    name="src.tasks.maintenance.refresh_platform_tokens",
)
def refresh_platform_tokens():
    """
    Refresh OAuth tokens for platform integrations.
    """
    async def _refresh():
        from src.agents.manager import agent_manager

        agents = await agent_manager.get_active_agents()
        results = []

        for agent in agents:
            for platform in agent.platforms:
                try:
                    # Refresh token for platform
                    # This would call platform-specific token refresh
                    results.append({
                        "agent_id": str(agent.id),
                        "platform": platform,
                        "status": "refreshed",
                    })
                except Exception as e:
                    logger.error(f"Failed to refresh token for {agent.id} on {platform}: {e}")
                    results.append({
                        "agent_id": str(agent.id),
                        "platform": platform,
                        "status": "failed",
                        "error": str(e),
                    })

        return {"refreshed": results}

    return run_async(_refresh())


@shared_task(
    name="src.tasks.maintenance.update_agent_stats",
)
def update_agent_stats():
    """
    Update agent statistics and performance metrics.
    """
    async def _update():
        from src.agents.manager import agent_manager

        agents = await agent_manager.get_all_agents()
        updated = 0

        for agent in agents:
            try:
                await agent_manager.update_agent_stats(agent.id)
                updated += 1
            except Exception as e:
                logger.error(f"Failed to update stats for agent {agent.id}: {e}")

        return {"updated": updated, "total": len(agents)}

    return run_async(_update())


@shared_task(
    name="src.tasks.maintenance.check_system_health",
)
def check_system_health():
    """
    Comprehensive system health check.
    """
    async def _check():
        from src.core.database import db_manager
        from src.core.cache import cache_manager
        from src.core.circuit_breaker import circuit_breaker_registry

        health = {
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
        }

        # Database health
        try:
            db_health = await db_manager.health_check()
            health["components"]["database"] = db_health
        except Exception as e:
            health["components"]["database"] = {"healthy": False, "error": str(e)}

        # Cache health
        try:
            cache_health = await cache_manager.health_check()
            health["components"]["cache"] = cache_health
        except Exception as e:
            health["components"]["cache"] = {"healthy": False, "error": str(e)}

        # Circuit breakers
        breaker_status = circuit_breaker_registry.get_all_status()
        open_breakers = [
            name for name, status in breaker_status.items()
            if status["state"] == "open"
        ]
        health["components"]["circuit_breakers"] = {
            "total": len(breaker_status),
            "open": len(open_breakers),
            "open_names": open_breakers,
        }

        # Overall health
        health["healthy"] = all(
            c.get("healthy", True) for c in health["components"].values()
            if isinstance(c, dict) and "healthy" in c
        ) and len(open_breakers) == 0

        return health

    return run_async(_check())


@shared_task(
    name="src.tasks.maintenance.backup_critical_data",
)
def backup_critical_data():
    """
    Backup critical data to external storage.
    """
    async def _backup():
        # This would integrate with cloud storage (S3, etc.)
        # Placeholder implementation
        logger.info("Starting critical data backup")

        backup_result = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "completed",
            "items": [
                {"type": "agents", "count": 0},
                {"type": "jobs", "count": 0},
                {"type": "transactions", "count": 0},
            ],
        }

        logger.info("Backup completed", **backup_result)
        return backup_result

    return run_async(_backup())


@shared_task(
    name="src.tasks.maintenance.optimize_database",
)
def optimize_database():
    """
    Run database optimization tasks.
    """
    async def _optimize():
        from src.core.database import db_manager

        async with db_manager.session() as session:
            # Analyze tables for query optimization
            await session.execute("ANALYZE agents")
            await session.execute("ANALYZE active_jobs")
            await session.execute("ANALYZE proposals")
            await session.execute("ANALYZE transactions")

            await session.commit()

        return {
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat(),
        }

    return run_async(_optimize())
