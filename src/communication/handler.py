"""
Communication Handler
Orchestrates all communication with clients
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select, and_, update

from src.core.database import db_manager
from src.core.events import event_bus
from src.core.cache import cache_manager
from src.communication.models import (
    Conversation,
    Message,
    MessageDirection,
    ConversationStatus,
    CommunicationChannel,
    ResponseTemplate,
)
from src.communication.sentiment import sentiment_analyzer, SentimentResult
from src.communication.memory import conversation_memory
from src.llm.client import llm_client

logger = structlog.get_logger(__name__)


class CommunicationHandler:
    """
    Central handler for all client communications.

    Features:
    - Automatic sentiment analysis on all messages
    - Context-aware response generation
    - Template-based quick responses
    - Escalation handling
    - Multi-channel support
    """

    def __init__(self):
        self.response_cache_ttl = 300  # 5 minutes

    async def process_incoming_message(
        self,
        agent_id: uuid.UUID,
        client_id: str,
        client_name: Optional[str],
        client_platform: str,
        content: str,
        channel: CommunicationChannel = CommunicationChannel.PLATFORM_CHAT,
        job_id: Optional[uuid.UUID] = None,
        platform_message_id: Optional[str] = None,
        attachments: Optional[list] = None,
    ) -> dict:
        """
        Process an incoming message from a client.

        Returns processed message with sentiment and suggested responses.
        """
        async with db_manager.session() as session:
            # Find or create conversation
            conversation = await self._get_or_create_conversation(
                session=session,
                agent_id=agent_id,
                client_id=client_id,
                client_name=client_name,
                client_platform=client_platform,
                channel=channel,
                job_id=job_id,
            )

            # Analyze sentiment
            context_summary = conversation.context_summary or ""
            sentiment_result = await sentiment_analyzer.analyze(
                text=content,
                context=context_summary,
            )

            # Create message record
            message = Message(
                conversation_id=conversation.id,
                direction=MessageDirection.INBOUND,
                content=content,
                sentiment=sentiment_result.sentiment,
                sentiment_score=sentiment_result.score,
                sentiment_confidence=sentiment_result.confidence,
                detected_intent=sentiment_result.intent,
                detected_urgency=sentiment_result.urgency_level,
                platform_message_id=platform_message_id,
                attachments=attachments or [],
            )
            session.add(message)

            # Update conversation stats
            conversation.message_count += 1
            conversation.last_message_at = datetime.utcnow()
            conversation.status = ConversationStatus.WAITING_AGENT

            # Update sentiment tracking
            await self._update_conversation_sentiment(
                session=session,
                conversation=conversation,
                new_sentiment=sentiment_result,
            )

            # Check for escalation triggers
            if sentiment_result.urgency_level > 0.7 or sentiment_result.sentiment.value in ["very_negative", "urgent"]:
                conversation.requires_attention = True
                conversation.is_priority = True

            await session.commit()

            # Generate suggested responses asynchronously
            suggestions = await conversation_memory.get_suggested_responses(
                conversation_id=conversation.id,
                incoming_message=content,
            )

            # Emit event
            await event_bus.emit(
                "message.received",
                {
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "agent_id": str(agent_id),
                    "sentiment": sentiment_result.sentiment.value,
                    "urgency": sentiment_result.urgency_level,
                },
            )

            return {
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "sentiment": {
                    "type": sentiment_result.sentiment.value,
                    "score": sentiment_result.score,
                    "confidence": sentiment_result.confidence,
                    "urgency": sentiment_result.urgency_level,
                    "emotions": sentiment_result.detected_emotions,
                    "intent": sentiment_result.intent,
                },
                "suggested_responses": suggestions,
                "requires_attention": conversation.requires_attention,
            }

    async def send_response(
        self,
        conversation_id: uuid.UUID,
        content: str,
        response_template_id: Optional[str] = None,
        auto_generated: bool = True,
    ) -> dict:
        """
        Send a response in a conversation.
        """
        async with db_manager.session() as session:
            # Get conversation
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                raise ValueError(f"Conversation not found: {conversation_id}")

            # Get last inbound message for response time calculation
            result = await session.execute(
                select(Message)
                .where(
                    and_(
                        Message.conversation_id == conversation_id,
                        Message.direction == MessageDirection.INBOUND,
                    )
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_inbound = result.scalar_one_or_none()

            response_time = None
            if last_inbound:
                response_time = (datetime.utcnow() - last_inbound.created_at).total_seconds()

            # Create message
            message = Message(
                conversation_id=conversation_id,
                direction=MessageDirection.OUTBOUND,
                content=content,
                response_time_seconds=response_time,
                was_automated=auto_generated,
                response_template_id=response_template_id,
            )
            session.add(message)

            # Update conversation
            conversation.message_count += 1
            conversation.last_message_at = datetime.utcnow()
            conversation.status = ConversationStatus.WAITING_CLIENT
            conversation.requires_attention = False

            # Update average response time
            if response_time:
                if conversation.avg_response_time_seconds == 0:
                    conversation.avg_response_time_seconds = response_time
                else:
                    # Moving average
                    conversation.avg_response_time_seconds = (
                        conversation.avg_response_time_seconds * 0.8 + response_time * 0.2
                    )

            # Track template usage
            if response_template_id:
                await session.execute(
                    update(ResponseTemplate)
                    .where(ResponseTemplate.id == response_template_id)
                    .values(times_used=ResponseTemplate.times_used + 1)
                )

            await session.commit()

            # Emit event
            await event_bus.emit(
                "message.sent",
                {
                    "conversation_id": str(conversation_id),
                    "message_id": str(message.id),
                    "response_time_seconds": response_time,
                },
            )

            return {
                "message_id": str(message.id),
                "conversation_id": str(conversation_id),
                "response_time_seconds": response_time,
            }

    async def generate_response(
        self,
        conversation_id: uuid.UUID,
        incoming_message: str,
        style: str = "professional",
    ) -> str:
        """
        Generate an AI response for a conversation.
        """
        # Get conversation context
        context = await conversation_memory.get_conversation_context(conversation_id)

        if not context:
            raise ValueError(f"Conversation not found: {conversation_id}")

        preferences = context.get("preferences", {})

        # Build prompt
        recent_messages = "\n".join([
            f"{'Client' if m['direction'] == 'inbound' else 'You'}: {m['content']}"
            for m in context.get("messages", [])[-10:]
        ])

        prompt = f"""You are a professional freelancer responding to a client message.

