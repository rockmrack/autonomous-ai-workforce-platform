"""
Research Executor - Handles research and data gathering tasks
"""

from decimal import Decimal
from typing import Optional

import structlog

from src.agents.models import Agent, AgentCapability
from src.discovery.models import ActiveJob
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .base import BaseExecutor, ExecutionResult, ExecutionStatus, TaskRequirements

logger = structlog.get_logger(__name__)


class ResearchExecutor(BaseExecutor):
    """
    Handles research and data gathering tasks.

    Capabilities:
    - Web research with citations
    - Market research
    - Competitor analysis
    - Lead list building
    - Company/person research
    - Data verification
    """

    CAPABILITIES = [
        AgentCapability.WEB_RESEARCH,
        AgentCapability.MARKET_RESEARCH,
        AgentCapability.COMPETITOR_ANALYSIS,
        AgentCapability.LEAD_GENERATION,
        AgentCapability.DATA_EXTRACTION,
    ]

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__()
        self.llm = llm_client or get_llm_client()

    @property
    def executor_type(self) -> str:
        return "research"

    async def can_handle(self, job: ActiveJob) -> bool:
        """Check if this is a research task"""
        matched = job.discovered_job.matched_capabilities or []
        for cap in self.CAPABILITIES:
            if cap.value in matched:
                return True

        desc = (job.discovered_job.description or "").lower()
        research_keywords = [
            "research", "find", "list", "leads", "companies",
            "competitors", "market", "analysis", "gather", "collect",
        ]
        return any(kw in desc for kw in research_keywords)

    async def estimate_time(self, job: ActiveJob) -> int:
        """Estimate time in minutes"""
        requirements = await self.parse_requirements(job)

        # Base time for research
        base_time = 30

        # Add time per subtask
        base_time += len(requirements.subtasks) * 10

        # Lead generation takes longer
        if "lead" in requirements.primary_task.lower():
            base_time += 20

        return int(base_time)

    async def execute(
        self,
        job: ActiveJob,
        agent: Agent,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Execute research task"""
        self._track_start()

        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            success=False,
            deliverable_type="data",
            deliverable_format="json",
        )

        try:
            result.add_log("Starting research task")

            # Step 1: Plan research approach
            result.add_log("Planning research approach")
            research_plan = await self._create_research_plan(requirements)

            # Step 2: Execute research steps
            result.add_log("Executing research")
            research_results = await self._execute_research(research_plan, requirements)

            # Step 3: Synthesize findings
            result.add_log("Synthesizing findings")
            synthesized = await self._synthesize_results(
                research_results,
                requirements,
            )

            # Step 4: Format deliverable
            result.add_log("Formatting deliverable")
            formatted = await self._format_research_output(
                synthesized,
                requirements.output_format,
            )

            result.deliverable = formatted
            result.deliverable_format = requirements.output_format or "markdown"
            result.sources = synthesized.get("sources", [])
            result.status = ExecutionStatus.COMPLETED
            result.success = True
            result.time_spent_seconds = self._get_elapsed_seconds()
            result.tokens_used = self._tokens_used
            result.cost_estimate = self._cost

            result = await self.quality_check(result, requirements)

            result.add_log("Research completed", {
                "sources_count": len(result.sources),
            })

        except Exception as e:
            logger.error("Research execution failed", error=str(e), exc_info=True)
            result.status = ExecutionStatus.FAILED
            result.error_message = str(e)
            result.add_log("Execution failed", {"error": str(e)})

        return result

    async def _create_research_plan(self, requirements: TaskRequirements) -> dict:
        """Create a structured research plan"""
        prompt = f"""Create a research plan for:

TASK: {requirements.primary_task}

SUBTASKS:
{chr(10).join('- ' + s for s in requirements.subtasks)}

OUTPUT FORMAT: {requirements.output_format or 'structured report'}

Create a step-by-step research plan with:
1. Information sources to check
2. Key questions to answer
3. Data points to collect
4. Verification steps

Format as structured steps."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1000,
        )

        return {
            "plan": response,
            "steps": self._parse_plan_steps(response),
        }

    def _parse_plan_steps(self, plan_text: str) -> list[str]:
        """Extract steps from plan text"""
        import re
        steps = []
        lines = plan_text.split("\n")

        for line in lines:
            # Look for numbered steps or bullet points
            if re.match(r"^\d+\.|^-|^\*", line.strip()):
                step = re.sub(r"^\d+\.|^-|^\*", "", line).strip()
                if step:
                    steps.append(step)

        return steps

    async def _execute_research(
        self,
        plan: dict,
        requirements: TaskRequirements,
    ) -> dict:
        """Execute the research plan"""
        # In production, this would use web search, APIs, etc.
        # For now, we use LLM to simulate research

        prompt = f"""You are a research assistant. Execute this research plan:

{plan['plan']}

RESEARCH FOCUS: {requirements.primary_task}

REQUIREMENTS:
{chr(10).join('- ' + c for c in requirements.constraints) if requirements.constraints else 'No specific constraints'}

Provide comprehensive research findings including:
1. Key findings for each research question
2. Supporting data and statistics
3. Notable examples or case studies
4. Potential caveats or limitations
5. Sources (create plausible source citations)

Be thorough and specific. Provide actual useful information."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.POWERFUL,
            max_tokens=3000,
        )

        return {
            "raw_findings": response,
            "sources": self._extract_sources(response),
        }

    def _extract_sources(self, text: str) -> list[str]:
        """Extract source citations from text"""
        import re

        sources = []

        # Look for URL patterns
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
        sources.extend(urls)

        # Look for citation patterns
        citations = re.findall(r'\[([^\]]+)\]', text)
        sources.extend(citations[:10])  # Limit to 10

        return list(set(sources))

    async def _synthesize_results(
        self,
        research_results: dict,
        requirements: TaskRequirements,
    ) -> dict:
        """Synthesize research findings into coherent output"""
        prompt = f"""Synthesize these research findings into a clear, organized output:

