"""
Proposal Generator - Creates winning proposals for jobs
Uses LLM with personalization and A/B testing
"""

import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog

from src.agents.models import Agent, AgentPortfolio
from src.discovery.models import DiscoveredJob, Proposal, ProposalStatus
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .bid_calculator import BidCalculator

logger = structlog.get_logger(__name__)


@dataclass
class GeneratedProposal:
    """Generated proposal ready for submission"""

    cover_letter: str
    bid_amount: Decimal
    bid_type: str
    estimated_duration: str
    milestones: list[dict]
    attachments: list[str]
    variant_id: str
    generation_metadata: dict


class ProposalGenerator:
    """
    Generates personalized, winning proposals.

    Features:
    - LLM-powered cover letter generation
    - Personalization based on job and agent
    - A/B testing of proposal styles
    - Portfolio matching
    - Humanization to avoid detection
    """

    # Proposal templates/variants for A/B testing
    VARIANTS = {
        "direct": {
            "style": "direct and professional",
            "structure": "problem-solution-cta",
            "length": "concise",
        },
        "storytelling": {
            "style": "engaging with brief story",
            "structure": "hook-experience-approach-cta",
            "length": "moderate",
        },
        "expertise": {
            "style": "authority-focused",
            "structure": "credentials-understanding-plan-cta",
            "length": "detailed",
        },
        "friendly": {
            "style": "warm and approachable",
            "structure": "greeting-connection-value-cta",
            "length": "moderate",
        },
    }

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        bid_calculator: Optional[BidCalculator] = None,
    ):
        self.llm = llm_client or get_llm_client()
        self.bid_calculator = bid_calculator or BidCalculator()

    async def generate_proposal(
        self,
        job: DiscoveredJob,
        agent: Agent,
        variant_id: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ) -> GeneratedProposal:
        """
        Generate a winning proposal for a job.

        Args:
            job: The job to apply for
            agent: The agent applying
            variant_id: Specific variant to use (for A/B testing)
            custom_instructions: Additional instructions for generation

        Returns:
            GeneratedProposal ready for submission
        """
        logger.info(
            "Generating proposal",
            job_id=str(job.id),
            agent_id=str(agent.id),
            variant_id=variant_id,
        )

        # Select variant for A/B testing
        if not variant_id:
            variant_id = random.choice(list(self.VARIANTS.keys()))
        variant = self.VARIANTS.get(variant_id, self.VARIANTS["direct"])

        # Analyze the job posting
        job_analysis = await self._analyze_job_posting(job)

        # Find relevant portfolio items
        relevant_portfolio = self._match_portfolio(agent, job_analysis)

        # Calculate bid
        bid_result = self.bid_calculator.calculate_optimal_bid(job, agent)

        # Generate cover letter
        cover_letter = await self._generate_cover_letter(
            job=job,
            agent=agent,
            job_analysis=job_analysis,
            relevant_work=relevant_portfolio,
            variant=variant,
            custom_instructions=custom_instructions,
        )

        # Humanize the letter
        humanized_letter = await self._humanize_proposal(cover_letter, agent)

        # Generate milestones if fixed price
        milestones = []
        if job.budget_type == "fixed" and bid_result["bid_amount"] > 200:
            milestones = await self._generate_milestones(
                job,
                bid_result["bid_amount"],
                job_analysis,
            )

        return GeneratedProposal(
            cover_letter=humanized_letter,
            bid_amount=bid_result["bid_amount"],
            bid_type=bid_result["bid_type"],
            estimated_duration=bid_result["duration"],
            milestones=milestones,
            attachments=[p.file_url for p in relevant_portfolio if p.file_url],
            variant_id=variant_id,
            generation_metadata={
                "job_analysis": job_analysis,
                "bid_calculation": bid_result,
                "variant": variant,
                "generated_at": datetime.utcnow().isoformat(),
            },
        )

    async def _analyze_job_posting(self, job: DiscoveredJob) -> dict:
        """Analyze job posting to understand key points"""
        prompt = f"""Analyze this job posting and extract key insights:

TITLE: {job.title}

DESCRIPTION:
{job.description}

BUDGET: {job.budget_display}
SKILLS REQUIRED: {', '.join(job.skills_required or [])}

Extract:
1. Main deliverable(s) expected
2. Key pain points or problems to solve
3. Any specific requirements mentioned
4. Client's apparent priorities
5. Questions the client might want answered
6. Tone/formality level expected
7. Potential approach to highlight

Format as structured analysis."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1000,
        )

        return {
            "analysis": response,
            "key_skills": job.skills_required or [],
            "budget_type": job.budget_type,
            "client_rating": float(job.client_rating or 0),
        }

    def _match_portfolio(
        self,
        agent: Agent,
        job_analysis: dict,
    ) -> list[AgentPortfolio]:
        """Find relevant portfolio items for the job"""
        if not agent.portfolio_items:
            return []

        key_skills = set(s.lower() for s in job_analysis.get("key_skills", []))
        relevant = []

        for item in agent.portfolio_items:
            # Check skill overlap
            item_skills = set(s.lower() for s in item.skills_demonstrated)
            if item_skills & key_skills:
                relevant.append(item)
            elif item.is_featured:
                relevant.append(item)

        # Sort by relevance (featured first, then by display order)
        relevant.sort(key=lambda x: (not x.is_featured, x.display_order))

        return relevant[:3]  # Return top 3

    async def _generate_cover_letter(
        self,
        job: DiscoveredJob,
        agent: Agent,
        job_analysis: dict,
        relevant_work: list[AgentPortfolio],
        variant: dict,
        custom_instructions: Optional[str],
    ) -> str:
        """Generate the cover letter"""
        # Build portfolio mention
        portfolio_mention = ""
        if relevant_work:
            portfolio_items = [f"- {p.title}: {p.description[:100]}..." for p in relevant_work]
            portfolio_mention = f"\n\nRELEVANT EXPERIENCE:\n" + "\n".join(portfolio_items)

        prompt = f"""Write a compelling proposal cover letter for this job:

