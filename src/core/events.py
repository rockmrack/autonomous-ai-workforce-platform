"""
Event system for decoupled communication between components
Supports both sync and async handlers with priority ordering
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Optional, Union
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger(__name__)


class EventPriority(Enum):
    """Event handler priority levels"""

    CRITICAL = 0  # Execute first
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4  # Execute last


@dataclass
class Event:
    """
    Base event class for all platform events.

    Attributes:
        event_type: String identifier for the event type
        data: Event payload data
        event_id: Unique identifier for this event instance
        timestamp: When the event was created
        source: Component that emitted the event
        correlation_id: ID to track related events
    """

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: Optional[str] = None
    correlation_id: Optional[UUID] = None

    def __post_init__(self) -> None:
        if self.correlation_id is None:
            self.correlation_id = self.event_id

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary"""
        return {
            "event_type": self.event_type,
            "event_id": str(self.event_id),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": str(self.correlation_id),
            "data": self.data,
        }

    def create_child(self, event_type: str, data: dict[str, Any]) -> "Event":
        """Create a child event with same correlation ID"""
        return Event(
            event_type=event_type,
            data=data,
            source=self.source,
            correlation_id=self.correlation_id,
        )


# Type alias for event handlers
EventHandler = Union[
    Callable[[Event], None],
    Callable[[Event], Coroutine[Any, Any, None]],
]


@dataclass
class HandlerRegistration:
    """Registration info for an event handler"""

    handler: EventHandler
    priority: EventPriority
    is_async: bool
    filter_fn: Optional[Callable[[Event], bool]] = None


