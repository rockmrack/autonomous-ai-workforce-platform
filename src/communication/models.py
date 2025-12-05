"""
Communication data models
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models import BaseModel


class MessageDirection(str, Enum):
    """Direction of message"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class SentimentType(str, Enum):
    """Sentiment classification"""
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"
    URGENT = "urgent"
    CONFUSED = "confused"


class CommunicationChannel(str, Enum):
    """Communication channel types"""
    PLATFORM_CHAT = "platform_chat"
    EMAIL = "email"
    VIDEO_CALL = "video_call"
    VOICE_CALL = "voice_call"


class ConversationStatus(str, Enum):
    """Status of conversation"""
    ACTIVE = "active"
    WAITING_CLIENT = "waiting_client"
    WAITING_AGENT = "waiting_agent"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Conversation(BaseModel):
    """
    Represents a conversation thread with a client.
    Maintains context, sentiment tracking, and history.
    """

    __tablename__ = "conversations"

    # Relationships
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovered_jobs.id"),
        nullable=True,
        index=True,
    )

    # Client info
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_platform: Mapped[str] = mapped_column(String(100), nullable=False)

    # Conversation state
    status: Mapped[ConversationStatus] = mapped_column(
        String(50),
        default=ConversationStatus.ACTIVE,
        nullable=False,
    )
    channel: Mapped[CommunicationChannel] = mapped_column(
        String(50),
        default=CommunicationChannel.PLATFORM_CHAT,
        nullable=False,
    )

    # Sentiment tracking
    overall_sentiment: Mapped[SentimentType] = mapped_column(
        String(50),
        default=SentimentType.NEUTRAL,
        nullable=False,
    )
    sentiment_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    sentiment_trend: Mapped[str] = mapped_column(
        String(20),
        default="stable",
        nullable=False,
    )  # improving, stable, declining

    # Context and memory
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_topics: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    client_preferences: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    action_items: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Statistics
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Flags
    requires_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    is_priority: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        order_by="Message.created_at",
    )


class Message(BaseModel):
    """
    Individual message in a conversation.
    Includes sentiment analysis and response metadata.
    """

    __tablename__ = "messages"

    # Relationships
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )

    # Message content
    direction: Mapped[MessageDirection] = mapped_column(
        String(20),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(50),
        default="text",
        nullable=False,
    )  # text, file, image, etc.

    # Attachments
    attachments: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Sentiment analysis
    sentiment: Mapped[SentimentType] = mapped_column(
        String(50),
        default=SentimentType.NEUTRAL,
        nullable=False,
    )
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Extracted information
    detected_intent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_entities: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    detected_urgency: Mapped[float] = mapped_column(Float, default=0.0)

    # Response metadata (for outbound)
    response_time_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    was_automated: Mapped[bool] = mapped_column(Boolean, default=True)
    response_template_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Platform metadata
    platform_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    platform_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Reading status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )


class ResponseTemplate(BaseModel):
    """
    Pre-defined response templates for common scenarios.
    Supports personalization and A/B testing.
    """

    __tablename__ = "response_templates"

    # Template info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    trigger_keywords: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Content variants
    content_variants: Mapped[list] = mapped_column(JSONB, nullable=False)
    # [{"id": "v1", "content": "...", "weight": 0.5}, ...]

    # Personalization placeholders
    placeholders: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    # ["client_name", "project_name", "deadline", ...]

    # Conditions
    sentiment_conditions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    # When to use this template based on sentiment

    # Performance tracking
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_sentiment_change: Mapped[float] = mapped_column(Float, default=0.0)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CommunicationPreference(BaseModel):
    """
    Client communication preferences learned over time.
    """

    __tablename__ = "communication_preferences"

    # Client identification
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    client_platform: Mapped[str] = mapped_column(String(100), nullable=False)

    # Communication style preferences
    preferred_tone: Mapped[str] = mapped_column(
        String(50),
        default="professional",
    )  # professional, casual, formal, friendly
    preferred_response_length: Mapped[str] = mapped_column(
        String(50),
        default="medium",
    )  # short, medium, detailed
    prefers_bullet_points: Mapped[bool] = mapped_column(Boolean, default=False)
    prefers_technical_detail: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timing preferences
    preferred_contact_times: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    timezone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    avg_response_expectation_hours: Mapped[float] = mapped_column(Float, default=24.0)

    # Learned patterns
    common_concerns: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    communication_history_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relationship_score: Mapped[float] = mapped_column(Float, default=0.5)

    # Flags
    is_high_value: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_special_handling: Mapped[bool] = mapped_column(Boolean, default=False)
    special_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