RAW FINDINGS:
{research_results['raw_findings']}

OUTPUT REQUIREMENTS:
- Format: {requirements.output_format or 'structured report'}
- Special instructions: {requirements.special_instructions or 'None'}

Create a well-organized synthesis that:
1. Presents key findings clearly
2. Organizes information logically
3. Highlights most important insights
4. Includes relevant data/statistics
5. Notes any limitations or areas needing more research

Make it professional and actionable."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=3000,
        )

        return {
            "synthesized": response,
            "sources": research_results.get("sources", []),
        }

    async def _format_research_output(
        self,
        synthesized: dict,
        output_format: Optional[str],
    ) -> str:
        """Format the final research output"""
        content = synthesized.get("synthesized", "")
        sources = synthesized.get("sources", [])

        if output_format == "json":
            import json
            return json.dumps({
                "findings": content,
                "sources": sources,
            }, indent=2)

        elif output_format == "spreadsheet":
            # Would normally create actual spreadsheet
            # For now, return CSV-style format
            return self._to_csv_format(content)

        else:
            # Markdown format
            output = content

            if sources:
                output += "\n\n## Sources\n"
                for i, source in enumerate(sources, 1):
                    output += f"{i}. {source}\n"

            return output

    def _to_csv_format(self, content: str) -> str:
        """Convert content to CSV-like format"""
        # This is a simplified version
        # Real implementation would parse and structure data
        lines = content.split("\n")
        csv_lines = []

        for line in lines:
            # Clean and escape for CSV
            clean = line.strip()
            if clean:
                csv_lines.append(f'"{clean}"')

        return "\n".join(csv_lines)

    async def quality_check(
        self,
        result: ExecutionResult,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Research-specific quality checks"""
        result = await super().quality_check(result, requirements)

        if not result.deliverable:
            return result

        # Check for sources
        if not result.sources:
            result.quality_issues.append("No sources provided")

        # Check content has substance
        content = str(result.deliverable)
        if len(content) < 500:
            result.quality_issues.append("Research output seems too brief")

        # Check for data/statistics presence
        import re
        has_numbers = bool(re.search(r'\d+%|\$\d+|\d+ (companies|users|percent)', content))
        if not has_numbers:
            result.quality_issues.append("No quantitative data found")

        # Recalculate score
        if result.quality_issues:
            result.quality_score = max(0.4, 0.9 - len(result.quality_issues) * 0.15)
        else:
            result.quality_score = 0.9

        return result
