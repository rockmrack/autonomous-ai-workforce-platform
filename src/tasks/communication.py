"""
Communication Tasks - Message handling and client interaction
"""

import asyncio
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery tasks"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    name="src.tasks.communication.check_all_messages",
    max_retries=3,
    default_retry_delay=30,
)
def check_all_messages(self):
    """
    Check for new messages across all platforms.

    Runs periodically via Celery Beat.
    """
    async def _check():
        from src.communication.handler import message_handler
        from src.agents.manager import agent_manager
        from config import settings

        results = {}
        agents = await agent_manager.get_active_agents()

        for agent in agents:
            for platform in agent.platforms:
                try:
                    messages = await message_handler.check_messages(
                        agent_id=agent.id,
                        platform=platform,
                    )

                    key = f"{agent.id}:{platform}"
                    results[key] = {
                        "new_messages": len(messages),
                        "status": "success",
                    }

                    # Queue responses for new messages
                    for msg in messages:
                        if msg.requires_response:
                            respond_to_message.delay(
                                str(agent.id),
                                str(msg.conversation_id),
                                str(msg.id),
                            )

                except Exception as e:
                    logger.error(f"Failed to check messages for {agent.id} on {platform}: {e}")
                    results[f"{agent.id}:{platform}"] = {
                        "status": "error",
                        "error": str(e),
                    }

        return results

    try:
        return run_async(_check())
    except Exception as exc:
        logger.error(f"check_all_messages failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.communication.send_message",
    max_retries=3,
    default_retry_delay=60,
)
def send_message(
    self,
    agent_id: str,
    conversation_id: str,
    message_content: str,
    message_type: str = "text",
):
    """
    Send a message on behalf of an agent.

    Args:
        agent_id: Agent sending the message
        conversation_id: Conversation to send to
        message_content: Message content
        message_type: Type of message (text, proposal, etc.)
    """
    async def _send():
        from uuid import UUID
        from src.communication.handler import message_handler
        from src.safety.humanizer import humanizer

        # Humanize the message
        humanized = await humanizer.humanize_text(message_content)

        # Send via handler
        result = await message_handler.send_message(
            agent_id=UUID(agent_id),
            conversation_id=UUID(conversation_id),
            content=humanized,
            message_type=message_type,
        )

        return {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "message_id": str(result.id),
            "status": "sent",
        }

    try:
        return run_async(_send())
    except Exception as exc:
        logger.error(f"send_message failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.communication.respond_to_message",
    max_retries=3,
    default_retry_delay=120,
)
def respond_to_message(self, agent_id: str, conversation_id: str, message_id: str):
    """
    Generate and send a response to a message.

    Uses LLM to generate contextual response.
    """
    async def _respond():
        from uuid import UUID
        from src.communication.handler import message_handler

        response = await message_handler.generate_response(
            agent_id=UUID(agent_id),
            conversation_id=UUID(conversation_id),
            message_id=UUID(message_id),
        )

        if response:
            # Send the response
            result = await message_handler.send_message(
                agent_id=UUID(agent_id),
                conversation_id=UUID(conversation_id),
                content=response.content,
            )

            return {
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "response_id": str(result.id),
                "status": "responded",
            }

        return {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "status": "no_response_needed",
        }

    try:
        return run_async(_respond())
    except Exception as exc:
        logger.error(f"respond_to_message failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    name="src.tasks.communication.send_follow_up",
)
def send_follow_up(agent_id: str, conversation_id: str, follow_up_type: str):
    """
    Send a follow-up message.

    Args:
        agent_id: Agent ID
        conversation_id: Conversation ID
        follow_up_type: Type of follow-up (proposal, check_in, etc.)
    """
    async def _follow_up():
        from uuid import UUID
        from src.communication.handler import message_handler

        result = await message_handler.send_follow_up(
            agent_id=UUID(agent_id),
            conversation_id=UUID(conversation_id),
            follow_up_type=follow_up_type,
        )

        return {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "follow_up_type": follow_up_type,
            "message_id": str(result.id) if result else None,
        }

    return run_async(_follow_up())


@shared_task(
    name="src.tasks.communication.analyze_conversation",
)
def analyze_conversation(conversation_id: str):
    """
    Analyze a conversation for sentiment and intent.

    Args:
        conversation_id: Conversation to analyze
    """
    async def _analyze():
        from uuid import UUID
        from src.communication.handler import message_handler

        analysis = await message_handler.analyze_conversation(
            conversation_id=UUID(conversation_id),
        )

        return {
            "conversation_id": conversation_id,
            "sentiment": analysis.sentiment,
            "intent": analysis.client_intent,
            "urgency": analysis.urgency,
            "suggested_action": analysis.suggested_action,
        }

    return run_async(_analyze())


@shared_task(
    name="src.tasks.communication.handle_negotiation",
)
def handle_negotiation(
    agent_id: str,
    conversation_id: str,
    client_offer: float,
    original_bid: float,
):
    """
    Handle a price negotiation from client.

    Args:
        agent_id: Agent handling negotiation
        conversation_id: Conversation ID
        client_offer: Client's counter-offer
        original_bid: Original bid amount
    """
    async def _negotiate():
        from uuid import UUID
        from src.communication.handler import message_handler
        from src.bidding.bid_calculator import bid_calculator

        # Calculate counter-offer
        counter = await bid_calculator.calculate_counter_offer(
            original_bid=original_bid,
            client_offer=client_offer,
        )

        # Generate negotiation message
        if counter["accept"]:
            message = f"Thank you for your offer. I'm happy to accept ${client_offer:.2f} for this project. When would you like to get started?"
        else:
            message = f"Thank you for considering my proposal. I can offer a slight adjustment to ${counter['counter_offer']:.2f}, which reflects the scope of work involved. This ensures I can deliver high-quality results. Would this work for you?"

        # Send response
        result = await message_handler.send_message(
            agent_id=UUID(agent_id),
            conversation_id=UUID(conversation_id),
            content=message,
        )

        return {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "accepted": counter["accept"],
            "counter_offer": counter.get("counter_offer"),
            "message_id": str(result.id),
        }

    return run_async(_negotiate())
