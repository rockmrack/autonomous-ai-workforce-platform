"""
Quality assurance data models
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models import BaseModel


class QualityCheckType(str, Enum):
    """Types of quality checks"""
    GRAMMAR = "grammar"
    SPELLING = "spelling"
    PLAGIARISM = "plagiarism"
    AI_DETECTION = "ai_detection"
    READABILITY = "readability"
    TONE = "tone"
    SEO = "seo"
    FACTUAL = "factual"
    CODE_SYNTAX = "code_syntax"
    CODE_STYLE = "code_style"
    CODE_SECURITY = "code_security"
    CODE_PERFORMANCE = "code_performance"
    CODE_TESTS = "code_tests"


class QualityStatus(str, Enum):
    """Quality check status"""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class QualityReport(BaseModel):
    """
    Quality assessment report for a deliverable.
    Contains all checks and overall assessment.
    """

    __tablename__ = "quality_reports"

    # Relationships
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("active_jobs.id"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
        index=True,
    )

    # Content reference
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)  # writing, code, data
    content_length: Mapped[int] = mapped_column(Integer, default=0)

    # Overall scores
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    status: Mapped[QualityStatus] = mapped_column(
        String(20),
        default=QualityStatus.PENDING,
        nullable=False,
    )

    # Individual scores
    grammar_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spelling_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    readability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    originality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_human_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # % human-like
    tone_match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    seo_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Code-specific scores
    code_syntax_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    code_style_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    code_security_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    code_test_coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Detailed findings
    issues_found: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    suggestions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Check metadata
    checks_run: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    checks_failed: Mapped[int] = mapped_column(Integer, default=0)
    checks_warnings: Mapped[int] = mapped_column(Integer, default=0)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Approval
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class QualityCheck(BaseModel):
    """
    Individual quality check result.
    """

    __tablename__ = "quality_checks"

    # Relationships
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quality_reports.id"),
        nullable=False,
        index=True,
    )

    # Check info
    check_type: Mapped[QualityCheckType] = mapped_column(
        String(50),
        nullable=False,
    )
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[QualityStatus] = mapped_column(
        String(20),
        nullable=False,
    )

    # Results
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, default=70.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Details
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issues: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Timing
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class QualityThreshold(BaseModel):
    """
    Quality thresholds for different content types and clients.
    """

    __tablename__ = "quality_thresholds"

    # Scope
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    platform: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Thresholds (0-100)
    min_overall_score: Mapped[float] = mapped_column(Float, default=80.0)
    min_grammar_score: Mapped[float] = mapped_column(Float, default=90.0)
    min_spelling_score: Mapped[float] = mapped_column(Float, default=95.0)
    min_readability_score: Mapped[float] = mapped_column(Float, default=70.0)
    min_originality_score: Mapped[float] = mapped_column(Float, default=85.0)
    min_ai_human_score: Mapped[float] = mapped_column(Float, default=60.0)

    # Code thresholds
    min_code_syntax_score: Mapped[float] = mapped_column(Float, default=100.0)
    min_code_style_score: Mapped[float] = mapped_column(Float, default=80.0)
    min_code_security_score: Mapped[float] = mapped_column(Float, default=90.0)
    min_test_coverage: Mapped[float] = mapped_column(Float, default=70.0)

    # Flags
    require_plagiarism_check: Mapped[bool] = mapped_column(Boolean, default=True)
    require_ai_detection: Mapped[bool] = mapped_column(Boolean, default=True)
    require_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
