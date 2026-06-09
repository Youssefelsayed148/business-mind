import hashlib
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None
_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: int


def get_client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _hash_part(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def rate_limit_key(*parts: str) -> str:
    return "rl:" + ":".join(_hash_part(part.lower()) for part in parts)


def rate_limit(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    now = int(time.time())
    reset_at = now + window_seconds
    if not settings.RATE_LIMIT_ENABLED:
        return RateLimitResult(True, limit, limit, reset_at, 0)

    try:
        client = _redis()
        count, ttl = client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
        if ttl < 0:
            client.expire(key, window_seconds)
            ttl = window_seconds
        reset_at = now + ttl
        remaining = max(limit - int(count), 0)
        allowed = int(count) <= limit
        return RateLimitResult(allowed, limit, remaining, reset_at, max(ttl, 1) if not allowed else 0)
    except RedisError:
        logger.exception("Rate limiter Redis operation failed")
        return RateLimitResult(True, limit, limit, reset_at, 0)


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_at),
    }
    if not result.allowed:
        headers["Retry-After"] = str(result.retry_after)
    return headers


def raise_rate_limited(result: RateLimitResult, detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers=rate_limit_headers(result),
    )


def enforce_rate_limit(key: str, limit: int, window_seconds: int, detail: str) -> RateLimitResult:
    result = rate_limit(key, limit, window_seconds)
    if not result.allowed:
        raise_rate_limited(result, detail)
    return result


def enforce_ip_rate_limit(request: Request, name: str, limit: int, window_seconds: int, detail: str) -> RateLimitResult:
    return enforce_rate_limit(
        rate_limit_key(name, get_client_ip(request)),
        limit,
        window_seconds,
        detail,
    )


def enforce_user_rate_limit(user: User, name: str, limit: int, window_seconds: int, detail: str) -> RateLimitResult:
    return enforce_rate_limit(
        rate_limit_key(name, str(user.id)),
        limit,
        window_seconds,
        detail,
    )


def check_login_rate_limits(request: Request, email: str) -> tuple[RateLimitResult, str] | None:
    ip = get_client_ip(request)
    checks = [
        (
            rate_limit_key("login_email_ip", ip, email),
            settings.LOGIN_EMAIL_IP_LIMIT,
            settings.LOGIN_EMAIL_IP_WINDOW_SECONDS,
            "email_ip",
        ),
        (
            rate_limit_key("login_ip", ip),
            settings.LOGIN_IP_LIMIT,
            settings.LOGIN_IP_WINDOW_SECONDS,
            "ip",
        ),
    ]
    for key, limit, window_seconds, window_name in checks:
        result = rate_limit(key, limit, window_seconds)
        if not result.allowed:
            return result, window_name
    return None
