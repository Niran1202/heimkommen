"""Tiny TTL cache: Redis when configured and reachable, otherwise in-process."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from app.core.config import get_settings

log = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, redis_url: str | None = None) -> None:
        self._local: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._redis = None
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
                client.ping()
                self._redis = client
            except Exception:  # pragma: no cover - depends on environment
                log.warning("redis at %s not reachable; using in-process cache", redis_url)

    def get(self, key: str) -> Any | None:
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                return json.loads(raw) if raw else None
            except Exception:  # pragma: no cover
                log.warning("redis get failed", exc_info=True)
        with self._lock:
            item = self._local.get(key)
            if item is None or item[0] < time.monotonic():
                self._local.pop(key, None)
                return None
            return json.loads(item[1])

    def set(self, key: str, value: Any, ttl: int) -> None:
        raw = json.dumps(value)
        if self._redis is not None:
            try:
                self._redis.setex(key, ttl, raw)
                return
            except Exception:  # pragma: no cover
                log.warning("redis set failed", exc_info=True)
        with self._lock:
            if len(self._local) > 5000:
                self._local.clear()
            self._local[key] = (time.monotonic() + ttl, raw)


_cache: TTLCache | None = None


def get_cache() -> TTLCache:
    global _cache
    if _cache is None:
        _cache = TTLCache(get_settings().redis_url)
    return _cache
