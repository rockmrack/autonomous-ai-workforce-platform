"""
Conversation Memory System
Maintains context and history for intelligent responses
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import db_manager
from src.core.cache import cache_manager
from src.communication.models import Conversation, Message, CommunicationPreference
from src.llm.client import llm_client

logger = structlog.get_logger(__name__)


class ConversationMemory:
    """
    Manages conversation history and context for natural interactions.

    Features:
    - Automatic context summarization
    - Key topic extraction
    - Client preference learning
    - Response suggestion based on history
    """

    def __init__(self, max_context_messages: int = 50):
        self.max_context_messages = max_context_messages

    async def get_conversation_context(
        self,
        conversation_id: uuid.UUID,
        max_messages: int = 20,
    ) -> dict:
        """
        Get full context for a conversation including history and preferences.
        """
        async with db_manager.session() as session:
            # Get conversation
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                return {}

            # Get recent messages
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(max_messages)
            )
            messages = list(reversed(result.scalars().all()))

            # Get client preferences
            result = await session.execute(
                select(CommunicationPreference)
                .where(CommunicationPreference.client_id == conversation.client_id)
            )
            preferences = result.scalar_one_or_none()

            return {
                "conversation": {
                    "id": str(conversation.id),
                    "status": conversation.status.value if hasattr(conversation.status, 'value') else conversation.status,
                    "overall_sentiment": conversation.overall_sentiment,
                    "sentiment_trend": conversation.sentiment_trend,
                    "context_summary": conversation.context_summary,
                    "key_topics": conversation.key_topics,
                    "action_items": conversation.action_items,
                },
                "client": {
                    "id": conversation.client_id,
                    "name": conversation.client_name,
                    "platform": conversation.client_platform,
                },
                "preferences": {
                    "tone": preferences.preferred_tone if preferences else "professional",
                    "response_length": preferences.preferred_response_length if preferences else "medium",
                    "prefers_bullet_points": preferences.prefers_bullet_points if preferences else False,
                    "prefers_technical_detail": preferences.prefers_technical_detail if preferences else True,
                    "common_concerns": preferences.common_concerns if preferences else [],
                } if preferences else {},
                "messages": [
                    {
                        "direction": msg.direction.value if hasattr(msg.direction, 'value') else msg.direction,
                        "content": msg.content,
                        "sentiment": msg.sentiment,
                        "timestamp": msg.created_at.isoformat(),
                    }
                    for msg in messages
                ],
            }

    async def update_context_summary(
        self,
        conversation_id: uuid.UUID,
    ) -> str:
        """
        Generate and update context summary using LLM.
        """
        context = await self.get_conversation_context(conversation_id)

        if not context.get("messages"):
            return ""

        # Build message history for summarization
        message_text = "\n".join([
            f"{'Client' if m['direction'] == 'inbound' else 'Agent'}: {m['content']}"
            for m in context["messages"][-20:]  # Last 20 messages
        ])

        prompt = f"""Summarize this conversation concisely, focusing on:
1. Main topic/request
2. Current status
3. Any outstanding issues or action items
4. Client's satisfaction level

Conversation:
{message_text}

Provide a 2-3 sentence summary:"""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=200,
            temperature=0.3,
        )

        summary = response.content.strip()

        # Update in database
        async with db_manager.session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.context_summary = summary
                await session.commit()

        return summary

    async def extract_key_topics(
        self,
        conversation_id: uuid.UUID,
    ) -> list[str]:
        """
        Extract key topics from conversation.
        """
        context = await self.get_conversation_context(conversation_id)

        if not context.get("messages"):
            return []

        message_text = "\n".join([m["content"] for m in context["messages"]])

        prompt = f"""Extract the main topics discussed in this conversation.
Return as a comma-separated list of 3-5 key topics.

Conversation text:
{message_text}

