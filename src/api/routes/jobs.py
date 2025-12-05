"""Jobs API Routes"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.discovery.scanner import JobScanner
from src.discovery.models import JobStatus

router = APIRouter()


class JobResponse(BaseModel):
    """Job response model"""
    id: str
    platform: str
    title: str
    category: Optional[str]
    budget_min: Optional[float]
    budget_max: Optional[float]
    budget_type: Optional[str]
    status: str
    score: Optional[float]
    applicant_count: int
    matched_capabilities: list[str]


class JobQueueResponse(BaseModel):
    """Job queue response"""
    jobs: list[JobResponse]
    total_count: int


@router.get("/queue", response_model=JobQueueResponse)
async def get_job_queue(
    min_score: float = Query(default=0.6, ge=0, le=1),
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get prioritized job queue"""
    scanner = JobScanner()

    jobs = await scanner.get_job_queue(
        limit=limit,
        min_score=min_score,
    )

    return JobQueueResponse(
        jobs=[
            JobResponse(
                id=str(job.id),
                platform=job.platform,
                title=job.title,
                category=job.category,
                budget_min=float(job.budget_min) if job.budget_min else None,
                budget_max=float(job.budget_max) if job.budget_max else None,
                budget_type=job.budget_type,
                status=job.status.value,
                score=float(job.score) if job.score else None,
                applicant_count=job.applicant_count,
                matched_capabilities=job.matched_capabilities or [],
            )
            for job in jobs
        ],
        total_count=len(jobs),
    )


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get job details"""
    from sqlalchemy import select
    from src.discovery.models import DiscoveredJob

    async with db as session:
        result = await session.execute(
            select(DiscoveredJob).where(DiscoveredJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "id": str(job.id),
            "platform": job.platform,
            "platform_job_id": job.platform_job_id,
            "title": job.title,
            "description": job.description,
            "category": job.category,
            "budget": {
                "min": float(job.budget_min) if job.budget_min else None,
                "max": float(job.budget_max) if job.budget_max else None,
                "type": job.budget_type,
            },
            "client": {
                "rating": float(job.client_rating) if job.client_rating else None,
                "total_spent": float(job.client_total_spent) if job.client_total_spent else None,
                "jobs_posted": job.client_jobs_posted,
            },
            "status": job.status.value,
            "score": float(job.score) if job.score else None,
            "score_breakdown": job.score_breakdown,
            "matched_capabilities": job.matched_capabilities,
            "applicant_count": job.applicant_count,
            "discovered_at": job.discovered_at.isoformat(),
        }


@router.post("/scan")
async def trigger_scan(
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual job scan"""
    scanner = JobScanner()
    jobs = await scanner.scan_all_platforms()

    return {
        "success": True,
        "jobs_found": len(jobs),
    }


@router.get("/stats")
async def get_job_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get job statistics"""
    scanner = JobScanner()
    return await scanner.get_stats()


@router.post("/{job_id}/refresh")
async def refresh_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Refresh job data from platform"""
    scanner = JobScanner()
    job = await scanner.refresh_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "success": True,
        "job_id": str(job.id),
        "applicant_count": job.applicant_count,
        "score": float(job.score) if job.score else None,
    }
