"""
Execution Tasks - Job execution and deliverable submission
"""

import asyncio
from typing import Optional

from celery import shared_task, chain, group
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
    name="src.tasks.execution.execute_job",
    max_retries=2,
    default_retry_delay=300,
    time_limit=7200,  # 2 hours max
    soft_time_limit=6900,  # 1 hour 55 min soft limit
)
def execute_job(self, job_id: str, agent_id: str):
    """
    Execute a job with the specified agent.

    This is a long-running task that:
    1. Analyzes job requirements
    2. Plans execution steps
    3. Executes each step
    4. Produces deliverables
    5. Runs quality checks
    """
    async def _execute():
        from uuid import UUID
        from src.execution.engine import execution_engine
        from src.core.events import Event, event_bus

        try:
            # Emit start event
            await event_bus.emit(Event(
                type="job.execution.started",
                data={"job_id": job_id, "agent_id": agent_id},
            ))

            # Execute the job
            result = await execution_engine.execute_job(
                job_id=UUID(job_id),
                agent_id=UUID(agent_id),
            )

            # Emit completion event
            await event_bus.emit(Event(
                type="job.execution.completed",
                data={
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "status": result.status.value,
                },
            ))

            return {
                "job_id": job_id,
                "agent_id": agent_id,
                "status": result.status.value,
                "deliverables_count": len(result.deliverables),
            }

        except Exception as e:
            logger.error(f"Job execution failed: {e}")

            await event_bus.emit(Event(
                type="job.execution.failed",
                data={
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "error": str(e),
                },
            ))

            raise

    try:
        return run_async(_execute())
    except Exception as exc:
        logger.error(f"execute_job failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.execution.execute_step",
    max_retries=3,
    default_retry_delay=60,
)
def execute_step(self, job_id: str, step_index: int, step_data: dict):
    """
    Execute a single step of a job.

    Used for breaking down large jobs into smaller tasks.
    """
    async def _execute():
        from uuid import UUID
        from src.execution.engine import execution_engine

        result = await execution_engine.execute_step(
            job_id=UUID(job_id),
            step_index=step_index,
            step_data=step_data,
        )

        return {
            "job_id": job_id,
            "step_index": step_index,
            "status": result.get("status", "completed"),
            "output": result.get("output"),
        }

    try:
        return run_async(_execute())
    except Exception as exc:
        logger.error(f"execute_step failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.execution.submit_deliverable",
    max_retries=3,
    default_retry_delay=120,
)
def submit_deliverable(self, job_id: str, deliverable_data: dict):
    """
    Submit a completed deliverable.

    Args:
        job_id: The job ID
        deliverable_data: Deliverable content and metadata
    """
    async def _submit():
        from uuid import UUID
        from src.execution.engine import execution_engine
        from src.quality.checker import quality_checker

        # Run quality checks first
        quality_result = await quality_checker.check_deliverable(
            deliverable_data=deliverable_data,
            job_id=UUID(job_id),
        )

        if not quality_result.passed:
            return {
                "job_id": job_id,
                "status": "quality_failed",
                "issues": quality_result.issues,
            }

        # Submit to platform
        result = await execution_engine.submit_deliverable(
            job_id=UUID(job_id),
            deliverable=deliverable_data,
        )

        return {
            "job_id": job_id,
            "status": "submitted",
            "submission_id": result.get("submission_id"),
        }

    try:
        return run_async(_submit())
    except Exception as exc:
        logger.error(f"submit_deliverable failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    name="src.tasks.execution.run_quality_check",
)
def run_quality_check(job_id: str, content: str, content_type: str):
    """
    Run quality checks on content.

    Args:
        job_id: Associated job ID
        content: Content to check
        content_type: Type of content (code, text, etc.)
    """
    async def _check():
        from uuid import UUID
        from src.quality.checker import quality_checker

        result = await quality_checker.check_content(
            content=content,
            content_type=content_type,
            job_id=UUID(job_id),
        )

        return {
            "job_id": job_id,
            "passed": result.passed,
            "score": result.overall_score,
            "checks": result.check_results,
        }

    return run_async(_check())


@shared_task(
    name="src.tasks.execution.request_revision",
)
def request_revision(job_id: str, revision_notes: str):
    """
    Handle a revision request from client.

    Args:
        job_id: The job ID
        revision_notes: Client's revision feedback
    """
    async def _handle_revision():
        from uuid import UUID
        from src.execution.engine import execution_engine

        result = await execution_engine.handle_revision(
            job_id=UUID(job_id),
            revision_notes=revision_notes,
        )

        # Queue re-execution
        execute_job.delay(job_id, str(result["agent_id"]))

        return {
            "job_id": job_id,
            "status": "revision_queued",
            "revision_number": result.get("revision_number", 1),
        }

    return run_async(_handle_revision())


@shared_task(
    name="src.tasks.execution.complete_job",
)
def complete_job(job_id: str, agent_id: str, payment_amount: float):
    """
    Mark a job as complete and process payment.

    Args:
        job_id: The job ID
        agent_id: The agent who completed it
        payment_amount: Payment received
    """
    async def _complete():
        from uuid import UUID
        from decimal import Decimal
        from src.core.database import db_manager
        from src.discovery.models import ActiveJob, JobStatus
        from src.finance.wallet import wallet_manager
        from sqlalchemy import select

        async with db_manager.session() as session:
            # Update job status
            result = await session.execute(
                select(ActiveJob).where(ActiveJob.id == UUID(job_id))
            )
            job = result.scalar_one_or_none()

            if job:
                job.status = JobStatus.COMPLETED
                job.payment_amount = Decimal(str(payment_amount))

                # Add earnings to wallet
                await wallet_manager.add_earnings(
                    agent_id=UUID(agent_id),
                    amount=Decimal(str(payment_amount)),
                    job_id=UUID(job_id),
                    platform=job.platform,
                    pending=True,  # Pending clearance
                )

                await session.commit()

        return {
            "job_id": job_id,
            "agent_id": agent_id,
            "payment": payment_amount,
            "status": "completed",
        }

    return run_async(_complete())
