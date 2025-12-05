"""
Base Platform Client - Abstract interface for all platform integrations
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional


@dataclass
class RawJob:
    """
    Raw job data from a platform.
    Standardized format for all platforms.
    """

    # Required fields
    platform: str
    platform_job_id: str
    title: str
    description: str

    # Source
    source_url: Optional[str] = None

    # Category
    category: Optional[str] = None
    subcategory: Optional[str] = None

    # Budget
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    budget_type: Optional[str] = None  # 'fixed', 'hourly', 'monthly'
    currency: Optional[str] = "USD"

    # Requirements
    skills_required: list[str] = field(default_factory=list)
    experience_level: Optional[str] = None
    estimated_hours: Optional[Decimal] = None
    estimated_duration: Optional[str] = None

    # Client info
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    client_country: Optional[str] = None
    client_rating: Optional[Decimal] = None
    client_reviews_count: Optional[int] = None
    client_total_spent: Optional[Decimal] = None
    client_jobs_posted: Optional[int] = None
    client_hire_rate: Optional[Decimal] = None

    # Competition
    applicant_count: Optional[int] = None
    interview_count: Optional[int] = None

    # Timing
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Raw data for debugging
    raw_data: Optional[dict[str, Any]] = None


@dataclass
class PlatformCredentials:
    """Credentials for authenticating with a platform"""

    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    cookies: Optional[dict[str, str]] = None
    extra: Optional[dict[str, Any]] = None


class BasePlatformClient(ABC):
    """
    Abstract base class for platform integrations.

    Each platform must implement:
    - fetch_jobs(): Get list of available jobs
    - get_job_details(): Get detailed info for a specific job
    - submit_proposal(): Submit a bid/proposal for a job
    - get_messages(): Get messages for active jobs
    - send_message(): Send a message to a client
    """

    def __init__(
        self,
        credentials: Optional[PlatformCredentials] = None,
        rate_limit_delay: float = 1.0,
    ):
        self.credentials = credentials
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time: Optional[datetime] = None

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier"""
        pass

    @property
    @abstractmethod
    def requires_authentication(self) -> bool:
        """Whether this platform requires auth for job fetching"""
        pass

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the platform.
        Returns True if successful.
        """
        pass

    @abstractmethod
    async def fetch_jobs(
        self,
        category: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[RawJob]:
        """
        Fetch available jobs from the platform.

        Args:
            category: Optional category filter
            keywords: Optional keyword filters
            limit: Maximum number of jobs to fetch

        Returns:
            List of RawJob objects
        """
        pass

    @abstractmethod
    async def get_job_details(self, job_id: str) -> Optional[RawJob]:
        """
        Get detailed information for a specific job.

        Args:
            job_id: Platform-specific job identifier

        Returns:
            RawJob with full details or None if not found
        """
        pass

    @abstractmethod
    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Submit a proposal/bid for a job.

        Args:
            job_id: Platform-specific job identifier
            cover_letter: Proposal text
            bid_amount: Proposed amount
            **kwargs: Platform-specific additional parameters

        Returns:
            Dict with submission result (success, proposal_id, etc.)
        """
        pass

    @abstractmethod
    async def get_messages(
        self,
        conversation_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """
        Get messages from conversations.

        Args:
            conversation_id: Specific conversation to fetch
            since: Only get messages after this time

        Returns:
            List of message dictionaries
        """
        pass

    @abstractmethod
    async def send_message(
        self,
        conversation_id: str,
        content: str,
        attachments: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Send a message in a conversation.

        Args:
            conversation_id: Platform conversation identifier
            content: Message text
            attachments: Optional file attachments

        Returns:
            Dict with send result
        """
        pass

    async def check_rate_limit(self) -> None:
        """Respect rate limits between requests"""
        import asyncio

        if self._last_request_time:
            elapsed = (datetime.utcnow() - self._last_request_time).total_seconds()
            if elapsed < self.rate_limit_delay:
                await asyncio.sleep(self.rate_limit_delay - elapsed)

        self._last_request_time = datetime.utcnow()

    async def health_check(self) -> dict[str, Any]:
        """Check if platform connection is healthy"""
        return {
            "platform": self.platform_name,
            "authenticated": bool(self.credentials),
            "healthy": True,
        }
