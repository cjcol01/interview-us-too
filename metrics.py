"""Lightweight Redis-backed hourly counters, feeding the "Metrics" section of
/admin/health (resend failures, 5xx error rate). Keys are hourly buckets
(`{prefix}:{YYYYMMDDHH}`) with a ~25h TTL, so a rolling 24h sum always has full
data without ever needing a cleanup job.

mailer.py is fully synchronous and has no request/app-state to reach the app's
async Redis client, so it gets its own tiny lazily-created sync client here.
server.py increments/reads the same keys through its existing async client —
this module just centralizes the key names/TTL so both sides agree on them.
Recording a metric must never break the request or email it's instrumenting,
so every write is best-effort and swallows its own errors.
"""
import os
from datetime import datetime

from config import REDIS_URL

METRIC_TTL_SECONDS = 25 * 3600  # >24h so a rolling 24h sum always sees a full day of buckets
EMAIL_FAIL_PREFIX = "metrics:email_fail"
HTTP_5XX_PREFIX = "metrics:5xx"

_sync_redis = None


def hourly_bucket_key(prefix: str, when: datetime = None) -> str:
    return f"{prefix}:{(when or datetime.utcnow()).strftime('%Y%m%d%H')}"


def _get_sync_redis():
    global _sync_redis
    if _sync_redis is None:
        import redis
        _sync_redis = redis.Redis.from_url(
            REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1,
        )
    return _sync_redis


def record_email_failure() -> None:
    """Call from mailer.py's `except` blocks when a Resend send fails."""
    if os.getenv("TESTING") == "1":
        return
    try:
        key = hourly_bucket_key(EMAIL_FAIL_PREFIX)
        r = _get_sync_redis()
        r.incr(key)
        r.expire(key, METRIC_TTL_SECONDS)
    except Exception:
        pass