JOB TITLE: {job.title}

JOB ANALYSIS:
{job_analysis['analysis']}

FREELANCER PROFILE:
Name: {agent.name}
Background: {agent.persona_description or 'Experienced freelancer'}
Key Skills: {', '.join(agent.capabilities[:5])}
{portfolio_mention}

PROPOSAL STYLE:
- Style: {variant['style']}
- Structure: {variant['structure']}
- Length: {variant['length']}

WRITING GUIDELINES:
1. Start by acknowledging a specific detail from the job posting
2. Demonstrate understanding of their needs
3. Briefly mention relevant experience
4. Propose a clear approach
5. End with an engaging question or soft call-to-action
6. Keep it human and avoid generic phrases
7. Don't be overly salesy or use superlatives

{f'ADDITIONAL INSTRUCTIONS: {custom_instructions}' if custom_instructions else ''}

Write the cover letter now. Do NOT include placeholder brackets like [Name] or [Company].
Make it feel personal and tailored."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1500,
            temperature=0.8,
        )

        return response.strip()

    async def _humanize_proposal(self, cover_letter: str, agent: Agent) -> str:
        """Make the proposal feel more human"""
        style = agent.writing_style or {}

        # Determine humanization approach
        uses_contractions = style.get("uses_contractions", True)
        formality = style.get("formality", "professional")

        # Small chance of minor typo (makes it feel human)
        add_typo = random.random() < 0.03

        prompt = f"""Lightly edit this cover letter to sound more naturally human:

{cover_letter}

HUMANIZATION RULES:
1. Vary sentence lengths more naturally
2. {"Use contractions where natural" if uses_contractions else "Maintain professional formality"}
3. Avoid cliche phrases like "I'm confident", "proven track record", "passion for"
4. Make transitions feel natural, not formulaic
5. Keep the same content and structure, just make it flow better
6. Formality level: {formality}
{f"7. Include one minor typo for authenticity" if add_typo else ""}

Return the edited cover letter only."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.FAST,
            max_tokens=1500,
            temperature=0.7,
        )

        return response.strip()

    async def _generate_milestones(
        self,
        job: DiscoveredJob,
        total_amount: Decimal,
        job_analysis: dict,
    ) -> list[dict]:
        """Generate payment milestones for fixed-price projects"""
        prompt = f"""Create payment milestones for this project:

PROJECT: {job.title}
TOTAL BUDGET: ${total_amount}

PROJECT ANALYSIS:
{job_analysis['analysis'][:500]}

Create 2-4 logical milestones with:
- Clear deliverable for each
- Reasonable amount (must sum to {total_amount})

Format as JSON array:
[
  {{"title": "Milestone 1", "amount": 100, "deliverable": "Description"}},
  ...
]"""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.FAST,
            max_tokens=500,
        )

        # Parse JSON
        import json
        import re

        try:
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                milestones = json.loads(json_match.group())
                return milestones
        except (json.JSONDecodeError, AttributeError):
            pass

        # Default milestones
        half = float(total_amount) / 2
        return [
            {
                "title": "Initial Delivery",
                "amount": half,
                "deliverable": "First version of deliverables",
            },
            {
                "title": "Final Delivery",
                "amount": half,
                "deliverable": "Final version with revisions",
            },
        ]

    async def regenerate_with_feedback(
        self,
        original_proposal: GeneratedProposal,
        feedback: str,
        job: DiscoveredJob,
        agent: Agent,
    ) -> GeneratedProposal:
        """Regenerate proposal incorporating feedback"""
        prompt = f"""Improve this proposal based on the feedback:

ORIGINAL PROPOSAL:
{original_proposal.cover_letter}

FEEDBACK:
{feedback}

JOB REQUIREMENTS:
{job.title}

Rewrite the proposal addressing the feedback while maintaining personalization.
Keep the same general structure but improve based on the feedback."""

        improved_letter = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1500,
            temperature=0.7,
        )

        return GeneratedProposal(
            cover_letter=improved_letter.strip(),
            bid_amount=original_proposal.bid_amount,
            bid_type=original_proposal.bid_type,
            estimated_duration=original_proposal.estimated_duration,
            milestones=original_proposal.milestones,
            attachments=original_proposal.attachments,
            variant_id=f"{original_proposal.variant_id}_revised",
            generation_metadata={
                **original_proposal.generation_metadata,
                "feedback": feedback,
                "regenerated_at": datetime.utcnow().isoformat(),
            },
        )
