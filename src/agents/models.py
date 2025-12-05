"""
Agent SQLAlchemy models
Defines agent entities with all capabilities and configurations
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
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models import BaseModel


class AgentStatus(str, enum.Enum):
    """Agent status enumeration"""

    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    TRAINING = "training"
    RETIRED = "retired"


class AgentCapability(str, enum.Enum):
    """Agent capability types"""

    # Research
    WEB_RESEARCH = "web_research"
    MARKET_RESEARCH = "market_research"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    LEAD_GENERATION = "lead_generation"
    DATA_EXTRACTION = "data_extraction"

    # Writing
    CONTENT_WRITING = "content_writing"
    SEO_WRITING = "seo_writing"
    COPYWRITING = "copywriting"
    TECHNICAL_WRITING = "technical_writing"
    EMAIL_WRITING = "email_writing"
    BLOG_WRITING = "blog_writing"
    SOCIAL_MEDIA = "social_media"

    # Data
    DATA_ENTRY = "data_entry"
    SPREADSHEET = "spreadsheet"
    DATA_ANALYSIS = "data_analysis"
    TRANSCRIPTION = "transcription"

    # Technical
    CODE_PYTHON = "code_python"
    CODE_JAVASCRIPT = "code_javascript"
    CODE_GENERAL = "code_general"
    API_INTEGRATION = "api_integration"
    WEB_SCRAPING = "web_scraping"
    AUTOMATION = "automation"

    # Other
    TRANSLATION = "translation"
    PROOFREADING = "proofreading"
    CUSTOMER_SUPPORT = "customer_support"
    VIRTUAL_ASSISTANT = "virtual_assistant"
    IMAGE_ANALYSIS = "image_analysis"


class Agent(BaseModel):
    """
    AI Agent model - represents an autonomous worker.

    Features:
    - Multiple platform profiles
    - Dynamic capabilities
    - Learning and adaptation
    - Performance tracking
    """

    __tablename__ = "agents"

    # Identity
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    persona_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Capabilities
    capabilities: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    specializations: Mapped[list] = mapped_column(
        JSONB, nullable=True, default=list
    )

    # Performance metrics
    hourly_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("25.00")
    )
    min_project_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("50.00")
    )
    success_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.0")
    )
    average_rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.0")
    )
    total_ratings: Mapped[int] = mapped_column(Integer, default=0)
    total_earnings: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00")
    )
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Behavior configuration
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    working_hours: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"start": 9, "end": 17, "days": [1, 2, 3, 4, 5]},
    )
    response_delay_range: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"min": 60, "max": 300},
    )
    writing_style: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Status
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"),
        default=AgentStatus.ACTIVE,
    )
    status_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ML/Learning
    embedding: Mapped[Optional[list]] = mapped_column(Vector(1536), nullable=True)
    learning_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Activity
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    platform_profiles: Mapped[list["AgentPlatformProfile"]] = relationship(
        "AgentPlatformProfile",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    portfolio_items: Mapped[list["AgentPortfolio"]] = relationship(
        "AgentPortfolio",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def has_capability(self, capability: AgentCapability) -> bool:
        """Check if agent has a specific capability"""
        return capability.value in self.capabilities

    def add_capability(self, capability: AgentCapability) -> None:
        """Add a capability to the agent"""
        if capability.value not in self.capabilities:
            self.capabilities = [*self.capabilities, capability.value]

    def remove_capability(self, capability: AgentCapability) -> None:
        """Remove a capability from the agent"""
        self.capabilities = [c for c in self.capabilities if c != capability.value]

    def can_work_now(self) -> bool:
        """Check if agent is available to work based on working hours"""
        if self.status != AgentStatus.ACTIVE:
            return False

        from datetime import datetime
        import pytz

        try:
            tz = pytz.timezone(self.timezone)
            now = datetime.now(tz)
            current_hour = now.hour
            current_day = now.isoweekday()

            working_days = self.working_hours.get("days", [1, 2, 3, 4, 5])
            start_hour = self.working_hours.get("start", 9)
            end_hour = self.working_hours.get("end", 17)

            return current_day in working_days and start_hour <= current_hour < end_hour
        except Exception:
            return True  # Default to available if timezone issue

    def calculate_success_rate(self) -> Decimal:
        """Calculate success rate from jobs completed/failed"""
        total = self.jobs_completed + self.jobs_failed
        if total == 0:
            return Decimal("0.0")
        return Decimal(self.jobs_completed) / Decimal(total)

    def update_stats(self, job_completed: bool, earnings: Decimal = Decimal("0")) -> None:
        """Update agent statistics after job outcome"""
        if job_completed:
            self.jobs_completed += 1
            self.total_earnings += earnings
        else:
            self.jobs_failed += 1

        self.success_rate = self.calculate_success_rate()
        self.last_active_at = datetime.utcnow()


class AgentPlatformProfile(BaseModel):
    """
    Platform-specific profile for an agent.
    Each agent can have profiles on multiple freelance platforms.
    """

    __tablename__ = "agent_platform_profiles"

    # Disable BaseModel defaults we don't need
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, insert_default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, insert_default=None
    )
    version: Mapped[int] = mapped_column(Integer, default=1, insert_default=1)

    # Foreign key
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Platform info
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    profile_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Platform-specific data
    profile_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    credentials_encrypted: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)

    # Performance on platform
    earnings_on_platform: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )
    jobs_on_platform: Mapped[int] = mapped_column(Integer, default=0)
    rating_on_platform: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="active")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Risk tracking
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    last_warning_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restriction_level: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="platform_profiles")

    def is_at_risk(self) -> bool:
        """Check if account is at risk of suspension"""
        return self.warning_count >= 2 or self.restriction_level > 0

    def record_warning(self, reason: str) -> None:
        """Record a platform warning"""
        self.warning_count += 1
        self.last_warning_at = datetime.utcnow()
        if "warnings" not in self.profile_data:
            self.profile_data["warnings"] = []
        self.profile_data["warnings"].append({
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        })


class AgentPortfolio(BaseModel):
    """
    Portfolio items for an agent.
    Can be real completed work or AI-generated samples.
    """

    __tablename__ = "agent_portfolio"

    # Disable unused BaseModel defaults
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, insert_default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, insert_default=None
    )
    version: Mapped[int] = mapped_column(Integer, default=1, insert_default=1)

    # Foreign key
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Portfolio item details
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    skills_demonstrated: Mapped[list] = mapped_column(JSONB, default=list)

    # Files
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Generation info
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Display settings
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="portfolio_items")
