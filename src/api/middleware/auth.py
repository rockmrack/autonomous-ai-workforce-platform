"""
Authentication Middleware
Provides API key authentication for protected endpoints
"""

import hashlib
import hmac
import secrets
from functools import wraps
from typing import Annotated, Callable, Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import structlog

logger = structlog.get_logger(__name__)

# API Key can be passed in header or query parameter
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for API key authentication.

    Allows:
    - Public endpoints (health, docs)
    - Authenticated endpoints (all others)
    """

    # Endpoints that don't require authentication
    PUBLIC_PATHS = {
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/health",
    }

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key_hash = self._hash_key(api_key)

    @staticmethod
    def _hash_key(key: str) -> str:
        """Hash API key for secure comparison"""
        return hashlib.sha256(key.encode()).hexdigest()

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public"""
        # Exact match
        if path in self.PUBLIC_PATHS:
            return True
        # Prefix match for docs
        if path.startswith("/docs") or path.startswith("/redoc"):
            return True
        return False

    def _verify_key(self, provided_key: Optional[str]) -> bool:
        """Securely compare provided key with stored hash"""
        if not provided_key:
            return False
        provided_hash = self._hash_key(provided_key)
        return hmac.compare_digest(provided_hash, self.api_key_hash)

    async def dispatch(self, request: Request, call_next):
        # Allow public endpoints
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Get API key from header or query
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

        # Verify key
        if not self._verify_key(api_key):
            logger.warning(
                "Authentication failed",
                path=request.url.path,
                client_ip=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # Add auth info to request state
        request.state.authenticated = True
        return await call_next(request)


async def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
) -> str:
    """
    Dependency to extract API key from request.
    Checks header first, then query parameter.
    """
    return api_key_header or api_key_query


async def get_current_api_key(
    api_key: str = Depends(get_api_key),
) -> str:
    """
    Dependency to validate and return API key.
    Use this in endpoints that need the actual key value.
    """
    from config import settings

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    expected_key = settings.api_key.get_secret_value()
    if not hmac.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


def require_auth(func: Callable) -> Callable:
    """
    Decorator to require authentication on an endpoint.
    Use when you need explicit auth checking beyond middleware.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Get request from kwargs or first arg
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if request and not getattr(request.state, "authenticated", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        return await func(*args, **kwargs)

    return wrapper


def generate_api_key() -> str:
    """Generate a secure random API key"""
    return secrets.token_urlsafe(32)
