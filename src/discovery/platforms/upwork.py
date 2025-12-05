"""
Upwork Platform Client
Integration with Upwork API for job discovery and proposals
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
import structlog

from .base import BasePlatformClient, PlatformCredentials, RawJob

logger = structlog.get_logger(__name__)


class UpworkClient(BasePlatformClient):
    """
    Upwork platform integration.

    Uses Upwork API v3 for authenticated operations.
    Note: Upwork API access requires approval from Upwork.
    """

    BASE_URL = "https://www.upwork.com/api"
    API_VERSION = "v3"

    def __init__(
        self,
        credentials: Optional[PlatformCredentials] = None,
        rate_limit_delay: float = 2.0,
    ):
        super().__init__(credentials, rate_limit_delay)
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None

    @property
    def platform_name(self) -> str:
        return "upwork"

    @property
    def requires_authentication(self) -> bool:
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "AI-Workforce-Platform/2.0",
                },
            )
        return self._client

    async def authenticate(self) -> bool:
        """
        Authenticate with Upwork OAuth2.

        Upwork uses OAuth 2.0 with access/refresh tokens.
        The initial OAuth flow needs to be done manually.
        """
        if not self.credentials:
            logger.error("No credentials provided for Upwork")
            return False

        # If we have an access token, use it
        if self.credentials.access_token:
            self._access_token = self.credentials.access_token
            return True

        # Otherwise, try to get a new token using refresh token
        if self.credentials.refresh_token:
            try:
                client = await self._get_client()
                response = await client.post(
                    "/auth/v2/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.credentials.refresh_token,
                        "client_id": self.credentials.api_key,
                        "client_secret": self.credentials.api_secret,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    self._access_token = data.get("access_token")
                    # Update refresh token if provided
                    if "refresh_token" in data:
                        self.credentials.refresh_token = data["refresh_token"]
                    return True
                else:
                    logger.error(
                        "Failed to refresh Upwork token",
                        status=response.status_code,
                        response=response.text,
                    )
            except Exception as e:
                logger.error("Upwork authentication error", error=str(e))

        return False

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Optional[dict]:
        """Make authenticated API request"""
        await self.check_rate_limit()

        client = await self._get_client()

        headers = kwargs.pop("headers", {})
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            response = await client.request(
                method,
                f"/{self.API_VERSION}{endpoint}",
                headers=headers,
                **kwargs,
            )

            if response.status_code == 401:
                # Token expired, try to refresh
                if await self.authenticate():
                    # Retry request
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    response = await client.request(
                        method,
                        f"/{self.API_VERSION}{endpoint}",
                        headers=headers,
                        **kwargs,
                    )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(
                    "Upwork API error",
                    endpoint=endpoint,
                    status=response.status_code,
                    response=response.text[:200],
                )
                return None

        except Exception as e:
            logger.error(
                "Upwork request failed",
                endpoint=endpoint,
                error=str(e),
            )
            return None

    async def fetch_jobs(
        self,
        category: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[RawJob]:
        """Fetch jobs from Upwork"""
        jobs = []

        # Build search query
        params = {
            "paging": f"0;{limit}",
            "sort": "recency",
        }

        if keywords:
            params["q"] = " ".join(keywords)

        if category:
            params["category2"] = category

        # Search for jobs
        data = await self._make_request(
            "GET",
            "/profiles/v2/search/jobs.json",
            params=params,
        )

        if not data or "jobs" not in data:
            return jobs

        for job_data in data.get("jobs", []):
            try:
                raw_job = self._parse_job(job_data)
                jobs.append(raw_job)
            except Exception as e:
                logger.warning(
                    "Failed to parse Upwork job",
                    error=str(e),
                    job_data=str(job_data)[:200],
                )

        logger.info("Fetched Upwork jobs", count=len(jobs))
        return jobs

    def _parse_job(self, data: dict) -> RawJob:
        """Parse Upwork job data into RawJob"""
        # Extract budget info
        budget_min = None
        budget_max = None
        budget_type = data.get("job_type", "").lower()

        if "budget" in data:
            budget = data["budget"]
            if isinstance(budget, dict):
                budget_min = Decimal(str(budget.get("min", 0)))
                budget_max = Decimal(str(budget.get("max", 0)))
            elif isinstance(budget, (int, float)):
                budget_max = Decimal(str(budget))

        if budget_type == "hourly" and "hourly_rate" in data:
            rate = data["hourly_rate"]
            if isinstance(rate, dict):
                budget_min = Decimal(str(rate.get("min", 0)))
                budget_max = Decimal(str(rate.get("max", 0)))

        # Extract client info
        client = data.get("client", {})

        # Extract skills
        skills = []
        if "skills" in data:
            skills = [s.get("name", s) if isinstance(s, dict) else s for s in data["skills"]]
        elif "op_required_skills" in data:
            skills = data["op_required_skills"]

        return RawJob(
            platform="upwork",
            platform_job_id=data.get("id", data.get("ciphertext", "")),
            title=data.get("title", ""),
            description=data.get("snippet", data.get("description", "")),
            source_url=f"https://www.upwork.com/jobs/{data.get('ciphertext', '')}",
            category=data.get("category2"),
            subcategory=data.get("subcategory2"),
            budget_min=budget_min,
            budget_max=budget_max,
            budget_type="hourly" if "hourly" in budget_type else "fixed",
            currency="USD",
            skills_required=skills,
            experience_level=data.get("contractor_tier"),
            estimated_duration=data.get("duration"),
            client_id=client.get("id"),
            client_country=client.get("country"),
            client_rating=Decimal(str(client.get("feedback", 0))) if client.get("feedback") else None,
            client_reviews_count=client.get("reviews_count"),
            client_total_spent=Decimal(str(client.get("total_spent", 0))) if client.get("total_spent") else None,
            client_jobs_posted=client.get("jobs_posted"),
            client_hire_rate=Decimal(str(client.get("hire_rate", 0) / 100)) if client.get("hire_rate") else None,
            applicant_count=data.get("total_applicants", 0),
            interview_count=data.get("total_interviews", 0),
            posted_at=datetime.fromisoformat(data["date_created"].replace("Z", "+00:00")) if data.get("date_created") else None,
            raw_data=data,
        )

    async def get_job_details(self, job_id: str) -> Optional[RawJob]:
        """Get detailed job information"""
        data = await self._make_request(
            "GET",
            f"/profiles/v1/jobs/{job_id}.json",
        )

        if not data or "profile" not in data:
            return None

        return self._parse_job(data["profile"])

    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Submit a proposal to a job"""
        # Get job details first
        job = await self.get_job_details(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        # Build proposal payload
        payload = {
            "cover_letter": cover_letter,
            "engagement_duration": kwargs.get("duration", "less_than_1_month"),
        }

        if job.budget_type == "hourly":
            payload["charge_rate"] = float(bid_amount)
        else:
            payload["amount"] = float(bid_amount)

        # Add milestones if provided
        if "milestones" in kwargs:
            payload["milestones"] = kwargs["milestones"]

        # Add answers to screening questions if provided
        if "questions" in kwargs:
            payload["questions"] = kwargs["questions"]

        data = await self._make_request(
            "POST",
            f"/offers/v1/jobs/{job_id}/proposals.json",
            json=payload,
        )

        if data and "reference" in data:
            return {
                "success": True,
                "proposal_id": data["reference"],
                "data": data,
            }

        return {
            "success": False,
            "error": "Failed to submit proposal",
            "data": data,
        }

    async def get_messages(
        self,
        conversation_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Get messages from Upwork"""
        messages = []

        params = {}
        if conversation_id:
            params["room_id"] = conversation_id
        if since:
            params["after"] = since.isoformat()

        data = await self._make_request(
            "GET",
            "/messages/v3/rooms.json",
            params=params,
        )

        if not data or "rooms" not in data:
            return messages

        # If we have a specific conversation, get its messages
        if conversation_id:
            msg_data = await self._make_request(
                "GET",
                f"/messages/v3/rooms/{conversation_id}/stories.json",
            )
            if msg_data and "stories" in msg_data:
                for story in msg_data["stories"]:
                    messages.append({
                        "id": story.get("id"),
                        "content": story.get("message"),
                        "sender": story.get("user_id"),
                        "timestamp": story.get("created_time"),
                        "conversation_id": conversation_id,
                        "raw": story,
                    })
        else:
            # Return rooms list for overview
            for room in data["rooms"]:
                messages.append({
                    "conversation_id": room.get("roomId"),
                    "title": room.get("roomName"),
                    "last_message": room.get("lastStory", {}).get("message"),
                    "unread_count": room.get("unreadCount", 0),
                    "raw": room,
                })

        return messages

    async def send_message(
        self,
        conversation_id: str,
        content: str,
        attachments: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Send a message in an Upwork conversation"""
        payload = {
            "message": content,
        }

        if attachments:
            payload["attachments"] = attachments

        data = await self._make_request(
            "POST",
            f"/messages/v3/rooms/{conversation_id}/stories.json",
            json=payload,
        )

        if data and "story" in data:
            return {
                "success": True,
                "message_id": data["story"].get("id"),
                "data": data,
            }

        return {
            "success": False,
            "error": "Failed to send message",
        }

    async def close(self) -> None:
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
