"""
Workforce Scheduler - Main orchestration layer
Coordinates job discovery, bidding, execution, and communication
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from config import settings
from src.core.events import Event, EventTypes, event_bus
from src.agents.manager import AgentManager
from src.discovery.scanner import JobScanner
from src.bidding.proposal_generator import ProposalGenerator
from src.bidding.submitter import ProposalSubmitter
from src.execution.engine import TaskExecutionEngine

logger = structlog.get_logger(__name__)


class WorkforceScheduler:
    """
    Main orchestration layer for the AI workforce.

    Features:
    - Scheduled job discovery
    - Automatic proposal generation and submission
    - Task execution coordination
    - Message handling
    - Financial reconciliation
    - Health monitoring
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

        # Initialize components
        self.agent_manager = AgentManager()
        self.job_scanner = JobScanner()
        self.proposal_generator = ProposalGenerator()
        self.proposal_submitter = ProposalSubmitter()
        self.execution_engine = TaskExecutionEngine()

        # Queues
        self._job_queue: asyncio.Queue = asyncio.Queue()
        self._proposal_queue: asyncio.Queue = asyncio.Queue()

    def setup_schedules(self) -> None:
        """Configure all scheduled tasks"""
        # Job discovery - every 5 minutes
        self.scheduler.add_job(
            self.discover_jobs,
            IntervalTrigger(minutes=5),
            id="discover_jobs",
            name="Job Discovery",
            max_instances=1,
        )

        # Process job queue - every minute
        self.scheduler.add_job(
            self.process_job_queue,
            IntervalTrigger(minutes=1),
            id="process_job_queue",
            name="Process Job Queue",
            max_instances=1,
        )

        # Check messages - every 2 minutes
        self.scheduler.add_job(
            self.check_messages,
            IntervalTrigger(minutes=2),
            id="check_messages",
            name="Check Messages",
            max_instances=1,
        )

        # Agent health check - hourly
        self.scheduler.add_job(
            self.check_agent_health,
            IntervalTrigger(hours=1),
            id="agent_health",
            name="Agent Health Check",
            max_instances=1,
        )

        # Cleanup expired jobs - every 30 minutes
        self.scheduler.add_job(
            self.cleanup_expired,
            IntervalTrigger(minutes=30),
            id="cleanup_expired",
            name="Cleanup Expired Jobs",
            max_instances=1,
        )

        # Financial reconciliation - daily at midnight
        self.scheduler.add_job(
            self.reconcile_finances,
            CronTrigger(hour=0, minute=0),
            id="reconcile_finances",
            name="Financial Reconciliation",
            max_instances=1,
        )

        logger.info("Schedules configured")

    async def start(self) -> None:
        """Start the scheduler"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        self.setup_schedules()
        self.scheduler.start()
        self.is_running = True

        # Emit startup event
        await event_bus.emit(Event(
            event_type=EventTypes.SYSTEM_STARTUP,
            data={"component": "scheduler"},
            source="scheduler",
        ))

        logger.info("Workforce scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler"""
        if not self.is_running:
            return

        self.scheduler.shutdown(wait=True)
        self.is_running = False

        # Emit shutdown event
        await event_bus.emit(Event(
            event_type=EventTypes.SYSTEM_SHUTDOWN,
            data={"component": "scheduler"},
            source="scheduler",
        ))

        logger.info("Workforce scheduler stopped")

    async def discover_jobs(self) -> None:
        """Scan platforms for new jobs"""
        logger.info("Starting job discovery")

        try:
            # Get available capabilities from active agents
            agents = await self.agent_manager.get_all_agents(
                status=AgentStatus.ACTIVE if hasattr(AgentStatus, 'ACTIVE') else None
            )

            all_capabilities = set()
            for agent in agents:
                all_capabilities.update(agent.capabilities)

            # Scan for jobs matching our capabilities
            from src.agents.models import AgentCapability
            capabilities = [AgentCapability(c) for c in all_capabilities if c in [e.value for e in AgentCapability]]

            new_jobs = await self.job_scanner.scan_all_platforms(
                available_capabilities=capabilities if capabilities else None
            )

            # Add high-scoring jobs to queue
            for job in new_jobs:
                if job.score and job.score >= settings.job_scoring.min_score_threshold:
                    await self._job_queue.put(job)

            logger.info(
                "Job discovery complete",
                new_jobs=len(new_jobs),
                queued=self._job_queue.qsize(),
            )

        except Exception as e:
            logger.error("Job discovery failed", error=str(e), exc_info=True)

    async def process_job_queue(self) -> None:
        """Process queued jobs - generate and submit proposals"""
        logger.debug("Processing job queue", queue_size=self._job_queue.qsize())

        if self._job_queue.empty():
            return

        processed = 0
        max_per_run = 5  # Process up to 5 jobs per run

        while not self._job_queue.empty() and processed < max_per_run:
            try:
                job = await asyncio.wait_for(
                    self._job_queue.get(),
                    timeout=1.0
                )

                # Find suitable agent
                from src.agents.models import AgentCapability
                required_caps = [
                    AgentCapability(c)
                    for c in job.matched_capabilities
                    if c in [e.value for e in AgentCapability]
                ]

                agent = await self.agent_manager.get_available_agent(
                    required_capabilities=required_caps,
                    platform=job.platform,
                )

                if not agent:
                    logger.warning(
                        "No available agent for job",
                        job_id=str(job.id),
                        required_capabilities=job.matched_capabilities,
                    )
                    continue

                # Generate proposal
                proposal = await self.proposal_generator.generate_proposal(
                    job=job,
                    agent=agent,
                )

                # Submit proposal
                result = await self.proposal_submitter.submit_proposal(
                    generated_proposal=proposal,
                    job=job,
                    agent=agent,
                )

                if result.get("success"):
                    processed += 1
                    logger.info(
                        "Proposal submitted",
                        job_id=str(job.id),
                        agent_id=str(agent.id),
                    )

            except asyncio.TimeoutError:
                break
            except Exception as e:
                logger.error("Error processing job", error=str(e))

        logger.debug("Job queue processing complete", processed=processed)

    async def check_messages(self) -> None:
        """Check for new messages across platforms"""
        logger.debug("Checking messages")

        try:
            # Get all active agents
            from src.agents.models import AgentStatus
            agents = await self.agent_manager.get_all_agents(
                status=AgentStatus.ACTIVE
            )

            for agent in agents:
                for profile in agent.platform_profiles:
                    if profile.status != "active":
                        continue

                    platform_client = self.proposal_submitter.platforms.get(profile.platform)
                    if not platform_client:
                        continue

                    # Check messages
                    # This would trigger message handler for new messages
                    # Implementation depends on platform integration

        except Exception as e:
            logger.error("Message check failed", error=str(e))

    async def check_agent_health(self) -> None:
        """Check health of all agents"""
        logger.info("Checking agent health")

        try:
            from src.agents.models import AgentStatus
            agents = await self.agent_manager.get_all_agents()

            for agent in agents:
                # Check platform profiles for warnings/restrictions
                for profile in agent.platform_profiles:
                    if profile.is_at_risk():
                        logger.warning(
                            "Agent profile at risk",
                            agent_id=str(agent.id),
                            platform=profile.platform,
                            warnings=profile.warning_count,
                        )

                        # Consider rotating agent if too risky
                        if profile.warning_count >= 3:
                            await self.agent_manager.update_agent_status(
                                agent.id,
                                AgentStatus.PAUSED,
                                reason="Too many platform warnings",
                            )

        except Exception as e:
            logger.error("Agent health check failed", error=str(e))

    async def cleanup_expired(self) -> None:
        """Cleanup expired jobs and stale data"""
        logger.debug("Running cleanup")

        try:
            expired_count = await self.job_scanner.cleanup_expired_jobs()
            logger.info("Cleanup complete", expired_jobs=expired_count)

        except Exception as e:
            logger.error("Cleanup failed", error=str(e))

    async def reconcile_finances(self) -> None:
        """Daily financial reconciliation"""
        logger.info("Running financial reconciliation")

        try:
            # This would:
            # 1. Sync platform balances
            # 2. Calculate daily earnings/costs
            # 3. Generate reports
            # 4. Process any pending withdrawals

            await event_bus.emit(Event(
                event_type="finance.reconciliation_complete",
                data={"date": datetime.utcnow().isoformat()},
                source="scheduler",
            ))

        except Exception as e:
            logger.error("Financial reconciliation failed", error=str(e))

    async def get_status(self) -> dict:
        """Get scheduler status and statistics"""
        return {
            "is_running": self.is_running,
            "job_queue_size": self._job_queue.qsize(),
            "proposal_queue_size": self._proposal_queue.qsize(),
            "scheduled_jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                }
                for job in self.scheduler.get_jobs()
            ],
        }

    async def trigger_job_manually(self, job_id: str) -> bool:
        """Manually trigger a scheduled job"""
        job = self.scheduler.get_job(job_id)
        if not job:
            return False

        # Run immediately
        job.modify(next_run_time=datetime.now())
        return True


# Need to import this for the scheduler
from src.agents.models import AgentStatus

# Singleton instance
workforce_scheduler = WorkforceScheduler()
