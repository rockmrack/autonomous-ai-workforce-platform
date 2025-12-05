"""
Base Executor - Abstract interface for task execution
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID

import structlog

from src.agents.models import Agent, AgentCapability
from src.discovery.models import ActiveJob

logger = structlog.get_logger(__name__)


class ExecutionStatus(str, Enum):
    """Execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_INPUT = "needs_input"


@dataclass
class ExecutionResult:
    """Result of task execution"""

    # Status
    status: ExecutionStatus
    success: bool

    # Output
    deliverable: Optional[Any] = None
    deliverable_type: Optional[str] = None  # 'text', 'file', 'data', 'code'
    deliverable_format: Optional[str] = None  # 'markdown', 'docx', 'xlsx', 'json', etc.

    # Files
    files: list[dict] = field(default_factory=list)  # [{name, path, type, size}]

    # Metrics
    time_spent_seconds: int = 0
    tokens_used: int = 0
    cost_estimate: Decimal = Decimal("0")

    # Quality
    quality_score: Optional[float] = None
    quality_issues: list[str] = field(default_factory=list)

    # Sources/references
    sources: list[str] = field(default_factory=list)

    # Error info (if failed)
    error_message: Optional[str] = None
    error_details: Optional[dict] = None

    # Execution log
    execution_log: list[dict] = field(default_factory=list)

    def add_log(self, message: str, data: Optional[dict] = None) -> None:
        """Add entry to execution log"""
        self.execution_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            "data": data or {},
        })

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "success": self.success,
            "deliverable_type": self.deliverable_type,
            "deliverable_format": self.deliverable_format,
            "files_count": len(self.files),
            "time_spent_seconds": self.time_spent_seconds,
            "tokens_used": self.tokens_used,
            "cost_estimate": float(self.cost_estimate),
            "quality_score": self.quality_score,
            "quality_issues": self.quality_issues,
            "sources_count": len(self.sources),
            "error_message": self.error_message,
        }


@dataclass
class TaskRequirements:
    """Parsed requirements for a task"""

    # Main task
    primary_task: str
    task_type: str

    # Specifics
    subtasks: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    # Output requirements
    output_format: Optional[str] = None
    word_count: Optional[int] = None
    file_format: Optional[str] = None

    # Quality requirements
    style_requirements: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    # Other
    deadline: Optional[datetime] = None
    special_instructions: Optional[str] = None


