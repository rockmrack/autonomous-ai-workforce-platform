"""
Safety Guardian
Central safety orchestrator for platform operations
"""

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import select, and_

from src.core.database import db_manager
from src.core.events import event_bus
from src.core.cache import cache_manager
from src.safety.models import (
    SafetyIncident,
    BehaviorProfile,
    ContentFilter,
    RiskLevel,
    ViolationType,
    ActionType,
)
from src.safety.rate_limiter import rate_limiter
from src.safety.humanizer import content_humanizer

logger = structlog.get_logger(__name__)


class SafetyGuardian:
    """
    Central safety system that monitors and protects platform operations.

    Features:
    - Real-time risk assessment
    - Behavioral pattern enforcement
    - Content policy compliance
    - Platform TOS adherence
    - Automatic incident response
    """

    def __init__(self):
        self.risk_thresholds = {
            RiskLevel.LOW: 0.3,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.7,
            RiskLevel.CRITICAL: 0.9,
        }

        # Prohibited content patterns
        self.prohibited_patterns = [
            r'\b(guarantee|guaranteed)\s+(income|earnings|money)\b',
            r'\b(get\s+rich|make\s+money)\s+(fast|quick)\b',
            r'\b(100%|totally)\s+(automated|hands-off)\b',
            r'\bno\s+(experience|skills?)\s+(needed|required)\b',
        ]

    async def assess_risk(
        self,
        action: str,
        context: dict,
        agent_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """
        Assess risk level for a proposed action.

        Returns risk assessment with recommended actions.
        """
        risk_factors = []
        risk_score = 0.0

        # Check rate limits
        if "platform" in context:
            wait_time = await rate_limiter.get_wait_time(
                context["platform"],
                action,
                str(agent_id) if agent_id else None,
            )
            if wait_time > 0:
                risk_factors.append({
                    "factor": "rate_limit",
                    "score": 0.3,
                    "message": f"Rate limit active, wait {wait_time:.0f}s",
                })
                risk_score += 0.3

        # Check behavioral profile
        if agent_id:
            profile = await self._get_behavior_profile(agent_id)
            if profile:
                behavior_risk = self._assess_behavior_risk(profile, action, context)
                if behavior_risk > 0:
                    risk_factors.append({
                        "factor": "behavior_pattern",
                        "score": behavior_risk,
                        "message": "Action deviates from normal pattern",
                    })
                    risk_score += behavior_risk

        # Check content if provided
        if "content" in context:
            content_risk = await self._assess_content_risk(context["content"])
            if content_risk > 0:
                risk_factors.append({
                    "factor": "content_policy",
                    "score": content_risk,
                    "message": "Content may violate policies",
                })
                risk_score += content_risk

        # Check recent incidents
        if agent_id:
            incident_risk = await self._check_recent_incidents(agent_id)
            if incident_risk > 0:
                risk_factors.append({
                    "factor": "incident_history",
                    "score": incident_risk,
                    "message": "Recent safety incidents detected",
                })
                risk_score += incident_risk

        # Determine risk level
        risk_level = self._calculate_risk_level(risk_score)

        # Determine recommended action
        recommended_action = self._get_recommended_action(risk_level)

        return {
            "risk_level": risk_level.value,
            "risk_score": min(1.0, risk_score),
            "factors": risk_factors,
            "recommended_action": recommended_action,
            "can_proceed": risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM],
            "requires_review": risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL],
        }

    async def validate_content(
        self,
        content: str,
        content_type: str = "text",
        platform: Optional[str] = None,
    ) -> dict:
        """
        Validate content against safety policies.
        """
        violations = []

        # Check against prohibited patterns
        for pattern in self.prohibited_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                violations.append({
                    "type": "prohibited_pattern",
                    "pattern": pattern,
                    "severity": RiskLevel.HIGH.value,
                })

        # Check against custom filters
        filters = await self._get_content_filters(content_type, platform)
        for filter_def in filters:
            if self._check_filter(content, filter_def):
                violations.append({
                    "type": "filter_match",
                    "filter_name": filter_def.name,
                    "severity": filter_def.severity.value,
                    "action": filter_def.action,
                })

        # Check for potential PII
        pii_check = self._check_pii(content)
        if pii_check:
            violations.append({
                "type": "pii_detected",
                "details": pii_check,
                "severity": RiskLevel.MEDIUM.value,
            })

        is_safe = len(violations) == 0
        risk_level = self._max_severity(violations) if violations else RiskLevel.LOW

        return {
            "is_safe": is_safe,
            "risk_level": risk_level.value,
            "violations": violations,
            "can_proceed": is_safe or risk_level == RiskLevel.LOW,
        }

    async def humanize_content(
        self,
        content: str,
        agent_id: Optional[uuid.UUID] = None,
        style: str = "casual_professional",
    ) -> str:
        """
        Make content appear more human-written.
        """
        # Get agent's personality traits if available
        traits = None
        if agent_id:
            async with db_manager.session() as session:
                from src.agents.models import Agent
                result = await session.execute(
                    select(Agent).where(Agent.id == agent_id)
                )
                agent = result.scalar_one_or_none()
                if agent and agent.metadata_json:
                    traits = agent.metadata_json.get("personality_traits")

        return await content_humanizer.humanize(
            content=content,
            style=style,
            personality_traits=traits,
        )

    async def enforce_behavior_pattern(
        self,
        agent_id: uuid.UUID,
        action: str,
    ) -> dict:
        """
        Ensure action follows human-like behavior patterns.
        Returns timing recommendations.
        """
        profile = await self._get_behavior_profile(agent_id)

        if not profile:
            # Create default profile
            profile = await self._create_default_profile(agent_id)

        now = datetime.utcnow()
        hour = now.hour

        # Check if within active hours
        is_active_hours = profile.active_hours_start <= hour < profile.active_hours_end

        # Calculate recommended delay
        base_delay = profile.min_response_delay_seconds

        if not is_active_hours:
            # Outside active hours - much longer delay or postpone
            delay = (profile.active_hours_start - hour) * 3600
            if delay < 0:
                delay += 24 * 3600
            return {
                "should_proceed": False,
                "delay_seconds": delay,
                "reason": "Outside active hours",
                "resume_at": (now + timedelta(seconds=delay)).isoformat(),
            }

        # Random human-like delay
        import random
        delay = random.uniform(
            profile.min_response_delay_seconds,
            profile.max_response_delay_seconds,
        )

        # Occasional break
        if random.random() < profile.coffee_break_probability:
            delay += random.uniform(300, 900)  # 5-15 minute break

        return {
            "should_proceed": True,
            "delay_seconds": delay,
            "reason": "Within active hours with human-like delay",
            "typing_speed_wpm": profile.typing_speed_wpm,
        }

    async def record_incident(
        self,
        violation_type: ViolationType,
        risk_level: RiskLevel,
        description: str,
        agent_id: Optional[uuid.UUID] = None,
        platform: Optional[str] = None,
        context: Optional[dict] = None,
        action_taken: Optional[ActionType] = None,
    ) -> SafetyIncident:
        """
        Record a safety incident.
        """
        async with db_manager.session() as session:
            incident = SafetyIncident(
                agent_id=agent_id,
                platform=platform,
                violation_type=violation_type,
                risk_level=risk_level,
                description=description,
                detected_by="safety_guardian",
                context_data=context or {},
                action_taken=action_taken,
            )
            session.add(incident)
            await session.commit()

            logger.warning(
                "Safety incident recorded",
                incident_id=str(incident.id),
                violation_type=violation_type.value,
                risk_level=risk_level.value,
            )

            # Emit event
            await event_bus.emit(
                "safety.incident_recorded",
                {
                    "incident_id": str(incident.id),
                    "violation_type": violation_type.value,
                    "risk_level": risk_level.value,
                    "agent_id": str(agent_id) if agent_id else None,
                },
            )

            return incident

    async def get_agent_safety_status(
        self,
        agent_id: uuid.UUID,
    ) -> dict:
        """
        Get comprehensive safety status for an agent.
        """
        async with db_manager.session() as session:
            # Get recent incidents
            result = await session.execute(
                select(SafetyIncident)
                .where(
                    and_(
                        SafetyIncident.agent_id == agent_id,
                        SafetyIncident.created_at > datetime.utcnow() - timedelta(days=7),
                    )
                )
                .order_by(SafetyIncident.created_at.desc())
            )
            incidents = result.scalars().all()

            # Get behavior profile
            profile = await self._get_behavior_profile(agent_id)

            # Calculate safety score
            incident_count = len(incidents)
            unresolved = sum(1 for i in incidents if not i.is_resolved)
            critical_count = sum(1 for i in incidents if i.risk_level == RiskLevel.CRITICAL)

            safety_score = 100
            safety_score -= incident_count * 5
            safety_score -= unresolved * 10
            safety_score -= critical_count * 20
            safety_score = max(0, safety_score)

            return {
                "agent_id": str(agent_id),
                "safety_score": safety_score,
                "total_incidents_7d": incident_count,
                "unresolved_incidents": unresolved,
                "critical_incidents": critical_count,
                "has_behavior_profile": profile is not None,
                "is_safe_to_operate": safety_score >= 60,
                "recent_incidents": [
                    {
                        "id": str(i.id),
                        "type": i.violation_type.value,
                        "risk_level": i.risk_level.value,
                        "resolved": i.is_resolved,
                        "created_at": i.created_at.isoformat(),
                    }
                    for i in incidents[:5]
                ],
            }

    async def _get_behavior_profile(
        self,
        agent_id: uuid.UUID,
    ) -> Optional[BehaviorProfile]:
        """Get agent's behavior profile"""
        cache_key = f"behavior_profile:{agent_id}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return cached

        async with db_manager.session() as session:
            result = await session.execute(
                select(BehaviorProfile)
                .where(BehaviorProfile.agent_id == agent_id)
            )
            profile = result.scalar_one_or_none()

            if profile:
                await cache_manager.set(cache_key, profile, ttl=3600)

            return profile

    async def _create_default_profile(
        self,
        agent_id: uuid.UUID,
    ) -> BehaviorProfile:
        """Create default behavior profile"""
        import random

        async with db_manager.session() as session:
            profile = BehaviorProfile(
                agent_id=agent_id,
                active_hours_start=random.randint(7, 10),
                active_hours_end=random.randint(17, 21),
                avg_tasks_per_day=random.uniform(2, 5),
                min_response_delay_seconds=random.randint(20, 60),
                max_response_delay_seconds=random.randint(180, 600),
                typing_speed_wpm=random.randint(40, 80),
            )
            session.add(profile)
            await session.commit()
            return profile

    def _assess_behavior_risk(
        self,
        profile: BehaviorProfile,
        action: str,
        context: dict,
    ) -> float:
        """Assess risk based on behavior patterns"""
        risk = 0.0

        now = datetime.utcnow()
        hour = now.hour

        # Check active hours
        if not (profile.active_hours_start <= hour < profile.active_hours_end):
            risk += 0.2

        # Check action frequency (would need more context in real implementation)
        # For now, return minimal risk if within profile parameters
        return risk

    async def _assess_content_risk(self, content: str) -> float:
        """Assess risk level of content"""
        risk = 0.0

        # Check prohibited patterns
        for pattern in self.prohibited_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                risk += 0.3

        # Check length (very short or very long content is suspicious)
        if len(content) < 50:
            risk += 0.1
        elif len(content) > 10000:
            risk += 0.1

        return min(1.0, risk)

    async def _check_recent_incidents(
        self,
        agent_id: uuid.UUID,
    ) -> float:
        """Check for recent safety incidents"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(SafetyIncident)
                .where(
                    and_(
                        SafetyIncident.agent_id == agent_id,
                        SafetyIncident.created_at > datetime.utcnow() - timedelta(hours=24),
                        SafetyIncident.is_resolved == False,
                    )
                )
            )
            incidents = result.scalars().all()

            if not incidents:
                return 0.0

            # Calculate risk based on incident severity
            risk = 0.0
            for incident in incidents:
                if incident.risk_level == RiskLevel.CRITICAL:
                    risk += 0.4
                elif incident.risk_level == RiskLevel.HIGH:
                    risk += 0.2
                elif incident.risk_level == RiskLevel.MEDIUM:
                    risk += 0.1
                else:
                    risk += 0.05

            return min(1.0, risk)

    def _calculate_risk_level(self, score: float) -> RiskLevel:
        """Calculate risk level from score"""
        if score >= self.risk_thresholds[RiskLevel.CRITICAL]:
            return RiskLevel.CRITICAL
        elif score >= self.risk_thresholds[RiskLevel.HIGH]:
            return RiskLevel.HIGH
        elif score >= self.risk_thresholds[RiskLevel.MEDIUM]:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _get_recommended_action(self, risk_level: RiskLevel) -> str:
        """Get recommended action based on risk level"""
        actions = {
            RiskLevel.LOW: "proceed",
            RiskLevel.MEDIUM: "proceed_with_caution",
            RiskLevel.HIGH: "review_required",
            RiskLevel.CRITICAL: "halt_and_investigate",
        }
        return actions[risk_level]

    async def _get_content_filters(
        self,
        content_type: str,
        platform: Optional[str],
    ) -> list[ContentFilter]:
        """Get applicable content filters"""
        async with db_manager.session() as session:
            query = select(ContentFilter).where(ContentFilter.is_active == True)

            result = await session.execute(query)
            filters = result.scalars().all()

            # Filter by content type and platform
            applicable = []
            for f in filters:
                type_match = not f.content_types or content_type in f.content_types
                platform_match = not f.platforms or platform in f.platforms
                if type_match and platform_match:
                    applicable.append(f)

            return applicable

    def _check_filter(self, content: str, filter_def: ContentFilter) -> bool:
        """Check if content matches a filter"""
        for pattern in filter_def.patterns:
            if pattern["type"] == "regex":
                if re.search(pattern["pattern"], content, re.IGNORECASE):
                    return True
            elif pattern["type"] == "keyword":
                if pattern["word"].lower() in content.lower():
                    return True
        return False

    def _check_pii(self, content: str) -> Optional[dict]:
        """Check for potential PII in content"""
        findings = {}

        # Email patterns
        emails = re.findall(r'\b[\w.-]+@[\w.-]+\.\w+\b', content)
        if emails:
            findings["emails"] = len(emails)

        # Phone patterns
        phones = re.findall(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', content)
        if phones:
            findings["phones"] = len(phones)

        # SSN patterns
        ssns = re.findall(r'\b\d{3}-\d{2}-\d{4}\b', content)
        if ssns:
            findings["ssns"] = len(ssns)

        return findings if findings else None

    def _max_severity(self, violations: list[dict]) -> RiskLevel:
        """Get maximum severity from violations"""
        severities = [v.get("severity", "low") for v in violations]
        severity_order = ["low", "medium", "high", "critical"]

        max_severity = "low"
        for s in severities:
            if severity_order.index(s) > severity_order.index(max_severity):
                max_severity = s

        return RiskLevel(max_severity)


# Singleton instance
safety_guardian = SafetyGuardian()
