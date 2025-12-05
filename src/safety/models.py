"""
Safety and anti-detection data models
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models import BaseModel


class RiskLevel(str, Enum):
    """Risk level classification"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ViolationType(str, Enum):
    """Types of safety violations"""
    RATE_LIMIT = "rate_limit"
    BEHAVIOR_ANOMALY = "behavior_anomaly"
    CONTENT_POLICY = "content_policy"
    PLATFORM_TOS = "platform_tos"
    DETECTION_RISK = "detection_risk"
    CREDENTIAL_ISSUE = "credential_issue"
    IP_BLOCKED = "ip_blocked"


class ActionType(str, Enum):
    """Actions taken in response to risks"""
    PAUSE = "pause"
    SLOW_DOWN = "slow_down"
    ROTATE_IDENTITY = "rotate_identity"
    CHANGE_PATTERN = "change_pattern"
    ALERT = "alert"
    SUSPEND = "suspend"


class SafetyIncident(BaseModel):
    """
    Record of safety incidents and responses.
    """

    __tablename__ = "safety_incidents"

    # Related entities
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=True,
        index=True,
    )
    platform: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Incident details
    violation_type: Mapped[ViolationType] = mapped_column(
        String(50),
        nullable=False,
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        String(20),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Detection info
    detected_by: Mapped[str] = mapped_column(String(100), nullable=False)
    detection_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Context
    context_data: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Response
    action_taken: Mapped[Optional[ActionType]] = mapped_column(String(50), nullable=True)
    action_details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class BehaviorProfile(BaseModel):
    """
    Behavioral profile for mimicking human patterns.
    """

    __tablename__ = "behavior_profiles"

    # Agent association
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
        unique=True,
    )

    # Activity patterns
    active_hours_start: Mapped[int] = mapped_column(Integer, default=9)  # 9 AM
    active_hours_end: Mapped[int] = mapped_column(Integer, default=17)  # 5 PM
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

    # Work patterns
    avg_tasks_per_day: Mapped[float] = mapped_column(Float, default=3.0)
    avg_session_length_minutes: Mapped[float] = mapped_column(Float, default=120.0)
    break_frequency_minutes: Mapped[float] = mapped_column(Float, default=45.0)

    # Response patterns
    min_response_delay_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_response_delay_seconds: Mapped[int] = mapped_column(Integer, default=300)
    typing_speed_wpm: Mapped[int] = mapped_column(Integer, default=60)

    # Browsing patterns
    pages_per_session: Mapped[float] = mapped_column(Float, default=15.0)
    scroll_behavior: Mapped[str] = mapped_column(String(50), default="natural")
    mouse_movement_style: Mapped[str] = mapped_column(String(50), default="human")

    # Quirks and variations
    typo_rate: Mapped[float] = mapped_column(Float, default=0.02)  # 2% typo rate
    revision_rate: Mapped[float] = mapped_column(Float, default=0.1)  # 10% revisions
    coffee_break_probability: Mapped[float] = mapped_column(Float, default=0.15)

    # Custom patterns
    custom_patterns: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_calibrated: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RateLimitState(BaseModel):
    """
    Rate limiting state per agent/platform.
    """

    __tablename__ = "rate_limit_states"

    # Scope
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=True,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Limits
    max_per_minute: Mapped[int] = mapped_column(Integer, default=10)
    max_per_hour: Mapped[int] = mapped_column(Integer, default=100)
    max_per_day: Mapped[int] = mapped_column(Integer, default=500)

    # Current state
    current_minute_count: Mapped[int] = mapped_column(Integer, default=0)
    current_hour_count: Mapped[int] = mapped_column(Integer, default=0)
    current_day_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timing
    minute_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    hour_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    day_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Backoff state
    is_backed_off: Mapped[bool] = mapped_column(Boolean, default=False)
    backoff_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    backoff_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    # History
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_blocked: Mapped[int] = mapped_column(Integer, default=0)
    last_request_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ContentFilter(BaseModel):
    """
    Content filtering rules for safety compliance.
    """

    __tablename__ = "content_filters"

    # Filter details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filter_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Matching rules
    patterns: Mapped[list] = mapped_column(JSONB, nullable=False)
    # [{"type": "regex", "pattern": "..."}, {"type": "keyword", "word": "..."}]

    # Action
    action: Mapped[str] = mapped_column(String(50), default="block")  # block, warn, flag, redact
    severity: Mapped[RiskLevel] = mapped_column(String(20), default=RiskLevel.MEDIUM)

    # Scope
    platforms: Mapped[Optional[list]] = mapped_column(JSONB, default=list)  # Empty = all
    content_types: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    times_triggered: Mapped[int] = mapped_column(Integer, default=0)
