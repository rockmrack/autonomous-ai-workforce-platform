"""
Bid Calculator - Optimizes bid amounts for maximum win rate and profit
"""

from decimal import Decimal
from typing import Optional

import structlog

from src.agents.models import Agent
from src.discovery.models import DiscoveredJob

logger = structlog.get_logger(__name__)


class BidCalculator:
    """
    Calculates optimal bid amounts based on multiple factors.

    Features:
    - Competition-aware pricing
    - Agent performance-based adjustments
    - Market rate consideration
    - Profit margin optimization
    - Platform fee accounting
    """

    # Platform fee rates (approximate)
    PLATFORM_FEES = {
        "upwork": 0.10,  # 10% (simplified, actual is tiered)
        "fiverr": 0.20,  # 20%
        "freelancer": 0.10,
        "peopleperhour": 0.15,
        "reddit": 0.0,  # No fees
        "default": 0.15,
    }

    # Minimum hourly equivalent
    MIN_HOURLY_RATE = Decimal("15.00")
    TARGET_HOURLY_RATE = Decimal("35.00")
    MAX_HOURLY_RATE = Decimal("100.00")

    # Minimum profit margin
    MIN_PROFIT_MARGIN = Decimal("0.30")  # 30%

    def calculate_optimal_bid(
        self,
        job: DiscoveredJob,
        agent: Agent,
        target_win_probability: float = 0.3,
    ) -> dict:
        """
        Calculate the optimal bid for a job.

        Args:
            job: The job to bid on
            agent: The agent submitting the bid
            target_win_probability: Target probability of winning (0-1)

        Returns:
            Dict with bid_amount, bid_type, duration, and analysis
        """
        # Get job budget info
        budget_min = job.budget_min or Decimal("0")
        budget_max = job.budget_max or Decimal("1000")
        budget_type = job.budget_type or "fixed"

        # Calculate base bid
        base_bid = self._calculate_base_bid(job, agent)

        # Adjust for competition
        competition_adjusted = self._adjust_for_competition(
            base_bid,
            job.applicant_count or 0,
            target_win_probability,
        )

        # Adjust for agent performance
        performance_adjusted = self._adjust_for_performance(
            competition_adjusted,
            agent,
        )

        # Ensure within budget range
        final_bid = self._constrain_to_budget(
            performance_adjusted,
            budget_min,
            budget_max,
        )

        # Ensure minimum profit
        final_bid = self._ensure_minimum_profit(
            final_bid,
            job,
            agent,
        )

        # Estimate duration
        duration = self._estimate_duration(job, final_bid)

        # Analysis breakdown
        analysis = {
            "base_bid": float(base_bid),
            "competition_factor": float(competition_adjusted / base_bid) if base_bid else 1,
            "performance_factor": float(performance_adjusted / competition_adjusted) if competition_adjusted else 1,
            "budget_range": f"${budget_min} - ${budget_max}",
            "applicant_count": job.applicant_count,
            "agent_success_rate": float(agent.success_rate),
            "estimated_profit_margin": self._calculate_profit_margin(final_bid, job),
        }

        logger.info(
            "Bid calculated",
            job_id=str(job.id),
            bid_amount=float(final_bid),
            bid_type=budget_type,
            analysis=analysis,
        )

        return {
            "bid_amount": final_bid,
            "bid_type": budget_type,
            "duration": duration,
            "analysis": analysis,
        }

    def _calculate_base_bid(self, job: DiscoveredJob, agent: Agent) -> Decimal:
        """Calculate base bid from job requirements and agent rate"""
        budget_max = job.budget_max or Decimal("500")
        budget_min = job.budget_min or Decimal("50")

        if job.budget_type == "hourly":
            # For hourly, bid based on agent's rate
            hourly_rate = agent.hourly_rate or self.TARGET_HOURLY_RATE
            return min(max(hourly_rate, self.MIN_HOURLY_RATE), budget_max)

        # For fixed price, start with budget midpoint
        midpoint = (budget_min + budget_max) / 2

        # Adjust based on estimated complexity
        complexity_factor = self._estimate_complexity_factor(job)
        adjusted = midpoint * Decimal(str(complexity_factor))

        return adjusted

    def _estimate_complexity_factor(self, job: DiscoveredJob) -> float:
        """Estimate complexity factor based on job details"""
        factor = 1.0

        # More skills = more complex
        skills_count = len(job.skills_required or [])
        if skills_count > 5:
            factor += 0.2
        elif skills_count > 3:
            factor += 0.1

        # Long description = more complex
        desc_length = len(job.description or "")
        if desc_length > 2000:
            factor += 0.15
        elif desc_length > 1000:
            factor += 0.05

        # Experience level requirements
        if job.experience_level:
            level = job.experience_level.lower()
            if "expert" in level or "senior" in level:
                factor += 0.2
            elif "intermediate" in level:
                factor += 0.1

        return min(factor, 1.5)  # Cap at 1.5x

    def _adjust_for_competition(
        self,
        base_bid: Decimal,
        applicant_count: int,
        target_win_prob: float,
    ) -> Decimal:
        """Adjust bid based on competition level"""
        if applicant_count <= 5:
            # Low competition - can bid higher
            return base_bid * Decimal("1.1")
        elif applicant_count <= 10:
            # Medium competition - bid at base
            return base_bid
        elif applicant_count <= 20:
            # High competition - bid lower
            return base_bid * Decimal("0.9")
        else:
            # Very high competition - bid aggressively low
            return base_bid * Decimal("0.8")

    def _adjust_for_performance(
        self,
        bid: Decimal,
        agent: Agent,
    ) -> Decimal:
        """Adjust bid based on agent's track record"""
        success_rate = float(agent.success_rate)

        if success_rate >= 0.9:
            # High performer can command premium
            return bid * Decimal("1.15")
        elif success_rate >= 0.7:
            # Good performer
            return bid * Decimal("1.05")
        elif success_rate >= 0.5:
            # Average performer
            return bid
        else:
            # New or struggling - bid lower to win
            return bid * Decimal("0.9")

    def _constrain_to_budget(
        self,
        bid: Decimal,
        budget_min: Decimal,
        budget_max: Decimal,
    ) -> Decimal:
        """Ensure bid is within client's budget"""
        # Never go below budget minimum
        if bid < budget_min:
            bid = budget_min

        # Never exceed budget maximum
        if bid > budget_max:
            bid = budget_max

        return bid

    def _ensure_minimum_profit(
        self,
        bid: Decimal,
        job: DiscoveredJob,
        agent: Agent,
    ) -> Decimal:
        """Ensure bid provides minimum acceptable profit"""
        platform_fee_rate = Decimal(str(
            self.PLATFORM_FEES.get(job.platform, self.PLATFORM_FEES["default"])
        ))

        # Estimate costs
        estimated_hours = float(job.estimated_hours or 4)
        api_cost_estimate = Decimal(str(estimated_hours * 0.10))  # ~$0.10/hour API cost

        # Calculate minimum bid for target margin
        platform_fee = bid * platform_fee_rate
        net_after_fees = bid - platform_fee - api_cost_estimate

        # If profit margin too low, increase bid
        min_acceptable = (api_cost_estimate + Decimal("10")) / (1 - platform_fee_rate - self.MIN_PROFIT_MARGIN)

        if bid < min_acceptable:
            # Only adjust up to budget max
            if job.budget_max:
                bid = min(min_acceptable, job.budget_max)
            else:
                bid = min_acceptable

        return bid

    def _calculate_profit_margin(self, bid: Decimal, job: DiscoveredJob) -> float:
        """Calculate expected profit margin"""
        platform_fee_rate = self.PLATFORM_FEES.get(job.platform, self.PLATFORM_FEES["default"])
        estimated_hours = float(job.estimated_hours or 4)
        api_cost_estimate = estimated_hours * 0.10

        platform_fee = float(bid) * platform_fee_rate
        net = float(bid) - platform_fee - api_cost_estimate

        return net / float(bid) if bid else 0

    def _estimate_duration(self, job: DiscoveredJob, bid: Decimal) -> str:
        """Estimate realistic duration for the job"""
        if job.estimated_duration:
            return job.estimated_duration

        if job.estimated_hours:
            hours = float(job.estimated_hours)
            if hours <= 8:
                return "1-2 days"
            elif hours <= 24:
                return "3-5 days"
            elif hours <= 80:
                return "1-2 weeks"
            else:
                return "2-4 weeks"

        # Estimate from budget
        if job.budget_type == "fixed":
            budget = float(job.budget_max or bid)
            if budget < 100:
                return "1-2 days"
            elif budget < 300:
                return "3-5 days"
            elif budget < 1000:
                return "1-2 weeks"
            else:
                return "2-4 weeks"

        return "To be discussed"

    def calculate_hourly_equivalent(
        self,
        bid: Decimal,
        estimated_hours: float,
    ) -> Decimal:
        """Calculate hourly equivalent of a fixed bid"""
        if estimated_hours <= 0:
            return Decimal("0")
        return bid / Decimal(str(estimated_hours))

    def get_market_rate_estimate(
        self,
        job: DiscoveredJob,
    ) -> dict:
        """Get estimated market rate for a job type"""
        # This would ideally use historical data
        # For now, use heuristic-based estimates

        category = (job.category or "").lower()

        rate_estimates = {
            "writing": {"min": 20, "typical": 35, "max": 75},
            "web development": {"min": 30, "typical": 50, "max": 100},
            "data entry": {"min": 10, "typical": 18, "max": 30},
            "research": {"min": 15, "typical": 30, "max": 60},
            "design": {"min": 25, "typical": 45, "max": 90},
            "default": {"min": 20, "typical": 35, "max": 70},
        }

        for key in rate_estimates:
            if key in category:
                return rate_estimates[key]

        return rate_estimates["default"]
