"""
Fiverr Platform Client

Integration with Fiverr for gig management and buyer requests.
"""

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
import structlog

from src.core.circuit_breaker import circuit_breaker
from src.core.exceptions import PlatformAuthError, PlatformRateLimitError
from .base import BasePlatformClient, PlatformCredentials, RawJob

logger = structlog.get_logger(__name__)


class FiverrClient(BasePlatformClient):
    """
    Fiverr platform integration.

    Features:
    - Buyer request discovery
    - Offer submission
    - Order management
    - Messaging
    """

    BASE_URL = "https://www.fiverr.com"
    API_URL = "https://www.fiverr.com/api"

    def __init__(
        self,
        credentials: Optional[PlatformCredentials] = None,
        rate_limit_delay: float = 3.0,  # Fiverr is stricter
    ):
        super().__init__(credentials, rate_limit_delay)
        self._client: Optional[httpx.AsyncClient] = None
        self._authenticated = False
        self._user_id: Optional[str] = None
        self._csrf_token: Optional[str] = None

    @property
    def platform_name(self) -> str:
        return "fiverr"

    @property
    def requires_authentication(self) -> bool:
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )

            if self.credentials and self.credentials.cookies:
                for name, value in self.credentials.cookies.items():
                    self._client.cookies.set(name, value)

        return self._client

    @circuit_breaker("fiverr_auth", failure_threshold=3, timeout=300)
    async def authenticate(self) -> bool:
        """Authenticate with Fiverr"""
        if not self.credentials:
            raise PlatformAuthError("fiverr", "No credentials provided")

        client = await self._get_client()

        try:
            # Use session cookies for authentication
            if self.credentials.cookies:
                # Verify session
                response = await client.get("/seller_dashboard")
                if response.status_code == 200 and "seller_dashboard" in str(response.url):
                    self._authenticated = True

                    # Extract CSRF token and user info
                    self._extract_session_data(response.text)
                    logger.info("Fiverr authentication successful")
                    return True

            # API key authentication (if available)
            if self.credentials.api_key:
                client.headers["Authorization"] = f"Bearer {self.credentials.api_key}"
                response = await client.get("/api/v1/users/me")
                if response.status_code == 200:
                    data = response.json()
                    self._user_id = data.get("id")
                    self._authenticated = True
                    return True

            return False

        except httpx.HTTPError as e:
            logger.error("Fiverr authentication failed", error=str(e))
            raise PlatformAuthError("fiverr", str(e))

    def _extract_session_data(self, html: str):
        """Extract session data from page"""
        # Extract CSRF token
        csrf_match = re.search(r'"csrfToken":"([^"]+)"', html)
        if csrf_match:
            self._csrf_token = csrf_match.group(1)

        # Extract user ID
        user_match = re.search(r'"userId":"?(\d+)"?', html)
        if user_match:
            self._user_id = user_match.group(1)

    @circuit_breaker("fiverr_api", failure_threshold=5, timeout=60)
    async def fetch_jobs(
        self,
        category: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[RawJob]:
        """Fetch buyer requests from Fiverr"""
        if not self._authenticated:
            await self.authenticate()

        await self.check_rate_limit()
        client = await self._get_client()
        jobs = []

        try:
            # Fetch buyer requests (briefs)
            params = {
                "limit": min(limit, 50),
                "offset": 0,
            }

            if category:
                params["category"] = category

            response = await client.get(
                "/api/v1/seller_dashboard/buyer_requests",
                params=params,
            )

            if response.status_code == 429:
                raise PlatformRateLimitError("fiverr", retry_after=120)

            if response.status_code != 200:
                logger.warning("Fiverr fetch failed", status=response.status_code)
                return []

            data = response.json()

            for request in data.get("buyer_requests", data.get("requests", [])):
                try:
                    raw_job = self._parse_buyer_request(request)
                    jobs.append(raw_job)
                except Exception as e:
                    logger.warning("Failed to parse Fiverr request", error=str(e))

            logger.info("Fetched Fiverr buyer requests", count=len(jobs))
            return jobs

        except httpx.HTTPError as e:
            logger.error("Fiverr fetch failed", error=str(e))
            return []

    def _parse_buyer_request(self, data: dict) -> RawJob:
        """Parse buyer request into RawJob"""
        # Parse budget
        budget = data.get("budget", {})
        if isinstance(budget, dict):
            budget_min = Decimal(str(budget.get("min", 0)))
            budget_max = Decimal(str(budget.get("max", budget_min)))
        elif isinstance(budget, (int, float)):
            budget_min = budget_max = Decimal(str(budget))
        else:
            budget_min = budget_max = Decimal("0")

        # Parse delivery time
        delivery = data.get("expected_delivery", data.get("delivery_time"))
        if isinstance(delivery, int):
            duration = f"{delivery} days"
        elif isinstance(delivery, str):
            duration = delivery
        else:
            duration = None

        # Parse posted date
        posted_at = None
        if data.get("created_at"):
            try:
                posted_at = datetime.fromisoformat(
                    data["created_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return RawJob(
            platform="fiverr",
            platform_job_id=str(data.get("id", "")),
            title=data.get("title", data.get("description", "")[:100]),
            description=data.get("description", ""),
            source_url=f"https://www.fiverr.com/buyer_requests/{data.get('id', '')}",
            category=data.get("category", {}).get("name") if isinstance(data.get("category"), dict) else data.get("category"),
            subcategory=data.get("subcategory", {}).get("name") if isinstance(data.get("subcategory"), dict) else data.get("subcategory"),
            budget_min=budget_min,
            budget_max=budget_max,
            budget_type="fixed",
            currency=data.get("currency", "USD"),
            skills_required=data.get("skills", []),
            estimated_duration=duration,
            client_name=data.get("buyer", {}).get("username"),
            client_country=data.get("buyer", {}).get("country"),
            applicant_count=data.get("offers_count", 0),
            posted_at=posted_at,
            expires_at=self._parse_expiry(data.get("expires_at")),
            raw_data=data,
        )

    def _parse_expiry(self, expiry_str: Optional[str]) -> Optional[datetime]:
        """Parse expiry date"""
        if not expiry_str:
            return None
        try:
            return datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    @circuit_breaker("fiverr_api", failure_threshold=5, timeout=60)
    async def get_job_details(self, job_id: str) -> Optional[RawJob]:
        """Get detailed buyer request information"""
        if not self._authenticated:
            await self.authenticate()

        await self.check_rate_limit()
        client = await self._get_client()

        try:
            response = await client.get(f"/api/v1/buyer_requests/{job_id}")

            if response.status_code != 200:
                return None

            data = response.json()
            return self._parse_buyer_request(data.get("buyer_request", data))

        except httpx.HTTPError as e:
            logger.error("Failed to get request details", job_id=job_id, error=str(e))
            return None

    @circuit_breaker("fiverr_api", failure_threshold=3, timeout=60)
    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Submit an offer to a buyer request"""
        if not self._authenticated:
            await self.authenticate()

        await self.check_rate_limit()
        client = await self._get_client()

        # Fiverr requires linking to an existing gig
        gig_id = kwargs.get("gig_id")
        if not gig_id:
            return {
                "success": False,
                "error": "gig_id required for Fiverr offers",
                "platform": "fiverr",
            }

        payload = {
            "buyer_request_id": job_id,
            "gig_id": gig_id,
            "description": cover_letter,
            "price": float(bid_amount),
            "delivery_time": kwargs.get("delivery_days", 7),
        }

        headers = {}
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token

        try:
            response = await client.post(
                "/api/v1/offers",
                json=payload,
                headers=headers,
            )

            if response.status_code == 429:
                raise PlatformRateLimitError("fiverr", retry_after=300)

            if response.status_code in [200, 201]:
                data = response.json()
                logger.info("Fiverr offer submitted", job_id=job_id)
                return {
                    "success": True,
                    "proposal_id": data.get("offer", {}).get("id", data.get("id")),
                    "platform": "fiverr",
                }

            logger.warning(
                "Fiverr offer submission failed",
                job_id=job_id,
                status=response.status_code,
            )
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "platform": "fiverr",
            }

        except httpx.HTTPError as e:
            logger.error("Fiverr offer submission error", error=str(e))
            return {"success": False, "error": str(e), "platform": "fiverr"}

    async def withdraw_offer(self, offer_id: str) -> dict[str, Any]:
        """Withdraw a submitted offer"""
        if not self._authenticated:
            await self.authenticate()

        client = await self._get_client()

        headers = {}
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token

        try:
            response = await client.delete(
                f"/api/v1/offers/{offer_id}",
                headers=headers,
            )

            if response.status_code in [200, 204]:
                return {"success": True, "platform": "fiverr"}

            return {"success": False, "error": f"HTTP {response.status_code}"}

        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}

    @circuit_breaker("fiverr_api", failure_threshold=5, timeout=60)
    async def get_messages(
        self,
        conversation_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Get messages from Fiverr inbox"""
        if not self._authenticated:
            await self.authenticate()

        await self.check_rate_limit()
        client = await self._get_client()

        try:
            if conversation_id:
                response = await client.get(
                    f"/api/v1/conversations/{conversation_id}/messages"
                )
            else:
                response = await client.get("/api/v1/conversations")

            if response.status_code != 200:
                return []

            data = response.json()
            messages = []

            if conversation_id:
                for msg in data.get("messages", []):
                    message = {
                        "id": msg.get("id"),
                        "conversation_id": conversation_id,
                        "content": msg.get("body", msg.get("text", "")),
                        "sender_id": msg.get("sender_id"),
                        "timestamp": msg.get("created_at"),
                        "is_read": msg.get("is_read", True),
                    }

                    if since:
                        msg_time = self._parse_expiry(msg.get("created_at"))
                        if msg_time and msg_time <= since:
                            continue

                    messages.append(message)
            else:
                for conv in data.get("conversations", []):
                    messages.append({
                        "conversation_id": conv.get("id"),
                        "buyer_username": conv.get("buyer", {}).get("username"),
                        "last_message": conv.get("last_message", {}).get("body"),
                        "unread_count": conv.get("unread_count", 0),
                        "order_id": conv.get("order_id"),
                    })

            return messages

        except httpx.HTTPError as e:
            logger.error("Failed to get Fiverr messages", error=str(e))
            return []

    @circuit_breaker("fiverr_api", failure_threshold=3, timeout=60)
    async def send_message(
        self,
        conversation_id: str,
        content: str,
        attachments: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Send a message on Fiverr"""
        if not self._authenticated:
            await self.authenticate()

        await self.check_rate_limit()
        client = await self._get_client()

        payload = {
            "body": content,
        }

        if attachments:
            payload["attachments"] = attachments

        headers = {}
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token

        try:
            response = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json=payload,
                headers=headers,
            )

            if response.status_code in [200, 201]:
                data = response.json()
                return {
                    "success": True,
                    "message_id": data.get("message", {}).get("id", data.get("id")),
                    "platform": "fiverr",
                }

            return {"success": False, "error": f"HTTP {response.status_code}"}

        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}

    async def get_gigs(self) -> list[dict[str, Any]]:
        """Get seller's gigs"""
        if not self._authenticated:
            await self.authenticate()

        client = await self._get_client()

        try:
            response = await client.get("/api/v1/gigs")

            if response.status_code != 200:
                return []

            data = response.json()
            return data.get("gigs", [])

        except httpx.HTTPError as e:
            logger.error("Failed to get gigs", error=str(e))
            return []

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