class BaseExecutor(ABC):
    """
    Base class for task executors.

    Each executor handles a specific type of task (research, writing, etc.)
    and orchestrates the LLM and tools needed to complete it.
    """

    # Capabilities this executor handles
    CAPABILITIES: list[AgentCapability] = []

    def __init__(self):
        self._start_time: Optional[datetime] = None
        self._tokens_used = 0
        self._cost = Decimal("0")

    @property
    @abstractmethod
    def executor_type(self) -> str:
        """Return executor type identifier"""
        pass

    @abstractmethod
    async def can_handle(self, job: ActiveJob) -> bool:
        """
        Check if this executor can handle the given job.

        Args:
            job: The job to check

        Returns:
            True if this executor can handle the job
        """
        pass

    @abstractmethod
    async def estimate_time(self, job: ActiveJob) -> int:
        """
        Estimate time in minutes to complete the job.

        Args:
            job: The job to estimate

        Returns:
            Estimated minutes
        """
        pass

    @abstractmethod
    async def execute(
        self,
        job: ActiveJob,
        agent: Agent,
        requirements: TaskRequirements,
    ) -> ExecutionResult:
        """
        Execute the task and return result.

        Args:
            job: The active job to execute
            agent: The agent executing the task
            requirements: Parsed task requirements

        Returns:
            ExecutionResult with deliverable or error
        """
        pass

    async def parse_requirements(self, job: ActiveJob) -> TaskRequirements:
        """
        Parse job description into structured requirements.
        Uses LLM to understand what's needed.
        """
        from src.llm.client import get_llm_client, ModelTier

        llm = get_llm_client()

        prompt = f"""Analyze this job and extract structured requirements.

Job Title: {job.discovered_job.title}

Job Description:
{job.discovered_job.description}

Extract and return in this exact format:

PRIMARY_TASK: [One sentence description of main task]
TASK_TYPE: [One of: research, writing, data_entry, coding, analysis, other]
SUBTASKS:
- [Subtask 1]
- [Subtask 2]
CONSTRAINTS:
- [Constraint 1]
- [Constraint 2]
OUTPUT_FORMAT: [Expected output format]
WORD_COUNT: [If applicable, otherwise "N/A"]
STYLE_REQUIREMENTS:
- [Style requirement 1]
KEYWORDS: [Comma-separated keywords if any]
SPECIAL_INSTRUCTIONS: [Any special notes]
"""

        response = await llm.generate(
            prompt=prompt,
            model_tier=ModelTier.FAST,
            max_tokens=1000,
        )

        return self._parse_requirements_response(response)

    def _parse_requirements_response(self, response: str) -> TaskRequirements:
        """Parse LLM response into TaskRequirements"""
        lines = response.strip().split("\n")
        req = TaskRequirements(primary_task="", task_type="other")

        current_section = None
        current_list: list[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("PRIMARY_TASK:"):
                req.primary_task = line.split(":", 1)[1].strip()
            elif line.startswith("TASK_TYPE:"):
                req.task_type = line.split(":", 1)[1].strip().lower()
            elif line.startswith("SUBTASKS:"):
                current_section = "subtasks"
            elif line.startswith("CONSTRAINTS:"):
                current_section = "constraints"
            elif line.startswith("OUTPUT_FORMAT:"):
                req.output_format = line.split(":", 1)[1].strip()
                current_section = None
            elif line.startswith("WORD_COUNT:"):
                wc = line.split(":", 1)[1].strip()
                if wc.isdigit():
                    req.word_count = int(wc)
                current_section = None
            elif line.startswith("STYLE_REQUIREMENTS:"):
                current_section = "style"
            elif line.startswith("KEYWORDS:"):
                keywords = line.split(":", 1)[1].strip()
                req.keywords = [k.strip() for k in keywords.split(",") if k.strip()]
                current_section = None
            elif line.startswith("SPECIAL_INSTRUCTIONS:"):
                req.special_instructions = line.split(":", 1)[1].strip()
                current_section = None
            elif line.startswith("-") and current_section:
                item = line[1:].strip()
                if current_section == "subtasks":
                    req.subtasks.append(item)
                elif current_section == "constraints":
                    req.constraints.append(item)
                elif current_section == "style":
                    req.style_requirements.append(item)

        return req

    async def quality_check(self, result: ExecutionResult, requirements: TaskRequirements) -> ExecutionResult:
        """
        Perform self-quality check on the result.
        Can be overridden by specific executors.
        """
        # Basic check - deliverable exists
        if not result.deliverable:
            result.quality_score = 0.0
            result.quality_issues.append("No deliverable produced")
            return result

        # Check word count if specified
        if requirements.word_count and result.deliverable_type == "text":
            actual_words = len(str(result.deliverable).split())
            if actual_words < requirements.word_count * 0.8:
                result.quality_issues.append(
                    f"Word count too low: {actual_words} vs required {requirements.word_count}"
                )
            elif actual_words > requirements.word_count * 1.2:
                result.quality_issues.append(
                    f"Word count too high: {actual_words} vs required {requirements.word_count}"
                )

        # Base quality score
        if not result.quality_issues:
            result.quality_score = 0.9
        else:
            result.quality_score = max(0.5, 0.9 - len(result.quality_issues) * 0.1)

        return result

    def _track_start(self) -> None:
        """Track execution start time"""
        self._start_time = datetime.utcnow()

    def _track_tokens(self, tokens: int, cost: Decimal) -> None:
        """Track token usage"""
        self._tokens_used += tokens
        self._cost += cost

    def _get_elapsed_seconds(self) -> int:
        """Get elapsed time since start"""
        if not self._start_time:
            return 0
        return int((datetime.utcnow() - self._start_time).total_seconds())

    def _create_result(
        self,
        success: bool,
        deliverable: Any = None,
        error: Optional[str] = None,
    ) -> ExecutionResult:
        """Create a result with tracked metrics"""
        return ExecutionResult(
            status=ExecutionStatus.COMPLETED if success else ExecutionStatus.FAILED,
            success=success,
            deliverable=deliverable,
            time_spent_seconds=self._get_elapsed_seconds(),
            tokens_used=self._tokens_used,
            cost_estimate=self._cost,
            error_message=error,
        )
