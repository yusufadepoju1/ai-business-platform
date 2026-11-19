"""Small in-memory sliding-window rate limiter (per process, per client IP)."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(name: str, limit: int, window_seconds: int = 60):
    def dep(request: Request):
        if not settings.rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"{name}:{ip}"
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many requests. Please slow down and try again shortly.")
        q.append(now)
    return dep


def reset_limits():
    _hits.clear()
