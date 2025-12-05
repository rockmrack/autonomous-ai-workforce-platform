"""
Coding Executor - Handles programming and technical tasks
"""

from decimal import Decimal
from typing import Any, Optional

import structlog

from src.agents.models import Agent, AgentCapability
from src.discovery.models import ActiveJob
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .base import BaseExecutor, ExecutionResult, ExecutionStatus, TaskRequirements

logger = structlog.get_logger(__name__)


class CodingExecutor(BaseExecutor):
    """
    Handles coding and technical tasks.

    Capabilities:
    - Python scripts and applications
    - JavaScript/Node.js development
    - Web scraping scripts
    - API integrations
    - Automation scripts
    - Bug fixes and code review
    """

    CAPABILITIES = [
        AgentCapability.CODE_PYTHON,
        AgentCapability.CODE_JAVASCRIPT,
        AgentCapability.CODE_GENERAL,
        AgentCapability.API_INTEGRATION,
        AgentCapability.WEB_SCRAPING,
        AgentCapability.AUTOMATION,
    ]

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__()
        self.llm = llm_client or get_llm_client()

    @property
    def executor_type(self) -> str:
        return "coding"

    async def can_handle(self, job: ActiveJob) -> bool:
        """Check if this is a coding task"""
        matched = job.discovered_job.matched_capabilities or []
        for cap in self.CAPABILITIES:
            if cap.value in matched:
                return True

        desc = (job.discovered_job.description or "").lower()
        code_keywords = [
            "python", "javascript", "script", "code", "api",
            "scrape", "automate", "bot", "program", "developer",
        ]
        return any(kw in desc for kw in code_keywords)

    async def estimate_time(self, job: ActiveJob) -> int:
        """Estimate time in minutes"""
        requirements = await self.parse_requirements(job)

        # Base time
        base_time = 45

        # Adjust based on complexity indicators
        desc = requirements.primary_task.lower()

        if "simple" in desc or "basic" in desc:
            base_time = 30
        elif "complex" in desc or "full" in desc:
            base_time = 90
        elif "api" in desc:
            base_time = 60

        return int(base_time)

    async def execute(
        self,
        job: ActiveJob,
        agent: Agent,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Execute coding task"""
        self._track_start()

        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            success=False,
            deliverable_type="code",
        )

        try:
            result.add_log("Starting coding task")

            # Step 1: Analyze requirements
            result.add_log("Analyzing technical requirements")
            tech_spec = await self._analyze_requirements(requirements)

            # Step 2: Plan implementation
            result.add_log("Planning implementation")
            implementation_plan = await self._plan_implementation(tech_spec)

            # Step 3: Write code
            result.add_log("Writing code")
            code = await self._write_code(requirements, tech_spec, implementation_plan)

            # Step 4: Create tests
            result.add_log("Creating tests")
            tests = await self._create_tests(code, tech_spec)

            # Step 5: Add documentation
            result.add_log("Adding documentation")
            documented_code = await self._add_documentation(code, tech_spec)

            # Step 6: Package deliverable
            result.add_log("Packaging deliverable")
            deliverable = self._package_code(documented_code, tests, tech_spec)

            result.deliverable = deliverable
            result.deliverable_format = tech_spec.get("language", "python")
            result.status = ExecutionStatus.COMPLETED
            result.success = True
            result.time_spent_seconds = self._get_elapsed_seconds()
            result.tokens_used = self._tokens_used
            result.cost_estimate = self._cost

            result = await self.quality_check(result, requirements)

            result.add_log("Coding task completed", {
                "language": tech_spec.get("language"),
                "files": len(deliverable.get("files", [])) if isinstance(deliverable, dict) else 1,
            })

        except Exception as e:
            logger.error("Coding execution failed", error=str(e), exc_info=True)
            result.status = ExecutionStatus.FAILED
            result.error_message = str(e)
            result.add_log("Execution failed", {"error": str(e)})

        return result

    async def _analyze_requirements(self, requirements: TaskRequirements) -> dict:
        """Analyze technical requirements"""
        prompt = f"""Analyze this coding task and extract technical specifications:

TASK: {requirements.primary_task}

SUBTASKS:
{chr(10).join('- ' + s for s in requirements.subtasks)}

CONSTRAINTS:
{chr(10).join('- ' + c for c in requirements.constraints) if requirements.constraints else 'None specified'}

Extract:
1. Programming language (Python, JavaScript, etc.)
2. Required libraries/dependencies
3. Input/output specifications
4. Core functionality needed
5. Error handling requirements
6. Any security considerations

Format as a technical specification."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1500,
        )

        # Parse language from response
        language = "python"  # default
        if "javascript" in response.lower() or "node" in response.lower():
            language = "javascript"
        elif "typescript" in response.lower():
            language = "typescript"

        return {
            "specification": response,
            "language": language,
        }

    async def _plan_implementation(self, tech_spec: dict) -> str:
        """Create implementation plan"""
        prompt = f"""Based on this technical specification, create an implementation plan:

{tech_spec['specification']}

Create a step-by-step implementation plan including:
1. File structure
2. Main functions/classes needed
3. Implementation order
4. Integration points
5. Testing approach

Be specific and practical."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=1500,
        )

        return response

    async def _write_code(
        self,
        requirements: TaskRequirements,
        tech_spec: dict,
        plan: str,
    ) -> str:
        """Write the actual code"""
        language = tech_spec.get("language", "python")

        prompt = f"""Write clean, production-ready {language} code for this task:

