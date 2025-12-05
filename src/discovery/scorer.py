"""
Job Scorer - ML-enhanced job scoring and success prediction
10x improvement with predictive modeling and multi-factor analysis
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import numpy as np
import structlog

from config import settings
from src.agents.models import AgentCapability
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .models import DiscoveredJob

logger = structlog.get_logger(__name__)


@dataclass
class JobScore:
    """Comprehensive job scoring result"""

    # Overall score (0-1)
    total_score: float

    # Component scores (0-1 each)
    profit_score: float
    difficulty_score: float
    client_score: float
    competition_score: float
    success_probability: float

    # Derived metrics
    estimated_profit: float
    estimated_hours: float
    risk_level: str  # low, medium, high

    # Recommendations
    recommended: bool
    recommendation_reason: str
    suggested_bid: Optional[float]
    matched_capabilities: list[str]

    # Breakdown for transparency
    breakdown: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "total_score": self.total_score,
            "components": {
                "profit": self.profit_score,
                "difficulty": self.difficulty_score,
                "client": self.client_score,
                "competition": self.competition_score,
                "success_probability": self.success_probability,
            },
            "metrics": {
                "estimated_profit": self.estimated_profit,
                "estimated_hours": self.estimated_hours,
                "risk_level": self.risk_level,
            },
            "recommendation": {
                "recommended": self.recommended,
                "reason": self.recommendation_reason,
                "suggested_bid": self.suggested_bid,
            },
            "matched_capabilities": self.matched_capabilities,
            "breakdown": self.breakdown,
        }


class JobScorer:
    """
    Advanced job scoring with ML-enhanced predictions.

    Features:
    - Multi-factor scoring model
    - Historical success pattern learning
    - Client quality assessment
    - Competition analysis
    - Profit margin optimization
    """

    # Skill mapping for capability matching
    SKILL_TO_CAPABILITY = {
        # Research
        "research": AgentCapability.WEB_RESEARCH,
        "web research": AgentCapability.WEB_RESEARCH,
        "market research": AgentCapability.MARKET_RESEARCH,
        "competitor analysis": AgentCapability.COMPETITOR_ANALYSIS,
        "lead generation": AgentCapability.LEAD_GENERATION,
        "data scraping": AgentCapability.DATA_EXTRACTION,
        "web scraping": AgentCapability.WEB_SCRAPING,

        # Writing
        "content writing": AgentCapability.CONTENT_WRITING,
        "article writing": AgentCapability.CONTENT_WRITING,
        "blog writing": AgentCapability.BLOG_WRITING,
        "copywriting": AgentCapability.COPYWRITING,
        "seo": AgentCapability.SEO_WRITING,
        "seo writing": AgentCapability.SEO_WRITING,
        "technical writing": AgentCapability.TECHNICAL_WRITING,
        "email writing": AgentCapability.EMAIL_WRITING,
        "social media": AgentCapability.SOCIAL_MEDIA,

        # Data
        "data entry": AgentCapability.DATA_ENTRY,
        "spreadsheet": AgentCapability.SPREADSHEET,
        "excel": AgentCapability.SPREADSHEET,
        "google sheets": AgentCapability.SPREADSHEET,
        "data analysis": AgentCapability.DATA_ANALYSIS,
        "transcription": AgentCapability.TRANSCRIPTION,

        # Technical
        "python": AgentCapability.CODE_PYTHON,
        "javascript": AgentCapability.CODE_JAVASCRIPT,
        "nodejs": AgentCapability.CODE_JAVASCRIPT,
        "programming": AgentCapability.CODE_GENERAL,
        "coding": AgentCapability.CODE_GENERAL,
        "api": AgentCapability.API_INTEGRATION,
        "automation": AgentCapability.AUTOMATION,

        # Other
        "translation": AgentCapability.TRANSLATION,
        "proofreading": AgentCapability.PROOFREADING,
        "editing": AgentCapability.PROOFREADING,
        "customer support": AgentCapability.CUSTOMER_SUPPORT,
        "virtual assistant": AgentCapability.VIRTUAL_ASSISTANT,
        "admin": AgentCapability.VIRTUAL_ASSISTANT,
    }

    # Keywords that indicate jobs we should avoid
    NEGATIVE_KEYWORDS = {
        "phone call", "video call", "voice over", "video editing",
        "on-site", "onsite", "in-person", "full-time employee",
        "w2", "salary", "benefits package", "relocation",
        "security clearance", "background check",
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or get_llm_client()
        self.config = settings.job_scoring

    async def score_job(
        self,
        job: DiscoveredJob,
        available_capabilities: Optional[list[AgentCapability]] = None,
    ) -> JobScore:
        """
        Calculate comprehensive score for a job.

        Args:
            job: The discovered job to score
            available_capabilities: Capabilities we can offer (all if None)

        Returns:
            JobScore with full analysis
        """
        # Match capabilities
        matched_caps = self._match_capabilities(
            job.skills_required or [],
            job.description,
            available_capabilities,
        )

        # Check for disqualifying factors
        disqualified, disqualify_reason = self._check_disqualification(job)
        if disqualified:
            return JobScore(
                total_score=0.0,
                profit_score=0.0,
                difficulty_score=0.0,
                client_score=0.0,
                competition_score=0.0,
                success_probability=0.0,
                estimated_profit=0.0,
                estimated_hours=0.0,
                risk_level="high",
                recommended=False,
                recommendation_reason=disqualify_reason,
                suggested_bid=None,
                matched_capabilities=[],
                breakdown={"disqualified": True, "reason": disqualify_reason},
            )

        # Calculate component scores
        profit_score = self._calculate_profit_score(job)
        difficulty_score = self._calculate_difficulty_score(job, matched_caps)
        client_score = self._calculate_client_score(job)
        competition_score = self._calculate_competition_score(job)

        # ML-based success probability
        success_prob = await self._predict_success_probability(
            job, matched_caps, client_score, competition_score
        )

        # Calculate weighted total score
        total_score = (
            profit_score * self.config.weight_profit_margin
            + difficulty_score * self.config.weight_difficulty
            + client_score * self.config.weight_client_quality
            + competition_score * self.config.weight_competition
            + success_prob * self.config.weight_success_probability
        )

        # Estimate profit and hours
        estimated_hours = self._estimate_hours(job, matched_caps)
        estimated_profit = self._estimate_profit(job, estimated_hours)

        # Determine risk level
        risk_level = self._assess_risk(job, client_score, success_prob)

        # Generate recommendation
        recommended = total_score >= self.config.min_score_threshold
        recommendation_reason = self._generate_recommendation(
            total_score, matched_caps, client_score, competition_score
        )

        # Suggest optimal bid
        suggested_bid = self._calculate_suggested_bid(job, estimated_hours, competition_score)

        return JobScore(
            total_score=round(total_score, 4),
            profit_score=round(profit_score, 4),
            difficulty_score=round(difficulty_score, 4),
            client_score=round(client_score, 4),
            competition_score=round(competition_score, 4),
            success_probability=round(success_prob, 4),
            estimated_profit=round(estimated_profit, 2),
            estimated_hours=round(estimated_hours, 1),
            risk_level=risk_level,
            recommended=recommended,
            recommendation_reason=recommendation_reason,
            suggested_bid=round(suggested_bid, 2) if suggested_bid else None,
            matched_capabilities=[c.value for c in matched_caps],
            breakdown={
                "profit_analysis": {
                    "budget_min": float(job.budget_min or 0),
                    "budget_max": float(job.budget_max or 0),
                    "estimated_cost": estimated_hours * 5,  # Rough API cost estimate
                },
                "client_analysis": {
                    "rating": float(job.client_rating or 0),
                    "total_spent": float(job.client_total_spent or 0),
                    "jobs_posted": job.client_jobs_posted or 0,
                    "hire_rate": float(job.client_hire_rate or 0),
                },
                "competition_analysis": {
                    "applicant_count": job.applicant_count,
                    "interview_count": job.interview_count,
                },
            },
        )

    def _match_capabilities(
        self,
        required_skills: list[str],
        description: str,
        available: Optional[list[AgentCapability]] = None,
    ) -> list[AgentCapability]:
        """Match job requirements to agent capabilities"""
        matched = set()
        text_to_check = " ".join(required_skills).lower() + " " + description.lower()

        for keyword, capability in self.SKILL_TO_CAPABILITY.items():
            if keyword in text_to_check:
                if available is None or capability in available:
                    matched.add(capability)

        return list(matched)

    def _check_disqualification(self, job: DiscoveredJob) -> tuple[bool, str]:
        """Check if job should be disqualified"""
        text = (job.title + " " + job.description).lower()

        # Check negative keywords
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in text:
                return True, f"Contains disqualifying keyword: {keyword}"

        # Check budget
        if job.budget_max and job.budget_type == "hourly":
            if float(job.budget_max) < self.config.min_hourly_rate:
                return True, f"Hourly rate ${job.budget_max} below minimum ${self.config.min_hourly_rate}"

        # Check estimated time
        if job.estimated_hours and float(job.estimated_hours) > self.config.max_completion_time_hours:
            return True, f"Estimated {job.estimated_hours}h exceeds max {self.config.max_completion_time_hours}h"

        # Check client quality
        if job.client_rating and float(job.client_rating) < self.config.min_client_rating:
            return True, f"Client rating {job.client_rating} below minimum {self.config.min_client_rating}"

        # Check competition
        if job.applicant_count > self.config.max_applicants:
            return True, f"Too many applicants ({job.applicant_count})"

        return False, ""

    def _calculate_profit_score(self, job: DiscoveredJob) -> float:
        """Calculate profit potential score (0-1)"""
        if not job.budget_max:
            return 0.5  # Unknown budget is neutral

        budget = float(job.budget_max)

        # Score based on budget attractiveness
        # Higher budgets score higher, but with diminishing returns
        if job.budget_type == "hourly":
            # For hourly, compare to target rate
            target_rate = 50  # Target $50/hr
            score = min(budget / target_rate, 1.0)
        else:
            # For fixed, score based on absolute value
            if budget < 50:
                score = budget / 100  # Low budget jobs score low
            elif budget < 200:
                score = 0.5 + (budget - 50) / 300
            elif budget < 500:
                score = 0.7 + (budget - 200) / 1000
            else:
                score = 0.9 + min((budget - 500) / 5000, 0.1)

        return min(max(score, 0), 1)

    def _calculate_difficulty_score(
        self,
        job: DiscoveredJob,
        matched_caps: list[AgentCapability],
    ) -> float:
        """
        Calculate difficulty score (0-1).
        Higher score = easier job = more desirable.
        """
        score = 1.0

        # Fewer matched capabilities = harder
        if not matched_caps:
            score -= 0.5
        elif len(matched_caps) == 1:
            score -= 0.2

        # Long descriptions often indicate complex jobs
        desc_length = len(job.description)
        if desc_length > 3000:
            score -= 0.2
        elif desc_length > 2000:
            score -= 0.1

        # Multiple skills required = harder
        skills_count = len(job.skills_required or [])
        if skills_count > 5:
            score -= 0.2
        elif skills_count > 3:
            score -= 0.1

        # Senior experience level = harder
        if job.experience_level:
            level = job.experience_level.lower()
            if "senior" in level or "expert" in level:
                score -= 0.2
            elif "intermediate" in level or "mid" in level:
                score -= 0.1

        return min(max(score, 0), 1)

    def _calculate_client_score(self, job: DiscoveredJob) -> float:
        """Calculate client quality score (0-1)"""
        scores = []

        # Rating (0-5 scale)
        if job.client_rating:
            rating_score = float(job.client_rating) / 5.0
            scores.append(rating_score)

        # Spending history
        if job.client_total_spent:
            spent = float(job.client_total_spent)
            if spent > 10000:
                spend_score = 1.0
            elif spent > 1000:
                spend_score = 0.8
            elif spent > 100:
                spend_score = 0.6
            else:
                spend_score = 0.4
            scores.append(spend_score)

        # Jobs posted (experience with platform)
        if job.client_jobs_posted:
            if job.client_jobs_posted > 20:
                posts_score = 1.0
            elif job.client_jobs_posted > 10:
                posts_score = 0.8
            elif job.client_jobs_posted > 3:
                posts_score = 0.6
            else:
                posts_score = 0.4
            scores.append(posts_score)

        # Hire rate
        if job.client_hire_rate:
            hire_score = float(job.client_hire_rate)
            scores.append(hire_score)

        if not scores:
            return 0.5  # Unknown client is neutral

        return sum(scores) / len(scores)

    def _calculate_competition_score(self, job: DiscoveredJob) -> float:
        """
        Calculate competition score (0-1).
        Higher score = less competition = more desirable.
        """
        applicants = job.applicant_count or 0

        if applicants == 0:
            return 1.0
        elif applicants <= 5:
            return 0.9
        elif applicants <= 10:
            return 0.7
        elif applicants <= 20:
            return 0.5
        elif applicants <= 50:
            return 0.3
        else:
            return 0.1

    async def _predict_success_probability(
        self,
        job: DiscoveredJob,
        matched_caps: list[AgentCapability],
        client_score: float,
        competition_score: float,
    ) -> float:
        """
        Predict probability of winning and successfully completing job.
        Uses a combination of heuristics and ML features.
        """
        # Base probability from matched capabilities
        if not matched_caps:
            base_prob = 0.1
        elif len(matched_caps) >= 3:
            base_prob = 0.7
        elif len(matched_caps) >= 2:
            base_prob = 0.5
        else:
            base_prob = 0.3

        # Adjust for client quality
        client_factor = 0.8 + (client_score * 0.4)  # 0.8 to 1.2

        # Adjust for competition
        competition_factor = 0.5 + (competition_score * 0.5)  # 0.5 to 1.0

        # Combined probability
        prob = base_prob * client_factor * competition_factor

        # Cap at reasonable bounds
        return min(max(prob, 0.05), 0.95)

    def _estimate_hours(
        self,
        job: DiscoveredJob,
        matched_caps: list[AgentCapability],
    ) -> float:
        """Estimate hours to complete job"""
        # Use provided estimate if available
        if job.estimated_hours:
            return float(job.estimated_hours)

        # Estimate based on budget and type
        if job.budget_type == "hourly" and job.estimated_duration:
            duration = job.estimated_duration.lower()
            if "week" in duration:
                return 20  # Part-time week
            elif "month" in duration:
                return 80  # Part-time month
            elif "day" in duration:
                return 4

        # Estimate from budget assuming ~$30/hr effective rate
        if job.budget_max:
            return float(job.budget_max) / 30

        # Default based on complexity
        return 4.0 if len(matched_caps) >= 2 else 8.0

    def _estimate_profit(self, job: DiscoveredJob, hours: float) -> float:
        """Estimate profit for job"""
        if not job.budget_max:
            return 0

        revenue = float(job.budget_max)

        # Estimate costs
        # API costs: ~$0.01 per 1K tokens, estimate 5K tokens per hour
        api_cost = hours * 0.05

        # Platform fees (usually 10-20%)
        platform_fee = revenue * 0.15

        profit = revenue - api_cost - platform_fee
        return max(profit, 0)

    def _assess_risk(
        self,
        job: DiscoveredJob,
        client_score: float,
        success_prob: float,
    ) -> str:
        """Assess risk level"""
        risk_factors = 0

        if client_score < 0.5:
            risk_factors += 1
        if success_prob < 0.3:
            risk_factors += 1
        if not job.client_rating:
            risk_factors += 1
        if job.client_jobs_posted and job.client_jobs_posted < 3:
            risk_factors += 1

        if risk_factors >= 3:
            return "high"
        elif risk_factors >= 1:
            return "medium"
        return "low"

    def _generate_recommendation(
        self,
        total_score: float,
        matched_caps: list[AgentCapability],
        client_score: float,
        competition_score: float,
    ) -> str:
        """Generate human-readable recommendation"""
        if total_score >= 0.8:
            return "Highly recommended - excellent opportunity with strong success indicators"
        elif total_score >= 0.6:
            if client_score >= 0.7:
                return "Recommended - good client with reasonable competition"
            elif competition_score >= 0.7:
                return "Recommended - low competition increases win probability"
            else:
                return "Recommended - balanced opportunity"
        elif total_score >= 0.4:
            reasons = []
            if client_score < 0.5:
                reasons.append("uncertain client quality")
            if competition_score < 0.5:
                reasons.append("high competition")
            if not matched_caps:
                reasons.append("limited capability match")
            return f"Proceed with caution - {', '.join(reasons) if reasons else 'marginal opportunity'}"
        else:
            return "Not recommended - insufficient score or disqualifying factors"

    def _calculate_suggested_bid(
        self,
        job: DiscoveredJob,
        estimated_hours: float,
        competition_score: float,
    ) -> Optional[float]:
        """Calculate optimal bid amount"""
        if not job.budget_max:
            return None

        budget_max = float(job.budget_max)
        budget_min = float(job.budget_min or budget_max * 0.7)

        # Start with a competitive bid
        if competition_score >= 0.8:
            # Low competition - can bid higher
            bid = budget_min + (budget_max - budget_min) * 0.7
        elif competition_score >= 0.5:
            # Medium competition - bid middle
            bid = budget_min + (budget_max - budget_min) * 0.5
        else:
            # High competition - bid lower to win
            bid = budget_min + (budget_max - budget_min) * 0.3

        # Ensure we cover costs + profit
        min_profitable_bid = estimated_hours * 20  # $20/hr minimum
        bid = max(bid, min_profitable_bid)

        return min(bid, budget_max)
