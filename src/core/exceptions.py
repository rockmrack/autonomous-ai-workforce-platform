"""
Custom exceptions for the AI Workforce Platform
Organized by module with detailed error information
"""

from typing import Any, Optional


class WorkforceException(Exception):
    """Base exception for all platform errors"""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        details: Optional[dict[str, Any]] = None,
        recoverable: bool = True,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }


# ===========================================
# Agent Exceptions
# ===========================================


class AgentException(WorkforceException):
    """Base exception for agent-related errors"""

    def __init__(
        self,
        message: str,
        agent_id: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        self.agent_id = agent_id
        if agent_id:
            self.details["agent_id"] = agent_id


class AgentNotFoundError(AgentException):
    """Agent does not exist"""

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent not found: {agent_id}",
            agent_id=agent_id,
            code="AGENT_NOT_FOUND",
            recoverable=False,
        )


class AgentBusyError(AgentException):
    """Agent is currently busy with other tasks"""

    def __init__(self, agent_id: str, current_jobs: int):
        super().__init__(
            message=f"Agent {agent_id} is busy with {current_jobs} jobs",
            agent_id=agent_id,
            code="AGENT_BUSY",
            details={"current_jobs": current_jobs},
            recoverable=True,
        )


class AgentSuspendedError(AgentException):
    """Agent has been suspended"""

    def __init__(self, agent_id: str, reason: str):
        super().__init__(
            message=f"Agent {agent_id} is suspended: {reason}",
            agent_id=agent_id,
            code="AGENT_SUSPENDED",
            details={"reason": reason},
            recoverable=False,
        )


class AgentCapabilityError(AgentException):
    """Agent lacks required capability"""

    def __init__(self, agent_id: str, required_capability: str):
        super().__init__(
            message=f"Agent {agent_id} lacks capability: {required_capability}",
            agent_id=agent_id,
            code="AGENT_CAPABILITY_MISSING",
            details={"required_capability": required_capability},
            recoverable=False,
        )


# ===========================================
# Job Exceptions
# ===========================================


class JobException(WorkforceException):
    """Base exception for job-related errors"""

    def __init__(
        self,
        message: str,
        job_id: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        self.job_id = job_id
        if job_id:
            self.details["job_id"] = job_id


class JobNotFoundError(JobException):
    """Job does not exist"""

    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job not found: {job_id}",
            job_id=job_id,
            code="JOB_NOT_FOUND",
            recoverable=False,
        )


class JobExpiredError(JobException):
    """Job has expired or is no longer available"""

    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job has expired: {job_id}",
            job_id=job_id,
            code="JOB_EXPIRED",
            recoverable=False,
        )


class JobAlreadyAppliedError(JobException):
    """Already applied to this job"""

    def __init__(self, job_id: str, agent_id: str):
        super().__init__(
            message=f"Already applied to job {job_id}",
            job_id=job_id,
            code="JOB_ALREADY_APPLIED",
            details={"agent_id": agent_id},
            recoverable=False,
        )


class JobExecutionError(JobException):
    """Error during job execution"""

    def __init__(self, job_id: str, stage: str, error: str):
        super().__init__(
            message=f"Job execution failed at {stage}: {error}",
            job_id=job_id,
            code="JOB_EXECUTION_ERROR",
            details={"stage": stage, "error": error},
            recoverable=True,
        )


# ===========================================
# Platform Exceptions
# ===========================================


