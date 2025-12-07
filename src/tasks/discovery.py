"""
Discovery Tasks - Job scanning and scoring
"""

import asyncio
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
    name="src.tasks.discovery.scan_all_platforms",
    max_retries=3,
    default_retry_delay=60,
)
def scan_all_platforms(self):
    """
    Scan all configured platforms for new jobs.

    Runs periodically via Celery Beat.
    """
    async def _scan():
        from src.discovery.discoverer import job_discoverer
        from config import settings

        platforms = settings.platforms.enabled
        results = {}

        for platform in platforms:
            try:
                jobs = await job_discoverer.discover_jobs(platform)
                results[platform] = {
                    "status": "success",
                    "jobs_found": len(jobs),
                }
                logger.info(f"Discovered {len(jobs)} jobs on {platform}")
            except Exception as e:
                results[platform] = {
                    "status": "error",
                    "error": str(e),
                }
                logger.error(f"Failed to scan {platform}: {e}")

        return results

    try:
        return run_async(_scan())
    except Exception as exc:
        logger.error(f"scan_all_platforms failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.discovery.scan_platform",
    max_retries=3,
    default_retry_delay=30,
)
def scan_platform(self, platform: str, search_params: Optional[dict] = None):
    """
    Scan a specific platform for jobs.

    Args:
        platform: Platform name (upwork, fiverr, reddit)
        search_params: Optional search parameters
    """
    async def _scan():
        from src.discovery.discoverer import job_discoverer

        jobs = await job_discoverer.discover_jobs(
            platform=platform,
            search_params=search_params or {},
        )

        # Queue scoring for discovered jobs
        for job in jobs:
            score_jobs.delay([str(job.id)])

        return {
            "platform": platform,
            "jobs_found": len(jobs),
            "job_ids": [str(job.id) for job in jobs[:20]],  # Return first 20
        }

    try:
        return run_async(_scan())
    except Exception as exc:
        logger.error(f"scan_platform failed for {platform}: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.discovery.score_jobs",
    max_retries=2,
    default_retry_delay=10,
)
def score_jobs(self, job_ids: list[str]):
    """
    Score discovered jobs for agent matching.

    Args:
        job_ids: List of job IDs to score
    """
    async def _score():
        from uuid import UUID
        from src.discovery.scorer import job_scorer
        from src.core.database import db_manager
        from src.discovery.models import DiscoveredJob
        from sqlalchemy import select

        scored_count = 0

        async with db_manager.session() as session:
            for job_id in job_ids:
                try:
                    result = await session.execute(
                        select(DiscoveredJob).where(
                            DiscoveredJob.id == UUID(job_id)
                        )
                    )
                    job = result.scalar_one_or_none()

                    if job and not job.is_scored:
                        score_result = await job_scorer.score_job(job)
                        job.score = score_result.overall_score
                        job.score_breakdown = score_result.breakdown
                        job.is_scored = True
                        scored_count += 1

                except Exception as e:
                    logger.error(f"Failed to score job {job_id}: {e}")

            await session.commit()

        return {"scored_count": scored_count}

    try:
        return run_async(_score())
    except Exception as exc:
        logger.error(f"score_jobs failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    name="src.tasks.discovery.match_agents_to_job",
)
def match_agents_to_job(job_id: str):
    """
    Find best agents for a discovered job.

    Args:
        job_id: Job ID to match
    """
    async def _match():
        from uuid import UUID
        from src.agents.manager import agent_manager
        from src.core.database import db_manager
        from src.discovery.models import DiscoveredJob
        from sqlalchemy import select

        async with db_manager.session() as session:
            result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == UUID(job_id))
            )
            job = result.scalar_one_or_none()

            if not job:
                return {"error": "Job not found"}

            # Find matching agents
            matches = await agent_manager.find_agents_for_job(job)

            return {
                "job_id": job_id,
                "matches": [
                    {
                        "agent_id": str(m.agent.id),
                        "score": m.match_score,
                    }
                    for m in matches[:5]
                ],
            }

    return run_async(_match())


@shared_task(
    name="src.tasks.discovery.auto_apply_to_job",
)
def auto_apply_to_job(job_id: str, agent_id: str):
    """
    Automatically apply to a job with an agent.

    Args:
        job_id: Job to apply to
        agent_id: Agent to use
    """
    async def _apply():
        from uuid import UUID
        from src.bidding.submitter import proposal_submitter

        result = await proposal_submitter.submit_proposal(
            job_id=UUID(job_id),
            agent_id=UUID(agent_id),
        )

        return {
            "job_id": job_id,
            "agent_id": agent_id,
            "proposal_id": str(result.id) if result else None,
            "status": "submitted" if result else "failed",
        }

    return run_async(_apply())
