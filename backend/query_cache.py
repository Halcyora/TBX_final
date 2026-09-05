"""
Redis-backed cache of previously execution-verified SQL, keyed by a normalized question.

Accuracy-first, not just a speed optimization: replaying SQL that has already executed
successfully once is strictly more deterministic than asking a 1.5B model to regenerate SQL
from scratch for a question it has effectively already answered. Every cached entry still gets
re-executed against the live database (never trusted blindly), so a repeat question always
reflects current data.

Never a hard dependency: if Redis isn't reachable, the cache is silently skipped and the normal
generation path runs unaffected.
"""

import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_redis_client = None
_redis_unavailable = False


def _get_client():
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is None:
        try:
            import redis
            client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=0.5,
            )
            client.ping()
            _redis_client = client
        except Exception as e:
            logger.info(f"Verified-query cache disabled (Redis unavailable): {e}")
            _redis_unavailable = True
    return _redis_client


def normalize_question(question: str) -> str:
    """Collapse whitespace/case so near-identical phrasing hits the same cache key.
    # ponytail: exact-match cache, add embedding similarity if paraphrase misses show up in testing
    """
    return re.sub(r"\s+", " ", question.strip().lower())


def get_cached_sql(question: str) -> Optional[str]:
    """Look up SQL for a previously-asked, execution-verified equivalent question."""
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get(f"verified_sql:{normalize_question(question)}")
    except Exception as e:
        logger.warning(f"Verified-query cache read failed: {e}")
        return None


def store_verified_sql(question: str, sql: str) -> None:
    """Cache SQL for reuse. Only call this after the SQL has actually executed without error."""
    client = _get_client()
    if client is None:
        return
    try:
        client.set(f"verified_sql:{normalize_question(question)}", sql)
    except Exception as e:
        logger.warning(f"Verified-query cache write failed: {e}")