class PlatformException(WorkforceException):
    """Base exception for platform-related errors"""

    def __init__(
        self,
        message: str,
        platform: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        self.platform = platform
        if platform:
            self.details["platform"] = platform


class PlatformAuthError(PlatformException):
    """Authentication failed with platform"""

    def __init__(self, platform: str, reason: str):
        super().__init__(
            message=f"Authentication failed for {platform}: {reason}",
            platform=platform,
            code="PLATFORM_AUTH_ERROR",
            details={"reason": reason},
            recoverable=True,
        )


class PlatformRateLimitError(PlatformException):
    """Rate limited by platform"""

    def __init__(self, platform: str, retry_after: Optional[int] = None):
        super().__init__(
            message=f"Rate limited by {platform}",
            platform=platform,
            code="PLATFORM_RATE_LIMIT",
            details={"retry_after_seconds": retry_after},
            recoverable=True,
        )
        self.retry_after = retry_after


class PlatformBanError(PlatformException):
    """Account banned or restricted on platform"""

    def __init__(self, platform: str, agent_id: str, reason: str):
        super().__init__(
            message=f"Account restricted on {platform}: {reason}",
            platform=platform,
            code="PLATFORM_BAN",
            details={"agent_id": agent_id, "reason": reason},
            recoverable=False,
        )


class PlatformUnavailableError(PlatformException):
    """Platform is temporarily unavailable"""

    def __init__(self, platform: str):
        super().__init__(
            message=f"Platform temporarily unavailable: {platform}",
            platform=platform,
            code="PLATFORM_UNAVAILABLE",
            recoverable=True,
        )


# ===========================================
# Quality Exceptions
# ===========================================


class QualityException(WorkforceException):
    """Base exception for quality-related errors"""

    pass


class QualityCheckFailedError(QualityException):
    """Deliverable failed quality checks"""

    def __init__(self, job_id: str, failed_checks: list[dict]):
        super().__init__(
            message=f"Quality check failed for job {job_id}",
            code="QUALITY_CHECK_FAILED",
            details={"job_id": job_id, "failed_checks": failed_checks},
            recoverable=True,
        )
        self.failed_checks = failed_checks


class PlagiarismDetectedError(QualityException):
    """Plagiarism detected in content"""

    def __init__(self, job_id: str, similarity_score: float, sources: list[str]):
        super().__init__(
            message=f"Plagiarism detected: {similarity_score:.1%} similarity",
            code="PLAGIARISM_DETECTED",
            details={
                "job_id": job_id,
                "similarity_score": similarity_score,
                "sources": sources,
            },
            recoverable=True,
        )


class AIDetectionError(QualityException):
    """Content flagged as AI-generated"""

    def __init__(self, job_id: str, detection_score: float):
        super().__init__(
            message=f"AI detection score too high: {detection_score:.1%}",
            code="AI_DETECTION_HIGH",
            details={"job_id": job_id, "detection_score": detection_score},
            recoverable=True,
        )


# ===========================================
# Rate Limit Exceptions
# ===========================================


class RateLimitException(WorkforceException):
    """Base exception for rate limiting"""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current: int,
        maximum: int,
        reset_at: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(
            message,
            code="RATE_LIMIT_EXCEEDED",
            details={
                "limit_type": limit_type,
                "current": current,
                "maximum": maximum,
                "reset_at": reset_at,
            },
            recoverable=True,
            **kwargs,
        )
        self.limit_type = limit_type
        self.current = current
        self.maximum = maximum
        self.reset_at = reset_at


class ProposalRateLimitError(RateLimitException):
    """Too many proposals submitted"""

    def __init__(self, agent_id: str, current: int, maximum: int):
        super().__init__(
            message=f"Proposal limit exceeded for agent {agent_id}",
            limit_type="proposals",
            current=current,
            maximum=maximum,
        )
        self.details["agent_id"] = agent_id


class MessageRateLimitError(RateLimitException):
    """Too many messages sent"""

    def __init__(self, agent_id: str, current: int, maximum: int):
        super().__init__(
            message=f"Message limit exceeded for agent {agent_id}",
            limit_type="messages",
            current=current,
            maximum=maximum,
        )
        self.details["agent_id"] = agent_id


# ===========================================
# LLM Exceptions
# ===========================================


class LLMException(WorkforceException):
    """Base exception for LLM-related errors"""

    pass


class LLMProviderError(LLMException):
    """Error from LLM provider"""

    def __init__(self, provider: str, error: str):
        super().__init__(
            message=f"LLM provider error ({provider}): {error}",
            code="LLM_PROVIDER_ERROR",
            details={"provider": provider, "error": error},
            recoverable=True,
        )


class LLMRateLimitError(LLMException):
    """Rate limited by LLM provider"""

    def __init__(self, provider: str, retry_after: Optional[int] = None):
        super().__init__(
            message=f"LLM rate limited ({provider})",
            code="LLM_RATE_LIMIT",
            details={"provider": provider, "retry_after": retry_after},
            recoverable=True,
        )


class LLMContextLengthError(LLMException):
    """Context length exceeded"""

    def __init__(self, provider: str, tokens: int, max_tokens: int):
        super().__init__(
            message=f"Context length exceeded: {tokens}/{max_tokens} tokens",
            code="LLM_CONTEXT_LENGTH",
            details={"provider": provider, "tokens": tokens, "max_tokens": max_tokens},
            recoverable=True,
        )


# ===========================================
# Configuration Exceptions
# ===========================================


class ConfigurationError(WorkforceException):
    """Configuration error"""

    def __init__(self, message: str, config_key: Optional[str] = None):
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            details={"config_key": config_key} if config_key else {},
            recoverable=False,
        )
