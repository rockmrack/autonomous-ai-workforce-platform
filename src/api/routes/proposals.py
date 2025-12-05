"""Proposals API Routes"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.bidding.submitter import ProposalSubmitter

router = APIRouter()


class ProposalResponse(BaseModel):
    """Proposal response model"""
    proposal_id: str
    job_id: str
    agent_id: str
    status: str
    bid_amount: float
    submitted_at: Optional[str]


@router.get("/", response_model=list[ProposalResponse])
async def list_proposals(
    agent_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List proposals"""
    submitter = ProposalSubmitter()
    proposals = await submitter.get_active_proposals(
        agent_id=agent_id,
        limit=limit,
    )

    return [
        ProposalResponse(
            proposal_id=p["proposal_id"],
            job_id=p["job_id"],
            agent_id=p["agent_id"],
            status=p["status"],
            bid_amount=p["bid_amount"],
            submitted_at=p.get("submitted_at"),
        )
        for p in proposals
    ]


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get proposal details"""
    submitter = ProposalSubmitter()
    proposal = await submitter.get_proposal_status(proposal_id)

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return proposal


@router.post("/{proposal_id}/withdraw")
async def withdraw_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a submitted proposal"""
    submitter = ProposalSubmitter()
    result = await submitter.withdraw_proposal(proposal_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/generate")
async def generate_proposal(
    job_id: UUID,
    agent_id: UUID,
    variant: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate a proposal without submitting"""
    from sqlalchemy import select
    from src.discovery.models import DiscoveredJob
    from src.agents.models import Agent
    from src.bidding.proposal_generator import ProposalGenerator

    async with db as session:
        # Get job
        result = await session.execute(
            select(DiscoveredJob).where(DiscoveredJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Get agent
        result = await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

    generator = ProposalGenerator()
    proposal = await generator.generate_proposal(
        job=job,
        agent=agent,
        variant_id=variant,
    )

    return {
        "cover_letter": proposal.cover_letter,
        "bid_amount": float(proposal.bid_amount),
        "bid_type": proposal.bid_type,
        "estimated_duration": proposal.estimated_duration,
        "milestones": proposal.milestones,
        "variant_id": proposal.variant_id,
    }