class EventBus:
    """
    Central event bus for platform-wide event handling.

    Features:
    - Async and sync handler support
    - Priority-based execution order
    - Event filtering
    - Wildcard subscriptions
    - Dead letter queue for failed events
    """

    _instance: Optional["EventBus"] = None

    def __new__(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._handlers: dict[str, list[HandlerRegistration]] = defaultdict(list)
        self._dead_letter_queue: list[tuple[Event, Exception]] = []
        self._max_dead_letters = 1000
        self._initialized = True

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
        filter_fn: Optional[Callable[[Event], bool]] = None,
    ) -> None:
        """
        Subscribe a handler to an event type.

        Args:
            event_type: Event type to subscribe to (use "*" for all events)
            handler: Function to call when event is emitted
            priority: Handler execution priority
            filter_fn: Optional function to filter events
        """
        is_async = asyncio.iscoroutinefunction(handler)

        registration = HandlerRegistration(
            handler=handler,
            priority=priority,
            is_async=is_async,
            filter_fn=filter_fn,
        )

        self._handlers[event_type].append(registration)

        # Sort handlers by priority
        self._handlers[event_type].sort(key=lambda r: r.priority.value)

        logger.debug(
            "Event handler registered",
            event_type=event_type,
            handler=handler.__name__,
            priority=priority.name,
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """
        Unsubscribe a handler from an event type.

        Returns True if handler was found and removed.
        """
        handlers = self._handlers.get(event_type, [])
        for i, reg in enumerate(handlers):
            if reg.handler == handler:
                handlers.pop(i)
                logger.debug(
                    "Event handler unsubscribed",
                    event_type=event_type,
                    handler=handler.__name__,
                )
                return True
        return False

    async def emit(self, event: Event) -> list[Exception]:
        """
        Emit an event to all subscribed handlers.

        Returns list of exceptions from failed handlers.
        """
        exceptions: list[Exception] = []

        # Get handlers for this specific event type and wildcard handlers
        handlers = self._handlers.get(event.event_type, []) + self._handlers.get(
            "*", []
        )

        logger.debug(
            "Emitting event",
            event_type=event.event_type,
            event_id=str(event.event_id),
            handler_count=len(handlers),
        )

        for registration in handlers:
            # Apply filter if present
            if registration.filter_fn and not registration.filter_fn(event):
                continue

            try:
                if registration.is_async:
                    await registration.handler(event)
                else:
                    registration.handler(event)
            except Exception as e:
                logger.error(
                    "Event handler failed",
                    event_type=event.event_type,
                    handler=registration.handler.__name__,
                    error=str(e),
                )
                exceptions.append(e)

        # Add to dead letter queue if any handlers failed
        if exceptions:
            self._add_to_dead_letter(event, exceptions[0])

        return exceptions

    def emit_sync(self, event: Event) -> None:
        """Emit event synchronously (for sync contexts)"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.emit(event))
            else:
                loop.run_until_complete(self.emit(event))
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.emit(event))

    async def emit_batch(self, events: list[Event]) -> dict[UUID, list[Exception]]:
        """Emit multiple events, returning exceptions per event"""
        results = {}
        for event in events:
            results[event.event_id] = await self.emit(event)
        return results

    def _add_to_dead_letter(self, event: Event, exception: Exception) -> None:
        """Add failed event to dead letter queue"""
        self._dead_letter_queue.append((event, exception))
        if len(self._dead_letter_queue) > self._max_dead_letters:
            self._dead_letter_queue.pop(0)

    def get_dead_letters(self) -> list[tuple[Event, Exception]]:
        """Get all events in dead letter queue"""
        return self._dead_letter_queue.copy()

    def clear_dead_letters(self) -> int:
        """Clear dead letter queue, return count cleared"""
        count = len(self._dead_letter_queue)
        self._dead_letter_queue.clear()
        return count

    def get_handler_count(self, event_type: Optional[str] = None) -> int:
        """Get number of registered handlers"""
        if event_type:
            return len(self._handlers.get(event_type, []))
        return sum(len(handlers) for handlers in self._handlers.values())


# Singleton instance
event_bus = EventBus()


# ===========================================
# Pre-defined Event Types
# ===========================================


class EventTypes:
    """Standard event types used throughout the platform"""

    # Agent events
    AGENT_CREATED = "agent.created"
    AGENT_ACTIVATED = "agent.activated"
    AGENT_PAUSED = "agent.paused"
    AGENT_SUSPENDED = "agent.suspended"
    AGENT_PROFILE_UPDATED = "agent.profile_updated"

    # Job events
    JOB_DISCOVERED = "job.discovered"
    JOB_SCORED = "job.scored"
    JOB_APPLIED = "job.applied"
    JOB_WON = "job.won"
    JOB_REJECTED = "job.rejected"
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_DELIVERED = "job.delivered"

    # Communication events
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    MESSAGE_FAILED = "message.failed"

    # Proposal events
    PROPOSAL_GENERATED = "proposal.generated"
    PROPOSAL_SUBMITTED = "proposal.submitted"
    PROPOSAL_ACCEPTED = "proposal.accepted"
    PROPOSAL_REJECTED = "proposal.rejected"

    # Quality events
    QA_PASSED = "qa.passed"
    QA_FAILED = "qa.failed"
    REVISION_REQUESTED = "revision.requested"

    # Financial events
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_PENDING = "payment.pending"
    WITHDRAWAL_INITIATED = "withdrawal.initiated"

    # Platform events
    PLATFORM_ERROR = "platform.error"
    PLATFORM_RATE_LIMITED = "platform.rate_limited"
    PLATFORM_BAN_WARNING = "platform.ban_warning"

    # System events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    HEALTH_CHECK = "system.health_check"


# ===========================================
# Decorator for easy handler registration
# ===========================================


def on_event(
    event_type: str,
    priority: EventPriority = EventPriority.NORMAL,
    filter_fn: Optional[Callable[[Event], bool]] = None,
) -> Callable[[EventHandler], EventHandler]:
    """
    Decorator to register a function as an event handler.

    Usage:
        @on_event(EventTypes.JOB_COMPLETED)
        async def handle_job_completed(event: Event):
            ...
    """

    def decorator(handler: EventHandler) -> EventHandler:
        event_bus.subscribe(event_type, handler, priority, filter_fn)
        return handler

    return decorator
