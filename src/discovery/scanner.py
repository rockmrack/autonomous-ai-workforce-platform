"""
Job Scanner - Multi-platform job discovery engine
Scans freelance platforms and aggregates opportunities
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from config import settings
from src.core.database import db_manager
from src.core.events import Event, EventTypes, event_bus
from src.agents.models import AgentCapability
from .models import DiscoveredJob, JobStatus
from .scorer import JobScorer, JobScore
from .platforms.base import BasePlatformClient, RawJob

logger = structlog.get_logger(__name__)


class JobScanner:
    """
    Multi-platform job discovery and scoring engine.

    Features:
    - Parallel platform scanning
    - Intelligent job filtering
    - ML-powered scoring
    - Duplicate detection
    - Rate limit management
    """

    def __init__(
        self,
        platforms: Optional[list[BasePlatformClient]] = None,
        scorer: Optional[JobScorer] = None,
    ):
        self.platforms = platforms or []
        self.scorer = scorer or JobScorer()
        self._scan_intervals: dict[str, int] = {}  # Platform -> minutes

    def register_platform(
        self,
        platform: BasePlatformClient,
        scan_interval_minutes: int = 5,
    ) -> None:
        """Register a platform for scanning"""
        self.platforms.append(platform)
        self._scan_intervals[platform.platform_name] = scan_interval_minutes
        logger.info(
            "Platform registered",
            platform=platform.platform_name,
            interval_minutes=scan_interval_minutes,
        )

    async def scan_all_platforms(
        self,
        available_capabilities: Optional[list[AgentCapability]] = None,
    ) -> list[DiscoveredJob]:
        """
        Scan all registered platforms in parallel.

        Args:
            available_capabilities: Filter for jobs matching these capabilities

        Returns:
            List of newly discovered and scored jobs
        """
        if not self.platforms:
            logger.warning("No platforms registered for scanning")
            return []

        logger.info(
            "Starting multi-platform scan",
            platform_count=len(self.platforms),
        )

        # Scan platforms in parallel
        tasks = [
            self._scan_platform(platform, available_capabilities)
            for platform in self.platforms
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_jobs = []
        for platform, result in zip(self.platforms, results):
            if isinstance(result, Exception):
                logger.error(
                    "Platform scan failed",
                    platform=platform.platform_name,
                    error=str(result),
                )
                continue
            all_jobs.extend(result)

        logger.info(
            "Multi-platform scan complete",
            total_jobs=len(all_jobs),
        )

        return all_jobs

    async def _scan_platform(
        self,
        platform: BasePlatformClient,
        available_capabilities: Optional[list[AgentCapability]] = None,
    ) -> list[DiscoveredJob]:
        """Scan a single platform"""
        try:
            logger.debug("Scanning platform", platform=platform.platform_name)

            # Get raw jobs from platform
            raw_jobs = await platform.fetch_jobs()

            logger.info(
                "Platform scan complete",
                platform=platform.platform_name,
                raw_jobs_found=len(raw_jobs),
            )

            # Process and filter jobs
            processed_jobs = []
            for raw_job in raw_jobs:
                # Check for duplicates
                if await self._is_duplicate(raw_job.platform, raw_job.platform_job_id):
                    continue

                # Convert to DiscoveredJob
                job = self._raw_to_discovered(raw_job)

                # Score the job
                score = await self.scorer.score_job(job, available_capabilities)

                # Update job with score
                job.score = score.total_score
                job.score_breakdown = score.to_dict()
                job.ml_success_probability = score.success_probability
                job.estimated_profit_margin = score.estimated_profit
                job.matched_capabilities = score.matched_capabilities

                # Only keep jobs that pass minimum threshold
                if score.recommended:
                    job.status = JobStatus.SCORED
                    processed_jobs.append(job)

                    # Emit event
                    await event_bus.emit(Event(
                        event_type=EventTypes.JOB_DISCOVERED,
                        data={
                            "platform": raw_job.platform,
                            "job_id": raw_job.platform_job_id,
                            "title": raw_job.title,
                            "score": score.total_score,
                        },
                        source="job_scanner",
                    ))

            # Save jobs to database
            if processed_jobs:
                await self._save_jobs(processed_jobs)

            return processed_jobs

        except Exception as e:
            logger.error(
                "Error scanning platform",
                platform=platform.platform_name,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _is_duplicate(self, platform: str, platform_job_id: str) -> bool:
        """Check if job already exists in database"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(DiscoveredJob.id).where(
                    and_(
                        DiscoveredJob.platform == platform,
                        DiscoveredJob.platform_job_id == platform_job_id,
                    )
                ).limit(1)
            )
            return result.scalar_one_or_none() is not None

    def _raw_to_discovered(self, raw: RawJob) -> DiscoveredJob:
        """Convert raw job data to DiscoveredJob model"""
        return DiscoveredJob(
            platform=raw.platform,
            platform_job_id=raw.platform_job_id,
            source_url=raw.source_url,
            title=raw.title,
            description=raw.description,
            category=raw.category,
            subcategory=raw.subcategory,
            budget_min=raw.budget_min,
            budget_max=raw.budget_max,
            budget_type=raw.budget_type,
            currency=raw.currency or "USD",
            skills_required=raw.skills_required or [],
            experience_level=raw.experience_level,
            estimated_hours=raw.estimated_hours,
            estimated_duration=raw.estimated_duration,
            client_id=raw.client_id,
            client_name=raw.client_name,
            client_country=raw.client_country,
            client_rating=raw.client_rating,
            client_reviews_count=raw.client_reviews_count,
            client_total_spent=raw.client_total_spent,
            client_jobs_posted=raw.client_jobs_posted,
            client_hire_rate=raw.client_hire_rate,
            applicant_count=raw.applicant_count or 0,
            interview_count=raw.interview_count or 0,
            posted_at=raw.posted_at,
            expires_at=raw.expires_at,
            raw_data=raw.raw_data,
            status=JobStatus.DISCOVERED,
        )

    async def _save_jobs(self, jobs: list[DiscoveredJob]) -> None:
        """Save jobs to database"""
        async with db_manager.session() as session:
            for job in jobs:
                session.add(job)
            await session.commit()

            logger.info("Jobs saved to database", count=len(jobs))

    async def get_job_queue(
        self,
        limit: int = 50,
        min_score: Optional[float] = None,
        capabilities: Optional[list[AgentCapability]] = None,
    ) -> list[DiscoveredJob]:
        """
        Get prioritized queue of jobs ready for bidding.

        Args:
            limit: Maximum number of jobs to return
            min_score: Minimum score threshold
            capabilities: Filter by matching capabilities

        Returns:
            List of jobs sorted by score
        """
        async with db_manager.session() as session:
            query = (
                select(DiscoveredJob)
                .where(
                    and_(
                        DiscoveredJob.status.in_([
                            JobStatus.DISCOVERED,
                            JobStatus.SCORED,
                            JobStatus.QUEUED,
                        ]),
                        DiscoveredJob.is_deleted == False,
                    )
                )
                .order_by(DiscoveredJob.score.desc())
                .limit(limit)
            )

            # Apply score filter
            if min_score:
                query = query.where(DiscoveredJob.score >= min_score)

            # Filter by capabilities
            if capabilities:
                cap_values = [c.value for c in capabilities]
                # Job must have at least one matching capability
                query = query.where(
                    DiscoveredJob.matched_capabilities.overlap(cap_values)
                )

            result = await session.execute(query)
            jobs = list(result.scalars().all())

            # Filter out expired jobs
            now = datetime.utcnow()
            jobs = [j for j in jobs if not j.expires_at or j.expires_at > now]

            return jobs

    async def refresh_job(self, job_id: UUID) -> Optional[DiscoveredJob]:
        """
        Refresh job data from platform.

        Useful to update applicant counts before bidding.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == job_id)
            )
            job = result.scalar_one_or_none()

            if not job:
                return None

            # Find platform client
            platform_client = next(
                (p for p in self.platforms if p.platform_name == job.platform),
                None
            )

            if not platform_client:
                logger.warning(
                    "No client for platform",
                    platform=job.platform,
                )
                return job

            # Refresh job data
            try:
                updated_raw = await platform_client.get_job_details(job.platform_job_id)
                if updated_raw:
                    # Update relevant fields
                    job.applicant_count = updated_raw.applicant_count or job.applicant_count
                    job.interview_count = updated_raw.interview_count or job.interview_count

                    # Re-score
                    new_score = await self.scorer.score_job(job)
                    job.score = new_score.total_score
                    job.score_breakdown = new_score.to_dict()

                    session.add(job)
                    await session.commit()
            except Exception as e:
                logger.warning(
                    "Failed to refresh job",
                    job_id=str(job_id),
                    error=str(e),
                )

            return job

    async def cleanup_expired_jobs(self) -> int:
        """Mark expired jobs and return count"""
        async with db_manager.session() as session:
            now = datetime.utcnow()

            result = await session.execute(
                select(DiscoveredJob).where(
                    and_(
                        DiscoveredJob.status.in_([
                            JobStatus.DISCOVERED,
                            JobStatus.SCORED,
                            JobStatus.QUEUED,
                        ]),
                        DiscoveredJob.expires_at < now,
                    )
                )
            )

            expired_jobs = list(result.scalars().all())

            for job in expired_jobs:
                job.status = JobStatus.EXPIRED

            await session.commit()

            if expired_jobs:
                logger.info("Expired jobs cleaned up", count=len(expired_jobs))

            return len(expired_jobs)

    async def get_stats(self) -> dict:
        """Get scanner statistics"""
        async with db_manager.session() as session:
            stats = {"platforms": {}, "totals": {}}

            for platform in self.platforms:
                # Count by status for each platform
                for status in [JobStatus.DISCOVERED, JobStatus.SCORED, JobStatus.APPLIED, JobStatus.WON]:
                    result = await session.execute(
                        select(DiscoveredJob).where(
                            and_(
                                DiscoveredJob.platform == platform.platform_name,
                                DiscoveredJob.status == status,
                            )
                        )
                    )
                    count = len(result.scalars().all())

                    if platform.platform_name not in stats["platforms"]:
                        stats["platforms"][platform.platform_name] = {}
                    stats["platforms"][platform.platform_name][status.value] = count

            # Total counts
            for status in JobStatus:
                result = await session.execute(
                    select(DiscoveredJob).where(DiscoveredJob.status == status)
                )
                stats["totals"][status.value] = len(result.scalars().all())

            return stats
