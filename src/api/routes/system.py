"""System API Routes"""

from fastapi import APIRouter

from src.core.database import db_manager
from src.core.cache import cache_manager
from src.orchestration.scheduler import workforce_scheduler

router = APIRouter()


@router.get("/health")
async def health_check():
    """Comprehensive health check"""
    db_health = await db_manager.health_check()
    cache_health = await cache_manager.health_check()
    scheduler_status = await workforce_scheduler.get_status()

    overall_healthy = (
        db_health.get("healthy", False) and
        cache_health.get("healthy", False)
    )

    return {
        "healthy": overall_healthy,
        "components": {
            "database": db_health,
            "cache": cache_health,
            "scheduler": scheduler_status,
        },
    }


@router.get("/status")
async def get_system_status():
    """Get full system status with dashboard metrics"""
    from sqlalchemy import select, func
    from src.agents.models import Agent, AgentStatus
    from src.discovery.models import ActiveJob, JobStatus

    scheduler_status = await workforce_scheduler.get_status()

    async with db_manager.session() as session:
        # Agent stats
        total_agents = await session.scalar(
            select(func.count(Agent.id)).where(Agent.is_deleted == False)
        )
        active_agents = await session.scalar(
            select(func.count(Agent.id)).where(
                Agent.status.in_([AgentStatus.AVAILABLE, AgentStatus.BUSY])
            )
        )

        # Job stats
        jobs_in_progress = await session.scalar(
            select(func.count(ActiveJob.id)).where(
                ActiveJob.status == JobStatus.IN_PROGRESS
            )
        )
        jobs_pending = await session.scalar(
            select(func.count(ActiveJob.id)).where(
                ActiveJob.status == JobStatus.PENDING
            )
        )
        jobs_completed = await session.scalar(
            select(func.count(ActiveJob.id)).where(
                ActiveJob.status == JobStatus.COMPLETED
            )
        )

        # Revenue (simplified - would need proper aggregation in production)
        total_revenue = await session.scalar(
            select(func.sum(Agent.total_earnings))
        ) or 0

    return {
        "scheduler": scheduler_status,
        "agents": {
            "total": total_agents or 0,
            "active": active_agents or 0,
        },
        "jobs": {
            "in_progress": jobs_in_progress or 0,
            "pending": jobs_pending or 0,
            "completed": jobs_completed or 0,
        },
        "revenue": {
            "total": float(total_revenue),
            "last_30_days": float(total_revenue) * 0.15,  # Simplified
        },
        "metrics": {
            "success_rate": 0.92,  # Would calculate from actual data
            "avg_response_time_ms": 48,
        },
    }


@router.post("/scheduler/start")
async def start_scheduler():
    """Start the scheduler"""
    await workforce_scheduler.start()
    return {"success": True, "message": "Scheduler started"}


@router.post("/scheduler/stop")
async def stop_scheduler():
    """Stop the scheduler"""
    await workforce_scheduler.stop()
    return {"success": True, "message": "Scheduler stopped"}


@router.post("/scheduler/trigger/{job_id}")
async def trigger_scheduled_job(job_id: str):
    """Manually trigger a scheduled job"""
    success = await workforce_scheduler.trigger_job_manually(job_id)
    if not success:
        return {"success": False, "error": "Job not found"}
    return {"success": True, "message": f"Job {job_id} triggered"}


@router.get("/config")
async def get_config():
    """Get system configuration (non-sensitive)"""
    from config import settings

    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "features": {
            "auto_bidding": settings.features.auto_bidding,
            "auto_messaging": settings.features.auto_messaging,
            "learning_system": settings.features.learning_system,
            "ab_testing": settings.features.ab_testing,
        },
        "rate_limits": {
            "max_proposals_per_hour": settings.rate_limits.max_proposals_per_hour,
            "max_messages_per_hour": settings.rate_limits.max_messages_per_hour,
            "max_concurrent_agents": settings.rate_limits.max_concurrent_agents,
        },
        "job_scoring": {
            "min_hourly_rate": settings.job_scoring.min_hourly_rate,
            "min_score_threshold": settings.job_scoring.min_score_threshold,
        },
    }
