"""
Task Execution Engine - Main orchestrator for task execution
Routes jobs to appropriate executors and manages execution lifecycle
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
import structlog

from src.core.database import db_manager
from src.core.events import Event, EventTypes, event_bus
from src.agents.models import Agent
from src.discovery.models import ActiveJob, DiscoveredJob, JobStatus
from .executors.base import (
    BaseExecutor,
    ExecutionResult,
    ExecutionStatus,
    TaskRequirements,
)
from .executors.research import ResearchExecutor
from .executors.writing import WritingExecutor
from .executors.data import DataEntryExecutor
from .executors.coding import CodingExecutor

logger = structlog.get_logger(__name__)


class TaskExecutionEngine:
    """
    Main engine for executing tasks.

    Features:
    - Automatic executor selection based on job type
    - Progress tracking and reporting
    - Error handling and retry logic
    - Quality assurance integration
    - Cost tracking
    """

    def __init__(self):
        # Initialize executors
        self.executors: list[BaseExecutor] = [
            WritingExecutor(),
            ResearchExecutor(),
            DataEntryExecutor(),
            CodingExecutor(),
        ]

    def register_executor(self, executor: BaseExecutor) -> None:
        """Register a custom executor"""
        self.executors.append(executor)
        logger.info(
            "Executor registered",
            executor_type=executor.executor_type,
        )

    async def execute_job(
        self,
        job_id: UUID,
        agent_id: UUID,
    ) -> ExecutionResult:
        """
        Execute a job with the appropriate executor.

        Args:
            job_id: ID of the active job to execute
            agent_id: ID of the agent executing the job

        Returns:
            ExecutionResult with deliverable or error
        """
        async with db_manager.session() as session:
            # Get job
            result = await session.execute(
                select(ActiveJob).where(ActiveJob.id == job_id)
            )
            job = result.scalar_one_or_none()

            if not job:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=f"Job not found: {job_id}",
                )

            # Get agent
            result = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one_or_none()

            if not agent:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=f"Agent not found: {agent_id}",
                )

            # Get discovered job for details
            result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == job.discovered_job_id)
            )
            discovered_job = result.scalar_one()
            job.discovered_job = discovered_job

            logger.info(
                "Starting job execution",
                job_id=str(job_id),
                agent_id=str(agent_id),
                job_title=discovered_job.title,
            )

            # Emit start event
            await event_bus.emit(Event(
                event_type=EventTypes.JOB_STARTED,
                data={
                    "job_id": str(job_id),
                    "agent_id": str(agent_id),
                    "title": discovered_job.title,
                },
                source="execution_engine",
            ))

            # Find appropriate executor
            executor = await self._select_executor(job)

            if not executor:
                error_msg = "No suitable executor found for job"
                logger.error(error_msg, job_id=str(job_id))

                await event_bus.emit(Event(
                    event_type=EventTypes.JOB_FAILED,
                    data={
                        "job_id": str(job_id),
                        "error": error_msg,
                    },
                    source="execution_engine",
                ))

                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=error_msg,
                )

            logger.info(
                "Executor selected",
                job_id=str(job_id),
                executor_type=executor.executor_type,
            )

            # Parse requirements
            requirements = await executor.parse_requirements(job)

            # Execute
            try:
                execution_result = await executor.execute(job, agent, requirements)

                # Update job status
                if execution_result.success:
                    job.status = JobStatus.DELIVERED
                    job.delivered_at = datetime.utcnow()
                    job.progress_percentage = Decimal("100")

                    await event_bus.emit(Event(
                        event_type=EventTypes.JOB_COMPLETED,
                        data={
                            "job_id": str(job_id),
                            "agent_id": str(agent_id),
                            "quality_score": execution_result.quality_score,
                            "time_spent": execution_result.time_spent_seconds,
                        },
                        source="execution_engine",
                    ))
                else:
                    job.status = JobStatus.IN_PROGRESS  # Keep in progress for retry

                    await event_bus.emit(Event(
                        event_type=EventTypes.JOB_FAILED,
                        data={
                            "job_id": str(job_id),
                            "error": execution_result.error_message,
                        },
                        source="execution_engine",
                    ))

                # Save execution log
                job.execution_log.extend(execution_result.execution_log)

                # Add deliverable info
                if execution_result.deliverable:
                    job.add_deliverable({
                        "type": execution_result.deliverable_type,
                        "format": execution_result.deliverable_format,
                        "quality_score": execution_result.quality_score,
                    })

                session.add(job)
                await session.commit()

                logger.info(
                    "Job execution complete",
                    job_id=str(job_id),
                    success=execution_result.success,
                    time_spent=execution_result.time_spent_seconds,
                    quality_score=execution_result.quality_score,
                )

                return execution_result

            except Exception as e:
                logger.error(
                    "Job execution error",
                    job_id=str(job_id),
                    error=str(e),
                    exc_info=True,
                )

                await event_bus.emit(Event(
                    event_type=EventTypes.JOB_FAILED,
                    data={
                        "job_id": str(job_id),
                        "error": str(e),
                    },
                    source="execution_engine",
                ))

                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=str(e),
                )

    async def _select_executor(self, job: ActiveJob) -> Optional[BaseExecutor]:
        """Select the most appropriate executor for a job"""
        for executor in self.executors:
            if await executor.can_handle(job):
                return executor
        return None

    async def estimate_job_time(self, job_id: UUID) -> Optional[int]:
        """
        Estimate time to complete a job.

        Returns estimated minutes or None if cannot estimate.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ActiveJob).where(ActiveJob.id == job_id)
            )
            job = result.scalar_one_or_none()

            if not job:
                return None

            # Get discovered job
            result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == job.discovered_job_id)
            )
            job.discovered_job = result.scalar_one()

            executor = await self._select_executor(job)
            if not executor:
                return None

            return await executor.estimate_time(job)

    async def get_supported_task_types(self) -> list[dict]:
        """Get list of supported task types"""
        return [
            {
                "type": executor.executor_type,
                "capabilities": [c.value for c in executor.CAPABILITIES],
            }
            for executor in self.executors
        ]

    async def handle_revision(
        self,
        job_id: UUID,
        feedback: str,
    ) -> ExecutionResult:
        """
        Handle a revision request for a completed job.

        Args:
            job_id: ID of the job needing revision
            feedback: Client feedback on what needs to change

        Returns:
            ExecutionResult with revised deliverable
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ActiveJob).where(ActiveJob.id == job_id)
            )
            job = result.scalar_one_or_none()

            if not job:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=f"Job not found: {job_id}",
                )

            # Check revision limit
            if job.revision_count >= job.max_revisions:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    success=False,
                    error_message=f"Maximum revisions ({job.max_revisions}) exceeded",
                )

            # Record revision request
            job.request_revision(feedback)

            await event_bus.emit(Event(
                event_type=EventTypes.REVISION_REQUESTED,
                data={
                    "job_id": str(job_id),
                    "revision_number": job.revision_count,
                    "feedback": feedback[:200],
                },
                source="execution_engine",
            ))

            session.add(job)
            await session.commit()

            # Re-execute with revision context
            # This would ideally incorporate the feedback
            logger.info(
                "Processing revision",
                job_id=str(job_id),
                revision_number=job.revision_count,
            )

            # For now, return a pending status
            # Full implementation would re-run executor with feedback
            return ExecutionResult(
                status=ExecutionStatus.RUNNING,
                success=True,
                execution_log=[{
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": "Revision in progress",
                    "feedback": feedback,
                }],
            )


# Singleton instance
execution_engine = TaskExecutionEngine()