TASK: {requirements.primary_task}

TECHNICAL SPEC:
{tech_spec['specification']}

IMPLEMENTATION PLAN:
{plan}

CODE REQUIREMENTS:
- Clean, readable code with meaningful variable names
- Proper error handling
- Follow {language} best practices
- Include type hints (if {language} supports them)
- Modular design with clear separation of concerns

Write the complete code now. Include all necessary imports and functions."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.POWERFUL,
            max_tokens=4000,
            temperature=0.3,  # Lower temperature for code
        )

        # Extract code blocks
        code = self._extract_code(response)

        return code

    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response"""
        import re

        # Look for code blocks
        code_blocks = re.findall(r'```(?:\w+)?\n([\s\S]*?)```', response)

        if code_blocks:
            return "\n\n".join(code_blocks)

        # If no code blocks, assume the whole response is code
        return response

    async def _create_tests(self, code: str, tech_spec: dict) -> str:
        """Create unit tests for the code"""
        language = tech_spec.get("language", "python")

        prompt = f"""Write unit tests for this {language} code:

```{language}
{code[:3000]}  # Truncate if too long
```

Create comprehensive tests including:
1. Happy path tests
2. Edge case tests
3. Error handling tests

Use appropriate testing framework ({language == 'python' and 'pytest' or 'jest'}).
Make tests practical and meaningful."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=2000,
            temperature=0.3,
        )

        return self._extract_code(response)

    async def _add_documentation(self, code: str, tech_spec: dict) -> str:
        """Add documentation to code"""
        language = tech_spec.get("language", "python")

        prompt = f"""Add comprehensive documentation to this {language} code:

```{language}
{code}
```

Add:
1. Module-level docstring explaining purpose
2. Function/class docstrings with parameters and return values
3. Inline comments for complex logic
4. Usage examples in docstrings

Return the fully documented code."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=4000,
            temperature=0.3,
        )

        return self._extract_code(response)

    def _package_code(self, code: str, tests: str, tech_spec: dict) -> dict:
        """Package code into deliverable format"""
        language = tech_spec.get("language", "python")

        extension = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
        }.get(language, "txt")

        # Create README
        readme = f"""# Project Code

## Description
{tech_spec.get('specification', 'Code deliverable')[:500]}

## Requirements
See requirements.txt or package.json

## Usage
See code documentation for usage examples.

## Testing
Run tests with {'pytest' if language == 'python' else 'npm test'}
"""

        return {
            "files": [
                {
                    "name": f"main.{extension}",
                    "content": code,
                    "type": "code",
                },
                {
                    "name": f"test_main.{extension}",
                    "content": tests,
                    "type": "test",
                },
                {
                    "name": "README.md",
                    "content": readme,
                    "type": "documentation",
                },
            ],
            "language": language,
            "main_file": f"main.{extension}",
        }

    async def quality_check(
        self,
        result: ExecutionResult,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Code-specific quality checks"""
        result = await super().quality_check(result, requirements)

        if not result.deliverable:
            return result

        deliverable = result.deliverable
        code = ""

        if isinstance(deliverable, dict):
            for file in deliverable.get("files", []):
                if file.get("type") == "code":
                    code = file.get("content", "")
                    break
        else:
            code = str(deliverable)

        # Check code has content
        if len(code) < 100:
            result.quality_issues.append("Code seems too short")

        # Check for basic structure
        if "def " not in code and "function " not in code and "class " not in code:
            result.quality_issues.append("No functions or classes defined")

        # Check for error handling
        if "try" not in code and "catch" not in code:
            result.quality_issues.append("No error handling found")

        # Check for comments/documentation
        if "#" not in code and "//" not in code and '"""' not in code:
            result.quality_issues.append("Limited documentation/comments")

        # Recalculate score
        if result.quality_issues:
            result.quality_score = max(0.5, 0.9 - len(result.quality_issues) * 0.1)
        else:
            result.quality_score = 0.9

        return result
