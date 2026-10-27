"""Configurable rate limits for public authentication endpoints.

The default ``memory://`` backend is process-local and intended for local
development. Multi-worker deployments must configure a shared ``limits``
storage URI or enforce equivalent limits at a trusted ingress.
"""

from __future__ import annotations

from math import ceil
from time import time

from fastapi import HTTPException, Request, status
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from app.core.config import settings

def _build_limiter(storage_uri: str):
    storage = storage_from_string(storage_uri)
    return storage, MovingWindowRateLimiter(storage)


_storage, _limiter = _build_limiter(settings.AUTH_RATE_LIMIT_STORAGE_URI)


def _client_key(request: Request, endpoint: str) -> str:
    # Do not trust X-Forwarded-For without an explicit trusted-proxy policy.
    client_host = request.client.host if request.client else "unknown"
    return f"auth:{endpoint}:{client_host}"


def enforce_auth_rate_limit(request: Request, endpoint: str) -> None:
    configured = (
        settings.AUTH_LOGIN_RATE_LIMIT
        if endpoint == "login"
        else settings.AUTH_REGISTER_RATE_LIMIT
    )
    item = parse(configured)
    key = _client_key(request, endpoint)
    if _limiter.hit(item, key):
        return

    stats = _limiter.get_window_stats(item, key)
    retry_after = max(1, ceil(stats.reset_time - time()))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many authentication attempts. Please try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def reset_auth_rate_limits() -> None:
    """Clear limiter state for isolated tests; not exposed as an API."""
    _storage.reset()
