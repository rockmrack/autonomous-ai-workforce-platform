"""
Writing Executor - Handles all content writing tasks
Blog posts, articles, copywriting, email sequences, etc.
"""

from decimal import Decimal
from typing import Optional

import structlog

from src.agents.models import Agent, AgentCapability
from src.discovery.models import ActiveJob
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .base import BaseExecutor, ExecutionResult, ExecutionStatus, TaskRequirements

logger = structlog.get_logger(__name__)


class WritingExecutor(BaseExecutor):
    """
    Handles content writing tasks.

    Capabilities:
    - Blog posts and articles
    - SEO-optimized content
    - Marketing copy
    - Email sequences
    - Product descriptions
    - Website copy
    - Technical documentation
    """

    CAPABILITIES = [
        AgentCapability.CONTENT_WRITING,
        AgentCapability.SEO_WRITING,
        AgentCapability.COPYWRITING,
        AgentCapability.BLOG_WRITING,
        AgentCapability.EMAIL_WRITING,
        AgentCapability.TECHNICAL_WRITING,
    ]

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__()
        self.llm = llm_client or get_llm_client()

    @property
    def executor_type(self) -> str:
        return "writing"

    async def can_handle(self, job: ActiveJob) -> bool:
        """Check if this is a writing task"""
        # Check matched capabilities
        matched = job.discovered_job.matched_capabilities or []
        for cap in self.CAPABILITIES:
            if cap.value in matched:
                return True

        # Check description for writing-related keywords
        desc = (job.discovered_job.description or "").lower()
        writing_keywords = [
            "write", "writing", "article", "blog", "content",
            "copy", "seo", "email", "newsletter", "documentation",
        ]
        return any(kw in desc for kw in writing_keywords)

    async def estimate_time(self, job: ActiveJob) -> int:
        """Estimate time in minutes"""
        # Parse requirements to understand scope
        requirements = await self.parse_requirements(job)

        # Base time: 15 minutes per 500 words
        base_time = 15

        if requirements.word_count:
            base_time = (requirements.word_count / 500) * 15

        # Add time for research if needed
        if "research" in requirements.primary_task.lower():
            base_time += 20

        # Add time for SEO optimization
        if requirements.keywords:
            base_time += 10

        return int(base_time)

    async def execute(
        self,
        job: ActiveJob,
        agent: Agent,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Execute writing task"""
        self._track_start()

        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            success=False,
            deliverable_type="text",
            deliverable_format="markdown",
        )

        try:
            result.add_log("Starting writing task", {
                "job_id": str(job.id),
                "task_type": requirements.task_type,
            })

            # Step 1: Research if needed
            research_data = None
            if self._needs_research(requirements):
                result.add_log("Conducting research")
                research_data = await self._conduct_research(requirements)
                result.sources = research_data.get("sources", [])

            # Step 2: Create outline
            result.add_log("Creating content outline")
            outline = await self._create_outline(requirements, research_data)

            # Step 3: Write content
            result.add_log("Writing content")
            content = await self._write_content(
                requirements=requirements,
                outline=outline,
                research=research_data,
                agent_style=agent.writing_style,
            )

            # Step 4: Edit and polish
            result.add_log("Editing and polishing")
            polished = await self._edit_content(content, requirements)

            # Step 5: Humanize (reduce AI detection)
            result.add_log("Humanizing content")
            final_content = await self._humanize_content(polished, agent)

            # Step 6: Format for delivery
            result.add_log("Formatting deliverable")
            formatted = self._format_deliverable(final_content, requirements)

            result.deliverable = formatted
            result.status = ExecutionStatus.COMPLETED
            result.success = True
            result.time_spent_seconds = self._get_elapsed_seconds()
            result.tokens_used = self._tokens_used
            result.cost_estimate = self._cost

            # Quality check
            result = await self.quality_check(result, requirements)

            result.add_log("Writing task completed", {
                "word_count": len(formatted.split()),
                "quality_score": result.quality_score,
            })

        except Exception as e:
            logger.error("Writing execution failed", error=str(e), exc_info=True)
            result.status = ExecutionStatus.FAILED
            result.error_message = str(e)
            result.add_log("Execution failed", {"error": str(e)})

        return result

    def _needs_research(self, requirements: TaskRequirements) -> bool:
        """Determine if task needs research"""
        research_indicators = [
            "research", "facts", "statistics", "data",
            "examples", "case study", "industry",
        ]
        task_text = f"{requirements.primary_task} {' '.join(requirements.subtasks)}".lower()
        return any(ind in task_text for ind in research_indicators)

    async def _conduct_research(self, requirements: TaskRequirements) -> dict:
        """Conduct research for the content"""
        # In a real implementation, this would use web search tools
        # For now, we'll ask the LLM to synthesize general knowledge

        prompt = f"""You are a research assistant. Provide key facts and information for writing about:

Topic: {requirements.primary_task}

Specific areas to cover:
{chr(10).join('- ' + s for s in requirements.subtasks)}

Please provide:
1. Key facts and statistics (with placeholder citations)
2. Important concepts to explain
3. Examples that could be used
4. Common misconceptions to address

Format as structured notes."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=2000,
        )

        return {
            "notes": response,
            "sources": ["Research compiled from domain knowledge"],
        }

    async def _create_outline(
        self,
        requirements: TaskRequirements,
        research: Optional[dict],
    ) -> str:
        """Create content outline"""
        research_notes = research.get("notes", "") if research else ""

        prompt = f"""Create a detailed outline for the following content:

TASK: {requirements.primary_task}
FORMAT: {requirements.output_format or 'article'}
TARGET LENGTH: {requirements.word_count or 800} words
STYLE: {', '.join(requirements.style_requirements) or 'professional'}
KEYWORDS TO INCLUDE: {', '.join(requirements.keywords) or 'none specified'}

{f'RESEARCH NOTES:{chr(10)}{research_notes}' if research_notes else ''}

Create a structured outline with:
- Engaging title options (2-3)
- Hook/Introduction approach
- Main sections with key points
- Conclusion approach
- Call to action (if applicable)

Format as a clear hierarchical outline."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1500,
        )

        return response

    async def _write_content(
        self,
        requirements: TaskRequirements,
        outline: str,
        research: Optional[dict],
        agent_style: dict,
    ) -> str:
        """Write the actual content"""
        style_instructions = self._get_style_instructions(agent_style, requirements)

        prompt = f"""Write the full content based on this outline:

