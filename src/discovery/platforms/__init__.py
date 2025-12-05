"""Platform integrations for job discovery"""

from .base import BasePlatformClient, RawJob
from .upwork import UpworkClient
from .reddit import RedditClient

__all__ = [
    "BasePlatformClient",
    "RawJob",
    "UpworkClient",
    "RedditClient",
]
