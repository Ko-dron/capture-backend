import asyncio
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Rate limit rules: (max_requests, window_seconds)
_ROUTE_LIMITS: list[tuple[str, int, int]] = [
    ("/api/auth/login", 5, 60),
    ("/api/auth/register", 3, 60),
    ("/api/media/upload/", 30, 60),     # prefix match
]

_AUTHENTICATED_LIMIT = (100, 60)
_PUBLIC_LIMIT = (60, 60)

# In-memory store: {key: [timestamp, ...]}
_requests: dict[str, list[float]] = defaultdict(list)

# Cleanup interval (seconds)
_CLEANUP_INTERVAL = 300
_last_cleanup = time.monotonic()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _get_limit_for_path(path: str, has_auth: bool) -> tuple[int, int]:
    """Return (max_requests, window_seconds) for a given path."""
    for route_prefix, max_req, window in _ROUTE_LIMITS:
        if path.startswith(route_prefix):
            return (max_req, window)

    if has_auth:
        return _AUTHENTICATED_LIMIT
    return _PUBLIC_LIMIT


def _cleanup_old_entries(now: float) -> None:
    """Remove entries older than 120 seconds to prevent memory leak."""
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    cutoff = now - 120
    keys_to_delete = []
    for key, timestamps in _requests.items():
        _requests[key] = [t for t in timestamps if t > cutoff]
        if not _requests[key]:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del _requests[key]


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = _get_client_ip(request)
        has_auth = "authorization" in request.headers

        max_requests, window = _get_limit_for_path(path, has_auth)
        key = f"{client_ip}:{path}"

        now = time.monotonic()
        _cleanup_old_entries(now)

        # Prune timestamps outside the current window
        cutoff = now - window
        timestamps = _requests[key]
        _requests[key] = [t for t in timestamps if t > cutoff]

        if len(_requests[key]) >= max_requests:
            retry_after = int(window - (now - _requests[key][0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        _requests[key].append(now)

        return await call_next(request)