Topics:"""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=100,
            temperature=0.2,
        )

        topics = [t.strip() for t in response.content.split(',')]

        # Update in database
        async with db_manager.session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.key_topics = topics
                await session.commit()

        return topics

    async def learn_client_preferences(
        self,
        client_id: str,
        client_platform: str,
    ) -> dict:
        """
        Analyze past conversations to learn client preferences.
        """
        async with db_manager.session() as session:
            # Get all conversations with this client
            result = await session.execute(
                select(Conversation)
                .where(
                    and_(
                        Conversation.client_id == client_id,
                        Conversation.client_platform == client_platform,
                    )
                )
                .order_by(Conversation.created_at.desc())
                .limit(10)
            )
            conversations = result.scalars().all()

            if not conversations:
                return {}

            # Gather all messages
            all_messages = []
            for conv in conversations:
                result = await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at)
                )
                all_messages.extend(result.scalars().all())

            # Analyze patterns
            inbound_messages = [m for m in all_messages if m.direction.value == "inbound"]
            outbound_messages = [m for m in all_messages if m.direction.value == "outbound"]

            # Calculate average message length
            avg_client_length = sum(len(m.content) for m in inbound_messages) / max(len(inbound_messages), 1)

            # Determine preferred response length
            if avg_client_length < 100:
                preferred_length = "short"
            elif avg_client_length < 300:
                preferred_length = "medium"
            else:
                preferred_length = "detailed"

            # Check for bullet point preference (if client uses them)
            uses_bullets = any('•' in m.content or '-' in m.content for m in inbound_messages)

            # Check for technical preference
            technical_terms = {"api", "code", "function", "database", "server", "deploy", "bug", "error"}
            uses_technical = any(
                any(term in m.content.lower() for term in technical_terms)
                for m in inbound_messages
            )

            # Calculate relationship score based on sentiment history
            sentiment_scores = [m.sentiment_score for m in inbound_messages if m.sentiment_score]
            relationship_score = sum(sentiment_scores) / max(len(sentiment_scores), 1) if sentiment_scores else 0.5
            relationship_score = (relationship_score + 1) / 2  # Normalize to 0-1

            preferences = {
                "preferred_response_length": preferred_length,
                "prefers_bullet_points": uses_bullets,
                "prefers_technical_detail": uses_technical,
                "relationship_score": relationship_score,
            }

            # Update or create preferences
            result = await session.execute(
                select(CommunicationPreference)
                .where(CommunicationPreference.client_id == client_id)
            )
            pref = result.scalar_one_or_none()

            if pref:
                for key, value in preferences.items():
                    setattr(pref, key, value)
            else:
                pref = CommunicationPreference(
                    client_id=client_id,
                    client_platform=client_platform,
                    **preferences,
                )
                session.add(pref)

            await session.commit()
            return preferences

    async def get_suggested_responses(
        self,
        conversation_id: uuid.UUID,
        incoming_message: str,
        num_suggestions: int = 3,
    ) -> list[dict]:
        """
        Generate suggested responses based on context and history.
        """
        context = await self.get_conversation_context(conversation_id)

        if not context:
            return []

        preferences = context.get("preferences", {})
        tone = preferences.get("tone", "professional")
        length = preferences.get("response_length", "medium")

        length_guide = {
            "short": "Keep response under 50 words.",
            "medium": "Keep response between 50-150 words.",
            "detailed": "Provide a comprehensive response of 150-300 words.",
        }

        # Build context for LLM
        recent_messages = "\n".join([
            f"{'Client' if m['direction'] == 'inbound' else 'Agent'}: {m['content']}"
            for m in context.get("messages", [])[-5:]
        ])

        prompt = f"""You are responding to a client message. Generate {num_suggestions} different response options.

Conversation context:
{recent_messages}

New client message: "{incoming_message}"

Requirements:
- Tone: {tone}
- {length_guide.get(length, '')}
- Use bullet points: {preferences.get('prefers_bullet_points', False)}

Generate {num_suggestions} response options, each on a new line starting with "OPTION N:":"""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=800,
            temperature=0.7,
        )

        # Parse options
        suggestions = []
        current_option = None

        for line in response.content.split('\n'):
            if line.startswith('OPTION'):
                if current_option:
                    suggestions.append(current_option)
                current_option = {"content": "", "confidence": 0.8}
            elif current_option is not None:
                current_option["content"] += line + "\n"

        if current_option and current_option["content"]:
            suggestions.append(current_option)

        # Clean up and score
        for i, suggestion in enumerate(suggestions):
            suggestion["content"] = suggestion["content"].strip()
            suggestion["confidence"] = 0.9 - (i * 0.1)  # First option gets highest confidence

        return suggestions[:num_suggestions]

    async def get_action_items(
        self,
        conversation_id: uuid.UUID,
    ) -> list[dict]:
        """
        Extract action items from conversation.
        """
        context = await self.get_conversation_context(conversation_id)

        if not context.get("messages"):
            return []

        message_text = "\n".join([
            f"{'Client' if m['direction'] == 'inbound' else 'Agent'}: {m['content']}"
            for m in context["messages"][-20:]
        ])

        prompt = f"""Extract all action items and commitments from this conversation.
For each action item, identify:
1. What needs to be done
2. Who is responsible (client or agent)
3. Any deadline mentioned

Conversation:
{message_text}

List action items in this format:
- ACTION: [description] | OWNER: [client/agent] | DEADLINE: [date or "none"]"""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=400,
            temperature=0.2,
        )

        action_items = []
        for line in response.content.split('\n'):
            if line.strip().startswith('-'):
                parts = line.strip('- ').split('|')
                if len(parts) >= 2:
                    item = {
                        "description": parts[0].replace('ACTION:', '').strip(),
                        "owner": parts[1].replace('OWNER:', '').strip() if len(parts) > 1 else "agent",
                        "deadline": parts[2].replace('DEADLINE:', '').strip() if len(parts) > 2 else None,
                        "completed": False,
                    }
                    action_items.append(item)

        # Update in database
        async with db_manager.session() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.action_items = action_items
                await session.commit()

        return action_items


# Singleton instance
conversation_memory = ConversationMemory()
