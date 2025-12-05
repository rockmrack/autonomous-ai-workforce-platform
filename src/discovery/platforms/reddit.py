"""
Reddit Platform Client
Integration with Reddit for finding jobs in hiring subreddits
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
import structlog

from .base import BasePlatformClient, PlatformCredentials, RawJob

logger = structlog.get_logger(__name__)


class RedditClient(BasePlatformClient):
    """
    Reddit platform integration.

    Monitors subreddits like r/forhire, r/slavelabour, r/HireAWriter, etc.
    Uses Reddit's OAuth API.
    """

    BASE_URL = "https://oauth.reddit.com"
    AUTH_URL = "https://www.reddit.com/api/v1"

    # Subreddits to monitor for jobs
    HIRING_SUBREDDITS = [
        "forhire",
        "slavelabour",
        "HireAWriter",
        "hiring",
        "jobbit",
        "remotejs",
        "ProgrammingBuddies",
    ]

    # Patterns to identify hiring posts (look for [Hiring] tag)
    HIRING_PATTERNS = [
        r"\[hiring\]",
        r"\[for hire\]",
        r"looking to hire",
        r"need a",
        r"looking for a",
    ]

    def __init__(
        self,
        credentials: Optional[PlatformCredentials] = None,
        rate_limit_delay: float = 1.0,
        subreddits: Optional[list[str]] = None,
    ):
        super().__init__(credentials, rate_limit_delay)
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self.subreddits = subreddits or self.HIRING_SUBREDDITS

    @property
    def platform_name(self) -> str:
        return "reddit"

    @property
    def requires_authentication(self) -> bool:
        return True  # OAuth required for better rate limits

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "AI-Workforce-Platform/2.0",
                },
            )
        return self._client

    async def authenticate(self) -> bool:
        """Authenticate with Reddit OAuth2"""
        if not self.credentials:
            logger.error("No credentials provided for Reddit")
            return False

        try:
            client = await self._get_client()

            # Reddit uses HTTP Basic Auth for token requests
            auth = (self.credentials.api_key, self.credentials.api_secret)

            response = await client.post(
                f"{self.AUTH_URL}/access_token",
                auth=auth,
                data={
                    "grant_type": "client_credentials",
                },
                headers={
                    "User-Agent": self.credentials.extra.get("user_agent", "AI-Workforce/2.0")
                    if self.credentials.extra
                    else "AI-Workforce/2.0",
                },
            )

            if response.status_code == 200:
                data = response.json()
                self._access_token = data.get("access_token")
                logger.info("Reddit authentication successful")
                return True
            else:
                logger.error(
                    "Reddit authentication failed",
                    status=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            logger.error("Reddit authentication error", error=str(e))
            return False

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        **kwargs: Any,
    ) -> Optional[dict]:
        """Make authenticated API request"""
        await self.check_rate_limit()

        client = await self._get_client()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers["User-Agent"] = "AI-Workforce-Platform/2.0"

        try:
            response = await client.request(
                method,
                f"{self.BASE_URL}{endpoint}",
                headers=headers,
                **kwargs,
            )

            if response.status_code == 401:
                # Token expired, refresh
                if await self.authenticate():
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    response = await client.request(
                        method,
                        f"{self.BASE_URL}{endpoint}",
                        headers=headers,
                        **kwargs,
                    )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(
                    "Reddit API error",
                    endpoint=endpoint,
                    status=response.status_code,
                )
                return None

        except Exception as e:
            logger.error("Reddit request failed", endpoint=endpoint, error=str(e))
            return None

    async def fetch_jobs(
        self,
        category: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[RawJob]:
        """Fetch hiring posts from Reddit"""
        jobs = []

        # Determine which subreddits to search
        subreddits = self.subreddits
        if category and category in subreddits:
            subreddits = [category]

        for subreddit in subreddits:
            try:
                subreddit_jobs = await self._fetch_subreddit_jobs(
                    subreddit,
                    keywords,
                    limit // len(subreddits),
                )
                jobs.extend(subreddit_jobs)
            except Exception as e:
                logger.warning(
                    "Failed to fetch from subreddit",
                    subreddit=subreddit,
                    error=str(e),
                )

        logger.info("Fetched Reddit jobs", count=len(jobs))
        return jobs

    async def _fetch_subreddit_jobs(
        self,
        subreddit: str,
        keywords: Optional[list[str]],
        limit: int,
    ) -> list[RawJob]:
        """Fetch jobs from a specific subreddit"""
        jobs = []

        # Build search query
        if keywords:
            query = " OR ".join(keywords)
            endpoint = f"/r/{subreddit}/search.json"
            params = {
                "q": query,
                "restrict_sr": "true",
                "sort": "new",
                "limit": limit,
                "t": "week",  # Posts from last week
            }
        else:
            # Just get new posts
            endpoint = f"/r/{subreddit}/new.json"
            params = {"limit": limit}

        data = await self._make_request(endpoint, params=params)

        if not data or "data" not in data:
            return jobs

        for post in data["data"].get("children", []):
            post_data = post.get("data", {})

            # Check if this is a hiring post
            if not self._is_hiring_post(post_data):
                continue

            try:
                raw_job = self._parse_post(post_data, subreddit)
                jobs.append(raw_job)
            except Exception as e:
                logger.warning(
                    "Failed to parse Reddit post",
                    error=str(e),
                    post_id=post_data.get("id"),
                )

        return jobs

    def _is_hiring_post(self, post: dict) -> bool:
        """Check if post is a hiring post"""
        title = post.get("title", "").lower()
        flair = post.get("link_flair_text", "").lower()

        # Check flair
        if "hiring" in flair:
            return True

        # Check title patterns
        for pattern in self.HIRING_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE):
                return True

        return False

    def _parse_post(self, post: dict, subreddit: str) -> RawJob:
        """Parse Reddit post into RawJob"""
        title = post.get("title", "")
        body = post.get("selftext", "")
        full_text = f"{title} {body}"

        # Extract budget from text
        budget = self._extract_budget(full_text)

        # Extract skills from text
        skills = self._extract_skills(full_text)

        # Calculate category based on subreddit
        category = self._subreddit_to_category(subreddit)

        return RawJob(
            platform="reddit",
            platform_job_id=post.get("id", ""),
            title=title,
            description=body or title,
            source_url=f"https://www.reddit.com{post.get('permalink', '')}",
            category=category,
            subcategory=subreddit,
            budget_min=budget.get("min"),
            budget_max=budget.get("max"),
            budget_type=budget.get("type", "fixed"),
            currency="USD",
            skills_required=skills,
            client_name=post.get("author", "[deleted]"),
            applicant_count=post.get("num_comments", 0),
            posted_at=datetime.fromtimestamp(post.get("created_utc", 0)),
            raw_data=post,
        )

    def _extract_budget(self, text: str) -> dict:
        """Extract budget information from post text"""
        budget: dict[str, Any] = {}

        # Look for dollar amounts
        patterns = [
            r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:-|to)\s*\$?(\d+(?:,\d{3})*(?:\.\d{2})?)",  # Range
            r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:per\s*)?(?:hour|hr|h)",  # Hourly
            r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:flat|fixed|total|budget)?",  # Single amount
        ]

        text_lower = text.lower()

        for i, pattern in enumerate(patterns):
            match = re.search(pattern, text_lower)
            if match:
                if i == 0:  # Range
                    budget["min"] = Decimal(match.group(1).replace(",", ""))
                    budget["max"] = Decimal(match.group(2).replace(",", ""))
                    budget["type"] = "fixed"
                elif i == 1:  # Hourly
                    amount = Decimal(match.group(1).replace(",", ""))
                    budget["min"] = amount
                    budget["max"] = amount
                    budget["type"] = "hourly"
                else:  # Single amount
                    amount = Decimal(match.group(1).replace(",", ""))
                    budget["max"] = amount
                    budget["type"] = "fixed"
                break

        return budget

    def _extract_skills(self, text: str) -> list[str]:
        """Extract skills from post text"""
        skills = []
        text_lower = text.lower()

        # Common skills to look for
        skill_patterns = {
            "python": ["python", "py"],
            "javascript": ["javascript", "js", "nodejs", "node.js"],
            "react": ["react", "reactjs"],
            "writing": ["writing", "writer", "content", "blog", "article"],
            "data entry": ["data entry", "spreadsheet", "excel"],
            "web scraping": ["scraping", "scraper", "web scraping"],
            "research": ["research", "researcher"],
            "seo": ["seo", "search engine"],
            "design": ["design", "designer", "figma", "photoshop"],
            "wordpress": ["wordpress", "wp"],
            "api": ["api", "rest", "graphql"],
        }

        for skill_name, patterns in skill_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    skills.append(skill_name)
                    break

        return list(set(skills))

    def _subreddit_to_category(self, subreddit: str) -> str:
        """Map subreddit to job category"""
        mappings = {
            "forhire": "general",
            "slavelabour": "micro_tasks",
            "HireAWriter": "writing",
            "hiring": "general",
            "remotejs": "programming",
            "ProgrammingBuddies": "programming",
        }
        return mappings.get(subreddit, "general")

    async def get_job_details(self, job_id: str) -> Optional[RawJob]:
        """Get detailed information for a Reddit post"""
        data = await self._make_request(f"/api/info.json?id=t3_{job_id}")

        if not data or "data" not in data:
            return None

        posts = data["data"].get("children", [])
        if not posts:
            return None

        post_data = posts[0].get("data", {})
        return self._parse_post(post_data, post_data.get("subreddit", ""))

    async def submit_proposal(
        self,
        job_id: str,
        cover_letter: str,
        bid_amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Submit a proposal (comment/PM) on Reddit.

        Note: Reddit job responses are typically done via:
        1. Comment on the post
        2. Direct message to the author
        """
        # Get post details
        job = await self.get_job_details(job_id)
        if not job:
            return {"success": False, "error": "Post not found"}

        # Try to send as a private message
        response_text = f"{cover_letter}\n\nProposed rate: ${bid_amount}"

        # Send DM to author
        result = await self._make_request(
            "/api/compose",
            method="POST",
            data={
                "api_type": "json",
                "to": job.client_name,
                "subject": f"Re: {job.title[:50]}",
                "text": response_text,
            },
        )

        if result:
            return {
                "success": True,
                "method": "dm",
                "data": result,
            }

        return {
            "success": False,
            "error": "Failed to send message",
        }

    async def get_messages(
        self,
        conversation_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Get Reddit messages"""
        messages = []

        data = await self._make_request("/message/inbox.json?limit=50")

        if not data or "data" not in data:
            return messages

        for msg in data["data"].get("children", []):
            msg_data = msg.get("data", {})

            # Filter by time if needed
            if since:
                msg_time = datetime.fromtimestamp(msg_data.get("created_utc", 0))
                if msg_time < since:
                    continue

            messages.append({
                "id": msg_data.get("id"),
                "content": msg_data.get("body"),
                "sender": msg_data.get("author"),
                "subject": msg_data.get("subject"),
                "timestamp": datetime.fromtimestamp(msg_data.get("created_utc", 0)),
                "conversation_id": msg_data.get("parent_id"),
                "is_read": not msg_data.get("new", False),
                "raw": msg_data,
            })

        return messages

    async def send_message(
        self,
        conversation_id: str,
        content: str,
        attachments: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Reply to a Reddit message"""
        # conversation_id is the parent message ID
        result = await self._make_request(
            "/api/comment",
            method="POST",
            data={
                "api_type": "json",
                "thing_id": conversation_id,
                "text": content,
            },
        )

        if result and "json" in result:
            return {
                "success": True,
                "data": result,
            }

        return {
            "success": False,
            "error": "Failed to send reply",
        }

    async def close(self) -> None:
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
