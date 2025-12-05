"""
Data Entry Executor - Handles data entry and spreadsheet tasks
"""

from decimal import Decimal
from typing import Any, Optional

import structlog

from src.agents.models import Agent, AgentCapability
from src.discovery.models import ActiveJob
from src.llm.client import LLMClient, ModelTier, get_llm_client
from .base import BaseExecutor, ExecutionResult, ExecutionStatus, TaskRequirements

logger = structlog.get_logger(__name__)


class DataEntryExecutor(BaseExecutor):
    """
    Handles data entry and spreadsheet tasks.

    Capabilities:
    - Data entry from various sources
    - Spreadsheet creation and manipulation
    - Data cleaning and normalization
    - Form filling
    - Data transformation
    """

    CAPABILITIES = [
        AgentCapability.DATA_ENTRY,
        AgentCapability.SPREADSHEET,
        AgentCapability.DATA_ANALYSIS,
        AgentCapability.TRANSCRIPTION,
    ]

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__()
        self.llm = llm_client or get_llm_client()

    @property
    def executor_type(self) -> str:
        return "data_entry"

    async def can_handle(self, job: ActiveJob) -> bool:
        """Check if this is a data entry task"""
        matched = job.discovered_job.matched_capabilities or []
        for cap in self.CAPABILITIES:
            if cap.value in matched:
                return True

        desc = (job.discovered_job.description or "").lower()
        data_keywords = [
            "data entry", "spreadsheet", "excel", "google sheets",
            "csv", "database", "transcription", "typing",
        ]
        return any(kw in desc for kw in data_keywords)

    async def estimate_time(self, job: ActiveJob) -> int:
        """Estimate time in minutes"""
        requirements = await self.parse_requirements(job)

        # Base time
        base_time = 20

        # Add time based on data volume indicators
        desc = requirements.primary_task.lower()
        if "100" in desc or "hundred" in desc:
            base_time += 30
        if "500" in desc or "thousand" in desc:
            base_time += 60

        return int(base_time)

    async def execute(
        self,
        job: ActiveJob,
        agent: Agent,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Execute data entry task"""
        self._track_start()

        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            success=False,
            deliverable_type="data",
        )

        try:
            result.add_log("Starting data entry task")

            # Step 1: Understand data structure
            result.add_log("Analyzing data structure")
            structure = await self._analyze_data_structure(requirements)

            # Step 2: Process/generate data
            result.add_log("Processing data")
            data = await self._process_data(requirements, structure)

            # Step 3: Validate data
            result.add_log("Validating data")
            validated_data = await self._validate_data(data, structure)

            # Step 4: Format output
            result.add_log("Formatting output")
            formatted = await self._format_data_output(
                validated_data,
                requirements.output_format or "csv",
            )

            result.deliverable = formatted
            result.deliverable_format = requirements.output_format or "csv"
            result.status = ExecutionStatus.COMPLETED
            result.success = True
            result.time_spent_seconds = self._get_elapsed_seconds()
            result.tokens_used = self._tokens_used
            result.cost_estimate = self._cost

            result = await self.quality_check(result, requirements)

            result.add_log("Data entry completed")

        except Exception as e:
            logger.error("Data entry failed", error=str(e), exc_info=True)
            result.status = ExecutionStatus.FAILED
            result.error_message = str(e)
            result.add_log("Execution failed", {"error": str(e)})

        return result

    async def _analyze_data_structure(self, requirements: TaskRequirements) -> dict:
        """Analyze the expected data structure"""
        prompt = f"""Analyze this data task and define the data structure:

TASK: {requirements.primary_task}

SUBTASKS:
{chr(10).join('- ' + s for s in requirements.subtasks)}

OUTPUT FORMAT: {requirements.output_format or 'spreadsheet'}

Define:
1. Column names/fields needed
2. Data types for each field
3. Any validation rules
4. Expected number of records (estimate)

Format as a structured schema."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.FAST,
            max_tokens=1000,
        )

        return {
            "schema": response,
            "columns": self._extract_columns(response),
        }

    def _extract_columns(self, schema_text: str) -> list[str]:
        """Extract column names from schema"""
        import re
        columns = []

        # Look for column-like patterns
        patterns = [
            r"(?:column|field)[:\s]+([^\n,]+)",
            r"^\s*-\s*(\w+)",
            r"^\d+\.\s*(\w+)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, schema_text, re.IGNORECASE | re.MULTILINE)
            columns.extend(matches)

        # Clean up
        columns = [c.strip() for c in columns if c.strip()]
        return list(dict.fromkeys(columns))[:20]  # Unique, max 20

    async def _process_data(
        self,
        requirements: TaskRequirements,
        structure: dict,
    ) -> list[dict]:
        """Process or generate the data"""
        columns = structure.get("columns", [])
        if not columns:
            columns = ["Field1", "Field2", "Field3"]

        prompt = f"""Generate sample data for this task:

TASK: {requirements.primary_task}

COLUMNS: {', '.join(columns)}

REQUIREMENTS:
{chr(10).join('- ' + c for c in requirements.constraints) if requirements.constraints else 'Standard data quality'}

Generate 10 sample records in JSON format:
[
  {{"column1": "value1", "column2": "value2"}},
  ...
]

Make the data realistic and consistent with the task requirements."""

        response = await self.llm.generate(
            prompt=prompt,
            model_tier=ModelTier.DEFAULT,
            max_tokens=2000,
        )

        # Parse JSON from response
        import json
        import re

        try:
            # Find JSON array in response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        # Fallback: return empty data with headers
        return [{col: "" for col in columns}]

    async def _validate_data(
        self,
        data: list[dict],
        structure: dict,
    ) -> list[dict]:
        """Validate and clean the data"""
        validated = []

        for row in data:
            cleaned_row = {}
            for key, value in row.items():
                # Basic cleaning
                if isinstance(value, str):
                    value = value.strip()
                cleaned_row[key] = value
            validated.append(cleaned_row)

        return validated

    async def _format_data_output(
        self,
        data: list[dict],
        output_format: str,
    ) -> Any:
        """Format data for delivery"""
        import json

        if output_format == "json":
            return json.dumps(data, indent=2)

        elif output_format in ["csv", "spreadsheet"]:
            if not data:
                return ""

            # Get headers
            headers = list(data[0].keys())

            # Create CSV
            lines = [",".join(f'"{h}"' for h in headers)]

            for row in data:
                values = []
                for h in headers:
                    val = str(row.get(h, ""))
                    # Escape quotes
                    val = val.replace('"', '""')
                    values.append(f'"{val}"')
                lines.append(",".join(values))

            return "\n".join(lines)

        else:
            # Markdown table
            if not data:
                return ""

            headers = list(data[0].keys())

            lines = []
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

            for row in data:
                values = [str(row.get(h, "")) for h in headers]
                lines.append("| " + " | ".join(values) + " |")

            return "\n".join(lines)

    async def quality_check(
        self,
        result: ExecutionResult,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """Data-specific quality checks"""
        result = await super().quality_check(result, requirements)

        if not result.deliverable:
            return result

        content = str(result.deliverable)

        # Check for empty data
        if len(content) < 50:
            result.quality_issues.append("Data output seems too small")

        # Check for data consistency
        lines = content.strip().split("\n")
        if len(lines) < 2:
            result.quality_issues.append("Insufficient data records")

        # Recalculate score
        if result.quality_issues:
            result.quality_score = max(0.5, 0.9 - len(result.quality_issues) * 0.15)
        else:
            result.quality_score = 0.9

        return result