{outline}

REQUIREMENTS:
- Target length: {requirements.word_count or 800} words
- Include keywords: {', '.join(requirements.keywords) or 'N/A'}
- Style: {', '.join(requirements.style_requirements) or 'professional and engaging'}

{style_instructions}

SPECIAL INSTRUCTIONS: {requirements.special_instructions or 'None'}

Write the complete content now. Make it engaging, informative, and well-structured.
Use natural transitions between sections."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=4000,
            temperature=0.7,
        )

        return response

    async def _edit_content(self, content: str, requirements: TaskRequirements) -> str:
        """Edit and polish the content"""
        prompt = f"""Edit and improve this content:

{content}

EDITING CHECKLIST:
1. Fix any grammar or spelling errors
2. Improve sentence variety and flow
3. Ensure keywords are naturally integrated: {', '.join(requirements.keywords) or 'N/A'}
4. Check logical flow between paragraphs
5. Strengthen the opening hook
6. Make the conclusion more impactful
7. Remove any redundant phrases
8. Ensure consistent tone throughout

Return the edited content. Keep the same structure but improve quality."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=4000,
            temperature=0.3,
        )

        return response

    async def _humanize_content(self, content: str, agent: Agent) -> str:
        """Make content less detectable as AI-generated"""
        style = agent.writing_style or {}

        # Get humanization preferences from agent style
        formality = style.get("formality", "professional")
        uses_contractions = style.get("uses_contractions", True)

        prompt = f"""Rewrite this content to sound more naturally human-written:

