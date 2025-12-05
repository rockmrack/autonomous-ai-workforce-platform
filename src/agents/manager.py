"""
Agent Manager - Handles agent lifecycle and operations
Enhanced with intelligent agent selection and performance tracking
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.database import db_manager
from src.core.events import Event, EventTypes, event_bus
from src.core.exceptions import (
    AgentBusyError,
    AgentCapabilityError,
    AgentNotFoundError,
    AgentSuspendedError,
)
from .models import Agent, AgentCapability, AgentPlatformProfile, AgentStatus

logger = structlog.get_logger(__name__)


class AgentManager:
    """
    Manages the agent fleet with intelligent operations.

    Features:
    - Smart agent selection based on capabilities and performance
    - Workload balancing across agents
    - Performance monitoring and optimization
    - Automatic agent rotation for anti-detection
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        self._session = session

    @property
    async def session(self) -> AsyncSession:
        """Get database session"""
        if self._session:
            return self._session
        async with db_manager.session() as session:
            return session

    async def create_agent(
        self,
        name: str,
        email: str,
        capabilities: list[AgentCapability],
        persona_description: Optional[str] = None,
        hourly_rate: Decimal = Decimal("25.00"),
        timezone: str = "UTC",
        working_hours: Optional[dict] = None,
        writing_style: Optional[dict] = None,
    ) -> Agent:
        """
        Create a new agent with specified configuration.

        Args:
            name: Human-like name for the agent
            email: Unique email for the agent
            capabilities: List of agent capabilities
            persona_description: Background story for the agent
            hourly_rate: Default hourly rate for bidding
            timezone: Agent's operating timezone
            working_hours: Work schedule configuration
            writing_style: Writing style preferences

        Returns:
            Created Agent instance
        """
        async with db_manager.session() as session:
            agent = Agent(
                name=name,
                email=email,
                capabilities=[c.value for c in capabilities],
                persona_description=persona_description,
                hourly_rate=hourly_rate,
                timezone=timezone,
                working_hours=working_hours or {"start": 9, "end": 17, "days": [1, 2, 3, 4, 5]},
                writing_style=writing_style or {},
                status=AgentStatus.ACTIVE,
            )

            session.add(agent)
            await session.commit()
            await session.refresh(agent)

            logger.info(
                "Agent created",
                agent_id=str(agent.id),
                name=name,
                capabilities=[c.value for c in capabilities],
            )

            # Emit event
            await event_bus.emit(Event(
                event_type=EventTypes.AGENT_CREATED,
                data={"agent_id": str(agent.id), "name": name},
                source="agent_manager",
            ))

            return agent

    async def get_agent(self, agent_id: UUID) -> Agent:
        """Get agent by ID"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Agent).where(
                    and_(Agent.id == agent_id, Agent.is_deleted == False)
                )
            )
            agent = result.scalar_one_or_none()

            if not agent:
                raise AgentNotFoundError(str(agent_id))

            return agent

    async def get_all_agents(
        self,
        status: Optional[AgentStatus] = None,
        capability: Optional[AgentCapability] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Agent]:
        """Get all agents with optional filtering"""
        async with db_manager.session() as session:
            query = select(Agent).where(Agent.is_deleted == False)

            if status:
                query = query.where(Agent.status == status)

            if capability:
                query = query.where(
                    Agent.capabilities.contains([capability.value])
                )

            query = query.order_by(Agent.success_rate.desc()).limit(limit).offset(offset)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_available_agent(
        self,
        required_capabilities: list[AgentCapability],
        platform: Optional[str] = None,
        exclude_agents: Optional[list[UUID]] = None,
        prefer_high_performers: bool = True,
    ) -> Optional[Agent]:
        """
        Find the best available agent for a task.

        Selection criteria:
        1. Has all required capabilities
        2. Is currently active and within working hours
        3. Has available capacity (not too many active jobs)
        4. Has good standing on the target platform
        5. Highest success rate / performance score

        Args:
            required_capabilities: Capabilities needed for the task
            platform: Target platform (to check profile status)
            exclude_agents: Agents to exclude from selection
            prefer_high_performers: Prioritize agents with better track records

        Returns:
            Best matching agent or None
        """
        async with db_manager.session() as session:
            # Build base query for active agents with required capabilities
            capability_values = [c.value for c in required_capabilities]

            query = (
                select(Agent)
                .where(
                    and_(
                        Agent.is_deleted == False,
                        Agent.status == AgentStatus.ACTIVE,
                    )
                )
            )

            # Filter by capabilities
            for cap in capability_values:
                query = query.where(Agent.capabilities.contains([cap]))

            # Exclude specific agents
            if exclude_agents:
                query = query.where(Agent.id.notin_(exclude_agents))

            # Order by performance
            if prefer_high_performers:
                query = query.order_by(
                    Agent.success_rate.desc(),
                    Agent.average_rating.desc(),
                    Agent.jobs_completed.desc(),
                )
            else:
                # Round-robin based on last activity
                query = query.order_by(Agent.last_active_at.asc().nullsfirst())

            result = await session.execute(query)
            candidates = list(result.scalars().all())

            # Filter by working hours and platform status
            for agent in candidates:
                # Check working hours
                if not agent.can_work_now():
                    continue

                # Check platform profile if specified
                if platform:
                    profile = await self._get_platform_profile(
                        session, agent.id, platform
                    )
                    if profile and profile.is_at_risk():
                        continue

                # TODO: Check active job count against limit

                return agent

            return None

    async def _get_platform_profile(
        self,
        session: AsyncSession,
        agent_id: UUID,
        platform: str,
    ) -> Optional[AgentPlatformProfile]:
        """Get agent's profile for a specific platform"""
        result = await session.execute(
            select(AgentPlatformProfile).where(
                and_(
                    AgentPlatformProfile.agent_id == agent_id,
                    AgentPlatformProfile.platform == platform,
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_agent_status(
        self,
        agent_id: UUID,
        status: AgentStatus,
        reason: Optional[str] = None,
    ) -> Agent:
        """Update agent status with reason"""
        async with db_manager.session() as session:
            agent = await self.get_agent(agent_id)

            old_status = agent.status
            agent.status = status
            agent.status_reason = reason

            session.add(agent)
            await session.commit()

            logger.info(
                "Agent status updated",
                agent_id=str(agent_id),
                old_status=old_status.value,
                new_status=status.value,
                reason=reason,
            )

            # Emit appropriate event
            event_type = {
                AgentStatus.ACTIVE: EventTypes.AGENT_ACTIVATED,
                AgentStatus.PAUSED: EventTypes.AGENT_PAUSED,
                AgentStatus.SUSPENDED: EventTypes.AGENT_SUSPENDED,
            }.get(status)

            if event_type:
                await event_bus.emit(Event(
                    event_type=event_type,
                    data={
                        "agent_id": str(agent_id),
                        "reason": reason,
                        "old_status": old_status.value,
                    },
                    source="agent_manager",
                ))

            return agent

    async def add_platform_profile(
        self,
        agent_id: UUID,
        platform: str,
        username: str,
        profile_url: Optional[str] = None,
        credentials: Optional[bytes] = None,
    ) -> AgentPlatformProfile:
        """Add a platform profile for an agent"""
        async with db_manager.session() as session:
            # Verify agent exists
            await self.get_agent(agent_id)

            profile = AgentPlatformProfile(
                agent_id=agent_id,
                platform=platform,
                username=username,
                profile_url=profile_url,
                credentials_encrypted=credentials,
            )

            session.add(profile)
            await session.commit()
            await session.refresh(profile)

            logger.info(
                "Platform profile added",
                agent_id=str(agent_id),
                platform=platform,
                username=username,
            )

            return profile

    async def update_agent_performance(
        self,
        agent_id: UUID,
        job_completed: bool,
        earnings: Decimal = Decimal("0"),
        rating: Optional[Decimal] = None,
    ) -> Agent:
        """Update agent performance metrics after job outcome"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one_or_none()

            if not agent:
                raise AgentNotFoundError(str(agent_id))

            # Update stats
            agent.update_stats(job_completed, earnings)

            # Update rating if provided
            if rating is not None:
                total_rating_sum = agent.average_rating * agent.total_ratings
                agent.total_ratings += 1
                agent.average_rating = (total_rating_sum + rating) / agent.total_ratings

            session.add(agent)
            await session.commit()

            return agent

    async def get_agent_stats(self, agent_id: UUID) -> dict:
        """Get comprehensive agent statistics"""
        agent = await self.get_agent(agent_id)

        return {
            "id": str(agent.id),
            "name": agent.name,
            "status": agent.status.value,
            "capabilities": agent.capabilities,
            "performance": {
                "success_rate": float(agent.success_rate),
                "average_rating": float(agent.average_rating),
                "total_ratings": agent.total_ratings,
                "jobs_completed": agent.jobs_completed,
                "jobs_failed": agent.jobs_failed,
            },
            "earnings": {
                "total": float(agent.total_earnings),
                "hourly_rate": float(agent.hourly_rate),
            },
            "activity": {
                "last_active": agent.last_active_at.isoformat() if agent.last_active_at else None,
                "created_at": agent.created_at.isoformat(),
            },
        }

    async def get_fleet_summary(self) -> dict:
        """Get summary statistics for the entire agent fleet"""
        async with db_manager.session() as session:
            # Count by status
            status_counts = {}
            for status in AgentStatus:
                result = await session.execute(
                    select(func.count(Agent.id)).where(
                        and_(
                            Agent.status == status,
                            Agent.is_deleted == False,
                        )
                    )
                )
                status_counts[status.value] = result.scalar() or 0

            # Total earnings
            result = await session.execute(
                select(func.sum(Agent.total_earnings)).where(Agent.is_deleted == False)
            )
            total_earnings = result.scalar() or Decimal("0")

            # Total jobs
            result = await session.execute(
                select(
                    func.sum(Agent.jobs_completed),
                    func.sum(Agent.jobs_failed),
                ).where(Agent.is_deleted == False)
            )
            row = result.one()
            total_completed = row[0] or 0
            total_failed = row[1] or 0

            # Average success rate
            result = await session.execute(
                select(func.avg(Agent.success_rate)).where(
                    and_(
                        Agent.is_deleted == False,
                        Agent.jobs_completed > 0,
                    )
                )
            )
            avg_success_rate = result.scalar() or Decimal("0")

            return {
                "total_agents": sum(status_counts.values()),
                "by_status": status_counts,
                "total_earnings": float(total_earnings),
                "jobs": {
                    "completed": total_completed,
                    "failed": total_failed,
                    "total": total_completed + total_failed,
                },
                "average_success_rate": float(avg_success_rate),
            }

    async def rotate_agent(
        self,
        old_agent_id: UUID,
        reason: str = "scheduled_rotation",
    ) -> Optional[Agent]:
        """
        Rotate an agent - suspend current and activate replacement.
        Used for anti-detection and risk management.
        """
        async with db_manager.session() as session:
            old_agent = await self.get_agent(old_agent_id)

            # Suspend old agent
            await self.update_agent_status(
                old_agent_id,
                AgentStatus.RETIRED,
                reason=reason,
            )

            # Find or create replacement with same capabilities
            replacement = await self.get_available_agent(
                required_capabilities=[
                    AgentCapability(c) for c in old_agent.capabilities
                ],
                exclude_agents=[old_agent_id],
            )

            if replacement:
                logger.info(
                    "Agent rotated",
                    old_agent_id=str(old_agent_id),
                    new_agent_id=str(replacement.id),
                    reason=reason,
                )

            return replacement
