"""
Proposal Submitter - Handles submission of proposals to platforms
"""

import asyncio
import random
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
import structlog

from src.core.database import db_manager
from src.core.events import Event, EventTypes, event_bus
from src.agents.models import Agent
from src.discovery.models import DiscoveredJob, Proposal, ProposalStatus
from src.discovery.platforms.base import BasePlatformClient
from .proposal_generator import GeneratedProposal

logger = structlog.get_logger(__name__)


class ProposalSubmitter:
    """
    Handles submission of proposals to various platforms.

    Features:
    - Platform-specific submission handling
    - Human-like submission delays
    - Rate limiting and safety checks
    - Submission tracking and logging
    """

    # Minimum delay between submissions (seconds)
    MIN_SUBMISSION_DELAY = 30
    MAX_SUBMISSION_DELAY = 180

    def __init__(self, platforms: Optional[dict[str, BasePlatformClient]] = None):
        self.platforms = platforms or {}

    def register_platform(self, name: str, client: BasePlatformClient) -> None:
        """Register a platform client"""
        self.platforms[name] = client

    async def submit_proposal(
        self,
        generated_proposal: GeneratedProposal,
        job: DiscoveredJob,
        agent: Agent,
        skip_delay: bool = False,
    ) -> dict:
        """
        Submit a generated proposal to the platform.

        Args:
            generated_proposal: The proposal to submit
            job: The job being applied to
            agent: The agent submitting
            skip_delay: Skip human-like delay (for testing)

        Returns:
            Dict with success status and details
        """
        logger.info(
            "Submitting proposal",
            job_id=str(job.id),
            agent_id=str(agent.id),
            platform=job.platform,
            bid_amount=float(generated_proposal.bid_amount),
        )

        # Add human-like delay
        if not skip_delay:
            delay = random.uniform(self.MIN_SUBMISSION_DELAY, self.MAX_SUBMISSION_DELAY)
            logger.debug(f"Waiting {delay:.1f}s before submission")
            await asyncio.sleep(delay)

        # Get platform client
        platform_client = self.platforms.get(job.platform)

        if not platform_client:
            logger.warning(
                "No platform client registered",
                platform=job.platform,
            )
            return {
                "success": False,
                "error": f"No client for platform: {job.platform}",
            }

        # Save proposal to database first
        proposal = await self._save_proposal(generated_proposal, job, agent)

        try:
            # Submit to platform
            result = await platform_client.submit_proposal(
                job_id=job.platform_job_id,
                cover_letter=generated_proposal.cover_letter,
                bid_amount=generated_proposal.bid_amount,
                milestones=generated_proposal.milestones or None,
                duration=generated_proposal.estimated_duration,
                attachments=generated_proposal.attachments or None,
            )

            if result.get("success"):
                # Update proposal status
                proposal.status = ProposalStatus.SUBMITTED
                proposal.submitted_at = datetime.utcnow()

                # Update job status
                job.status = "applied"
                job.applied_at = datetime.utcnow()
                job.assigned_agent_id = agent.id

                await self._update_records(proposal, job)

                # Emit event
                await event_bus.emit(Event(
                    event_type=EventTypes.PROPOSAL_SUBMITTED,
                    data={
                        "job_id": str(job.id),
                        "agent_id": str(agent.id),
                        "proposal_id": str(proposal.id),
                        "platform": job.platform,
                        "bid_amount": float(generated_proposal.bid_amount),
                    },
                    source="proposal_submitter",
                ))

                logger.info(
                    "Proposal submitted successfully",
                    job_id=str(job.id),
                    proposal_id=str(proposal.id),
                    platform_response=result.get("data"),
                )

                return {
                    "success": True,
                    "proposal_id": str(proposal.id),
                    "platform_proposal_id": result.get("proposal_id"),
                    "data": result,
                }

            else:
                logger.error(
                    "Proposal submission failed",
                    job_id=str(job.id),
                    error=result.get("error"),
                )

                return {
                    "success": False,
                    "proposal_id": str(proposal.id),
                    "error": result.get("error", "Unknown error"),
                    "data": result,
                }

        except Exception as e:
            logger.error(
                "Proposal submission exception",
                job_id=str(job.id),
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "proposal_id": str(proposal.id),
                "error": str(e),
            }

    async def _save_proposal(
        self,
        generated: GeneratedProposal,
        job: DiscoveredJob,
        agent: Agent,
    ) -> Proposal:
        """Save proposal to database"""
        async with db_manager.session() as session:
            proposal = Proposal(
                job_id=job.id,
                agent_id=agent.id,
                cover_letter=generated.cover_letter,
                bid_amount=generated.bid_amount,
                bid_type=generated.bid_type,
                estimated_duration=generated.estimated_duration,
                milestones=generated.milestones,
                attachments=generated.attachments,
                variant_id=generated.variant_id,
                generation_metadata=generated.generation_metadata,
                status=ProposalStatus.DRAFT,
            )

            session.add(proposal)
            await session.commit()
            await session.refresh(proposal)

            return proposal

    async def _update_records(self, proposal: Proposal, job: DiscoveredJob) -> None:
        """Update proposal and job records"""
        async with db_manager.session() as session:
            session.add(proposal)
            session.add(job)
            await session.commit()

    async def bulk_submit(
        self,
        proposals: list[tuple[GeneratedProposal, DiscoveredJob, Agent]],
        max_concurrent: int = 3,
    ) -> list[dict]:
        """
        Submit multiple proposals with controlled concurrency.

        Args:
            proposals: List of (proposal, job, agent) tuples
            max_concurrent: Maximum concurrent submissions

        Returns:
            List of submission results
        """
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def submit_with_semaphore(proposal, job, agent):
            async with semaphore:
                return await self.submit_proposal(proposal, job, agent)

        tasks = [
            submit_with_semaphore(proposal, job, agent)
            for proposal, job, agent in proposals
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append({
                    "success": False,
                    "error": str(result),
                })
            else:
                processed.append(result)

        return processed

    async def withdraw_proposal(
        self,
        proposal_id: UUID,
    ) -> dict:
        """Withdraw a submitted proposal from the platform"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Proposal).where(Proposal.id == proposal_id)
            )
            proposal = result.scalar_one_or_none()

            if not proposal:
                return {"success": False, "error": "Proposal not found"}

            if proposal.status not in [ProposalStatus.SUBMITTED, ProposalStatus.VIEWED]:
                return {"success": False, "error": f"Cannot withdraw proposal in status: {proposal.status}"}

            # Get the associated job to determine platform
            job_result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == proposal.job_id)
            )
            job = job_result.scalar_one_or_none()

            if not job:
                return {"success": False, "error": "Associated job not found"}

            # Attempt platform withdrawal
            platform_result = await self._withdraw_from_platform(
                platform=job.platform,
                platform_proposal_id=proposal.platform_proposal_id,
                job=job,
            )

            if not platform_result["success"]:
                logger.warning(
                    "Platform withdrawal failed, marking local only",
                    proposal_id=str(proposal_id),
                    error=platform_result.get("error"),
                )

            # Update our records regardless (mark as withdrawn)
            proposal.status = ProposalStatus.WITHDRAWN
            proposal.metadata_json = proposal.metadata_json or {}
            proposal.metadata_json["withdrawal"] = {
                "timestamp": datetime.utcnow().isoformat(),
                "platform_success": platform_result["success"],
                "platform_error": platform_result.get("error"),
            }

            session.add(proposal)
            await session.commit()

            logger.info(
                "Proposal withdrawn",
                proposal_id=str(proposal_id),
                platform_success=platform_result["success"],
            )

            return {
                "success": True,
                "proposal_id": str(proposal_id),
                "platform_withdrawn": platform_result["success"],
            }

    async def _withdraw_from_platform(
        self,
        platform: str,
        platform_proposal_id: Optional[str],
        job: DiscoveredJob,
    ) -> dict:
        """
        Withdraw proposal from the actual freelance platform.
        Returns success status and any error message.
        """
        if not platform_proposal_id:
            return {"success": False, "error": "No platform proposal ID available"}

        try:
            # Get platform client
            from src.discovery.platforms import get_platform_client

            client = get_platform_client(platform)
            if not client:
                return {"success": False, "error": f"No client available for platform: {platform}"}

            # Each platform has different withdrawal mechanisms
            if platform == "upwork":
                # Upwork API call to withdraw proposal
                result = await client.withdraw_proposal(
                    proposal_id=platform_proposal_id,
                    job_id=job.platform_job_id,
                )
                return result

            elif platform == "fiverr":
                # Fiverr doesn't allow proposal withdrawal in the same way
                # Offers can be cancelled
                result = await client.cancel_offer(
                    offer_id=platform_proposal_id,
                )
                return result

            else:
                # Generic attempt for other platforms
                if hasattr(client, "withdraw_proposal"):
                    result = await client.withdraw_proposal(
                        proposal_id=platform_proposal_id,
                    )
                    return result
                return {"success": False, "error": f"Platform {platform} does not support withdrawal"}

        except Exception as e:
            logger.error(
                "Platform withdrawal error",
                platform=platform,
                proposal_id=platform_proposal_id,
                error=str(e),
            )
            return {"success": False, "error": str(e)}

    async def get_proposal_status(
        self,
        proposal_id: UUID,
    ) -> Optional[dict]:
        """Get current status of a proposal"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Proposal).where(Proposal.id == proposal_id)
            )
            proposal = result.scalar_one_or_none()

            if not proposal:
                return None

            return {
                "proposal_id": str(proposal.id),
                "job_id": str(proposal.job_id),
                "status": proposal.status.value,
                "bid_amount": float(proposal.bid_amount),
                "submitted_at": proposal.submitted_at.isoformat() if proposal.submitted_at else None,
                "client_viewed_at": proposal.client_viewed_at.isoformat() if proposal.client_viewed_at else None,
            }

    async def get_active_proposals(
        self,
        agent_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get active (pending) proposals"""
        async with db_manager.session() as session:
            query = select(Proposal).where(
                Proposal.status.in_([
                    ProposalStatus.SUBMITTED,
                    ProposalStatus.VIEWED,
                    ProposalStatus.SHORTLISTED,
                ])
            )

            if agent_id:
                query = query.where(Proposal.agent_id == agent_id)

            query = query.order_by(Proposal.submitted_at.desc()).limit(limit)

            result = await session.execute(query)
            proposals = result.scalars().all()

            return [
                {
                    "proposal_id": str(p.id),
                    "job_id": str(p.job_id),
                    "agent_id": str(p.agent_id),
                    "status": p.status.value,
                    "bid_amount": float(p.bid_amount),
                    "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
                }
                for p in proposals
            ]