{content}

HUMANIZATION GUIDELINES:
1. Vary sentence structure more - mix short punchy sentences with longer ones
2. Add occasional rhetorical questions
3. Use more specific, unusual word choices instead of common AI phrases
4. {"Use contractions naturally" if uses_contractions else "Maintain formal tone without contractions"}
5. Add subtle personal touches or observations where appropriate
6. Avoid phrases like "In conclusion", "Furthermore", "It's important to note"
7. Use more active voice
8. Include occasional informal transitions

Formality level: {formality}

Rewrite maintaining the same information but sounding more human."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=4000,
            temperature=0.8,
        )

        return response

    def _get_style_instructions(self, agent_style: dict, requirements: TaskRequirements) -> str:
        """Generate style instructions for the agent"""
        instructions = []

        formality = agent_style.get("formality", "professional")
        if formality == "casual":
            instructions.append("Write in a conversational, friendly tone")
        elif formality == "professional":
            instructions.append("Maintain a professional but approachable tone")
        else:
            instructions.append("Use a semi-formal tone, balanced between casual and professional")

        if agent_style.get("uses_contractions", True):
            instructions.append("Use contractions naturally (don't, isn't, etc.)")
        else:
            instructions.append("Avoid contractions")

        verbosity = agent_style.get("verbosity", "moderate")
        if verbosity == "concise":
            instructions.append("Be concise and get to the point quickly")
        elif verbosity == "detailed":
            instructions.append("Provide thorough explanations with examples")

        return "\nWRITING STYLE:\n" + "\n".join(f"- {i}" for i in instructions)

    def _format_deliverable(self, content: str, requirements: TaskRequirements) -> str:
        """Format content for delivery"""
        format_type = requirements.output_format or "markdown"

        if format_type.lower() == "html":
            # Convert markdown to basic HTML
            return self._markdown_to_html(content)
        elif format_type.lower() == "plain":
            # Strip markdown formatting
            return self._strip_markdown(content)

        # Default: return as markdown
        return content

    def _markdown_to_html(self, content: str) -> str:
        """Basic markdown to HTML conversion"""
        import re

        html = content

        # Headers
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # Bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

        # Lists
        html = re.sub(r'^\- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

        # Paragraphs
        paragraphs = html.split('\n\n')
        html = '\n\n'.join(f'<p>{p}</p>' if not p.startswith('<') else p for p in paragraphs)

        return html

    def _strip_markdown(self, content: str) -> str:
        """Remove markdown formatting"""
        import re

        text = content

        # Remove headers markers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

        # Remove bold/italic
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)

        # Remove links but keep text
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)

        return text

    async def quality_check(
        self,
        result: ExecutionResult,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Writing-specific quality checks"""
        result = await super().quality_check(result, requirements)

        if not result.deliverable:
            return result

        content = str(result.deliverable)

        # Check keyword inclusion
        if requirements.keywords:
            missing_keywords = []
            for kw in requirements.keywords:
                if kw.lower() not in content.lower():
                    missing_keywords.append(kw)

            if missing_keywords:
                result.quality_issues.append(
                    f"Missing keywords: {', '.join(missing_keywords)}"
                )

        # Check for common AI phrases to flag
        ai_phrases = [
            "as an ai", "i cannot", "i don't have personal",
            "it's important to note that", "in conclusion,",
        ]
        for phrase in ai_phrases:
            if phrase in content.lower():
                result.quality_issues.append(
                    f"Contains AI-sounding phrase: '{phrase}'"
                )

        # Recalculate quality score
        if result.quality_issues:
            result.quality_score = max(0.3, 0.95 - len(result.quality_issues) * 0.1)
        else:
            result.quality_score = 0.95

        return result
