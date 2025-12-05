"""
Job Discovery Models
SQLAlchemy models for job tracking and management
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models import BaseModel


class JobStatus(str, enum.Enum):
    """Job lifecycle status"""

    DISCOVERED = "discovered"
    SCORED = "scored"
    QUEUED = "queued"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    WON = "won"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class ProposalStatus(str, enum.Enum):
    """Proposal status"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    SHORTLISTED = "shortlisted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class DiscoveredJob(BaseModel):
    """
    Discovered job from a freelance platform.

    Tracks the entire lifecycle from discovery through completion.
    """

    __tablename__ = "discovered_jobs"

    # Source info
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    platform_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Job details
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Budget
    budget_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    budget_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    budget_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Requirements
    skills_required: Mapped[list] = mapped_column(JSONB, default=list)
    experience_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    estimated_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    estimated_duration: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Client info
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    client_reviews_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_total_spent: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    client_jobs_posted: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_hire_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)

    # Competition
    applicant_count: Mapped[int] = mapped_column(Integer, default=0)
    interview_count: Mapped[int] = mapped_column(Integer, default=0)

    # Scoring
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ml_success_probability: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    estimated_profit_margin: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )

    # Matching
    matched_capabilities: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(1536), nullable=True)

    # Status
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        default=JobStatus.DISCOVERED,
    )
    assigned_agent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=True,
    )

    # Timing
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    won_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Raw data storage
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    active_job: Mapped[Optional["ActiveJob"]] = relationship(
        "ActiveJob",
        back_populates="discovered_job",
        uselist=False,
    )

    @property
    def budget_display(self) -> str:
        """Human-readable budget display"""
        if self.budget_min and self.budget_max:
            return f"${self.budget_min:,.0f} - ${self.budget_max:,.0f}"
        elif self.budget_max:
            return f"Up to ${self.budget_max:,.0f}"
        elif self.budget_min:
            return f"From ${self.budget_min:,.0f}"
        return "Budget not specified"

    @property
    def is_actionable(self) -> bool:
        """Check if job can still be applied to"""
        actionable_statuses = {
            JobStatus.DISCOVERED,
            JobStatus.SCORED,
            JobStatus.QUEUED,
        }
        if self.status not in actionable_statuses:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def mark_applied(self, agent_id: UUID) -> None:
        """Mark job as applied"""
        self.status = JobStatus.APPLIED
        self.assigned_agent_id = agent_id
        self.applied_at = datetime.utcnow()

    def mark_won(self) -> None:
        """Mark job as won"""
        self.status = JobStatus.WON
        self.won_at = datetime.utcnow()

    def mark_completed(self) -> None:
        """Mark job as completed"""
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.utcnow()


class Proposal(BaseModel):
    """
    Proposal submitted for a job.
    """

    __tablename__ = "proposals"

    # Foreign keys
    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("discovered_jobs.id"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
    )

    # Proposal content
    cover_letter: Mapped[str] = mapped_column(Text, nullable=False)
    bid_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    bid_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    estimated_duration: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    milestones: Mapped[list] = mapped_column(JSONB, default=list)

    # Questions/answers
    questions_answered: Mapped[list] = mapped_column(JSONB, default=list)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)

    # A/B Testing
    variant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    template_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, name="proposal_status"),
        default=ProposalStatus.DRAFT,
    )
    client_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Performance tracking
    response_time_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Generation metadata
    generation_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    job: Mapped["DiscoveredJob"] = relationship("DiscoveredJob", back_populates="proposals")

    def submit(self) -> None:
        """Mark proposal as submitted"""
        self.status = ProposalStatus.SUBMITTED
        self.submitted_at = datetime.utcnow()


class ActiveJob(BaseModel):
    """
    Job that we've won and are actively working on.
    """

    __tablename__ = "active_jobs"

    # Foreign keys
    discovered_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("discovered_jobs.id"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
    )
    proposal_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("proposals.id"),
        nullable=True,
    )

    # Contract details
    contract_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contract_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    agreed_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    agreed_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)

    # Progress
    progress_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0")
    )
    current_milestone: Mapped[int] = mapped_column(Integer, default=0)
    milestones: Mapped[list] = mapped_column(JSONB, default=list)

    # Deliverables
    deliverables: Mapped[list] = mapped_column(JSONB, default=list)

    # Time tracking
    hours_logged: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))

    # Status
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        default=JobStatus.IN_PROGRESS,
    )
    client_satisfied: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Revisions
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    max_revisions: Mapped[int] = mapped_column(Integer, default=3)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    deadline_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Execution data
    execution_log: Mapped[list] = mapped_column(JSONB, default=list)

    # Relationships
    discovered_job: Mapped["DiscoveredJob"] = relationship(
        "DiscoveredJob", back_populates="active_job"
    )

    def update_progress(self, percentage: Decimal, log_entry: Optional[dict] = None) -> None:
        """Update job progress"""
        self.progress_percentage = percentage
        if log_entry:
            self.execution_log.append({
                **log_entry,
                "timestamp": datetime.utcnow().isoformat(),
                "progress": float(percentage),
            })

    def add_deliverable(self, deliverable: dict) -> None:
        """Add a deliverable"""
        self.deliverables.append({
            **deliverable,
            "added_at": datetime.utcnow().isoformat(),
        })

    def mark_delivered(self) -> None:
        """Mark job as delivered"""
        self.status = JobStatus.DELIVERED
        self.delivered_at = datetime.utcnow()
        self.progress_percentage = Decimal("100")

    def request_revision(self, feedback: str) -> None:
        """Handle revision request"""
        self.revision_count += 1
        self.status = JobStatus.IN_PROGRESS
        self.execution_log.append({
            "type": "revision_requested",
            "feedback": feedback,
            "revision_number": self.revision_count,
            "timestamp": datetime.utcnow().isoformat(),
        })

    @property
    def is_overdue(self) -> bool:
        """Check if job is past deadline"""
        if not self.deadline_at:
            return False
        return datetime.utcnow() > self.deadline_at and self.status == JobStatus.IN_PROGRESS