Conversation history:
{recent_messages}

Client's new message: "{incoming_message}"

Context:
- Client name: {context.get('client', {}).get('name', 'Client')}
- Sentiment trend: {context.get('conversation', {}).get('sentiment_trend', 'stable')}
- Key topics: {', '.join(context.get('conversation', {}).get('key_topics', []))}

Requirements:
- Be {style} in tone
- Response length: {preferences.get('preferred_response_length', 'medium')}
- Address any concerns directly
- Be helpful and solution-oriented

Write your response (without any prefix like "You:" or "Agent:"):"""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=500,
            temperature=0.7,
        )

        return response.content.strip()

    async def get_matching_templates(
        self,
        message_content: str,
        sentiment: str,
        limit: int = 5,
    ) -> list[dict]:
        """
        Find response templates that match the incoming message.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ResponseTemplate)
                .where(ResponseTemplate.is_active == True)
                .limit(50)
            )
            templates = result.scalars().all()

        matched = []
        message_lower = message_content.lower()

        for template in templates:
            # Check keyword match
            keywords = template.trigger_keywords or []
            keyword_match = any(kw.lower() in message_lower for kw in keywords)

            # Check sentiment condition
            sentiment_conditions = template.sentiment_conditions or []
            sentiment_match = not sentiment_conditions or sentiment in sentiment_conditions

            if keyword_match and sentiment_match:
                matched.append({
                    "id": str(template.id),
                    "name": template.name,
                    "category": template.category,
                    "content_variants": template.content_variants,
                    "success_rate": template.success_rate,
                })

        # Sort by success rate
        matched.sort(key=lambda x: x["success_rate"], reverse=True)
        return matched[:limit]

    async def escalate_conversation(
        self,
        conversation_id: uuid.UUID,
        reason: str,
    ) -> None:
        """
        Escalate a conversation for human review.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if conversation:
                conversation.status = ConversationStatus.ESCALATED
                conversation.requires_attention = True
                conversation.is_priority = True

                # Add escalation to metadata
                metadata = conversation.metadata_json or {}
                metadata["escalation"] = {
                    "reason": reason,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                conversation.metadata_json = metadata

                await session.commit()

                # Emit event
                await event_bus.emit(
                    "conversation.escalated",
                    {
                        "conversation_id": str(conversation_id),
                        "reason": reason,
                    },
                )

    async def resolve_conversation(
        self,
        conversation_id: uuid.UUID,
        resolution_notes: Optional[str] = None,
    ) -> None:
        """
        Mark a conversation as resolved.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if conversation:
                conversation.status = ConversationStatus.RESOLVED
                conversation.requires_attention = False
                conversation.is_priority = False

                # Add resolution to metadata
                metadata = conversation.metadata_json or {}
                metadata["resolution"] = {
                    "notes": resolution_notes,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                conversation.metadata_json = metadata

                await session.commit()

                # Learn from successful conversation
                await conversation_memory.learn_client_preferences(
                    client_id=conversation.client_id,
                    client_platform=conversation.client_platform,
                )

                # Emit event
                await event_bus.emit(
                    "conversation.resolved",
                    {"conversation_id": str(conversation_id)},
                )

    async def get_pending_conversations(
        self,
        agent_id: Optional[uuid.UUID] = None,
        priority_only: bool = False,
    ) -> list[dict]:
        """
        Get conversations waiting for agent response.
        """
        async with db_manager.session() as session:
            query = select(Conversation).where(
                Conversation.status == ConversationStatus.WAITING_AGENT
            )

            if agent_id:
                query = query.where(Conversation.agent_id == agent_id)

            if priority_only:
                query = query.where(Conversation.is_priority == True)

            query = query.order_by(
                Conversation.is_priority.desc(),
                Conversation.last_message_at.asc(),
            )

            result = await session.execute(query)
            conversations = result.scalars().all()

            return [
                {
                    "id": str(conv.id),
                    "client_name": conv.client_name,
                    "client_platform": conv.client_platform,
                    "sentiment": conv.overall_sentiment,
                    "sentiment_trend": conv.sentiment_trend,
                    "message_count": conv.message_count,
                    "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                    "is_priority": conv.is_priority,
                    "context_summary": conv.context_summary,
                }
                for conv in conversations
            ]

    async def _get_or_create_conversation(
        self,
        session,
        agent_id: uuid.UUID,
        client_id: str,
        client_name: Optional[str],
        client_platform: str,
        channel: CommunicationChannel,
        job_id: Optional[uuid.UUID],
    ) -> Conversation:
        """Get existing active conversation or create new one."""
        # Look for active conversation with this client
        result = await session.execute(
            select(Conversation)
            .where(
                and_(
                    Conversation.agent_id == agent_id,
                    Conversation.client_id == client_id,
                    Conversation.status.in_([
                        ConversationStatus.ACTIVE,
                        ConversationStatus.WAITING_AGENT,
                        ConversationStatus.WAITING_CLIENT,
                    ]),
                )
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        conversation = result.scalar_one_or_none()

        if conversation:
            return conversation

        # Create new conversation
        conversation = Conversation(
            agent_id=agent_id,
            client_id=client_id,
            client_name=client_name,
            client_platform=client_platform,
            channel=channel,
            job_id=job_id,
        )
        session.add(conversation)
        await session.flush()

        return conversation

    async def _update_conversation_sentiment(
        self,
        session,
        conversation: Conversation,
        new_sentiment: SentimentResult,
    ) -> None:
        """Update conversation sentiment tracking."""
        # Get sentiment history
        result = await session.execute(
            select(Message.sentiment_score)
            .where(
                and_(
                    Message.conversation_id == conversation.id,
                    Message.direction == MessageDirection.INBOUND,
                )
            )
            .order_by(Message.created_at)
        )
        history = [r[0] for r in result.fetchall() if r[0] is not None]
        history.append(new_sentiment.score)

        # Calculate trend
        trend = sentiment_analyzer.calculate_sentiment_trend(history)

        # Update conversation
        conversation.overall_sentiment = new_sentiment.sentiment
        conversation.sentiment_score = new_sentiment.score
        conversation.sentiment_trend = trend


# Singleton instance
communication_handler = CommunicationHandler()
