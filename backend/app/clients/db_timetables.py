"""Client for the official DB Timetables API (DB API Marketplace, free plan).

Only called when a user asks for live data; responses are cached for 60 s and requests
are rate limited well below the free plan's 60 calls/minute.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
from defusedxml import ElementTree as ET

from app.core.cache import TTLCache
from app.core.metrics import LIVE_API_CALLS

log = logging.getLogger(__name__)


class LiveDataUnavailable(RuntimeError):
    pass


@dataclass
class TimetableStop:
    stop_id: str
    category: str | None
    number: str | None
    line: str | None
    planned_departure: datetime | None
    changed_departure: datetime | None
    planned_arrival: datetime | None
    changed_arrival: datetime | None
    platform: str | None
    changed_platform: str | None
    cancelled: bool

    @property
    def departure_delay(self) -> int | None:
        if self.planned_departure and self.changed_departure:
            return int((self.changed_departure - self.planned_departure).total_seconds() // 60)
        return 0 if self.planned_departure else None


def parse_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%y%m%d%H%M")
    except ValueError:
        return None


def parse_plan(xml_text: str) -> dict[str, dict]:
    """``/plan`` response -> stop id -> planned data."""
    root = ET.fromstring(xml_text)
    stops = {}
    for s in root.findall("s"):
        tl = s.find("tl")
        ar, dp = s.find("ar"), s.find("dp")
        stops[s.get("id")] = {
            "category": tl.get("c") if tl is not None else None,
            "number": tl.get("n") if tl is not None else None,
            "line": (dp if dp is not None else ar).get("l") if (dp is not None or ar is not None) else None,
            "pt_dep": parse_db_time(dp.get("pt")) if dp is not None else None,
            "pt_arr": parse_db_time(ar.get("pt")) if ar is not None else None,
            "pp": (dp if dp is not None else ar).get("pp") if (dp is not None or ar is not None) else None,
        }
    return stops


def parse_changes(xml_text: str) -> dict[str, dict]:
    """``/fchg`` response -> stop id -> changes."""
    root = ET.fromstring(xml_text)
    changes = {}
    for s in root.findall("s"):
        ar, dp = s.find("ar"), s.find("dp")
        changes[s.get("id")] = {
            "ct_dep": parse_db_time(dp.get("ct")) if dp is not None else None,
            "ct_arr": parse_db_time(ar.get("ct")) if ar is not None else None,
            "cp": (dp.get("cp") if dp is not None else None) or (ar.get("cp") if ar is not None else None),
            "cancelled": any(e is not None and e.get("cs") == "c" for e in (ar, dp)),
        }
    return changes


class DBTimetablesClient:
    def __init__(self, base_url: str, client_id: str, api_key: str, cache: TTLCache, ttl: int = 60,
                 max_per_minute: int = 30, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.api_key = api_key
        self.cache = cache
        self.ttl = ttl
        self.max_per_minute = max_per_minute
        self._calls: list[float] = []
        self._lock = threading.Lock()
        self._http = httpx.Client(timeout=5.0, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.api_key)

    def _allow_call(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < 60]
            if len(self._calls) >= self.max_per_minute:
                return False
            self._calls.append(now)
            return True

    def _get(self, path: str, endpoint: str, ttl: int) -> str:
        key = f"dbapi:{path}"
        cached = self.cache.get(key)
        if cached is not None:
            LIVE_API_CALLS.labels(endpoint, "cache").inc()
            return cached
        if not self.configured:
            raise LiveDataUnavailable("DB API credentials are not configured")
        if not self._allow_call():
            LIVE_API_CALLS.labels(endpoint, "rate_limited").inc()
            raise LiveDataUnavailable("live data rate limit reached, try again in a minute")
        try:
            response = self._http.get(f"{self.base_url}{path}", headers={
                "DB-Client-Id": self.client_id, "DB-Api-Key": self.api_key, "Accept": "application/xml"})
        except httpx.HTTPError as exc:
            LIVE_API_CALLS.labels(endpoint, "error").inc()
            raise LiveDataUnavailable("DB API not reachable") from exc
        if response.status_code == 429:
            LIVE_API_CALLS.labels(endpoint, "rate_limited").inc()
            raise LiveDataUnavailable("DB API rate limit reached")
        if response.status_code == 404:
            LIVE_API_CALLS.labels(endpoint, "not_found").inc()
            return "<timetable/>"
        if response.status_code != 200:
            LIVE_API_CALLS.labels(endpoint, "error").inc()
            raise LiveDataUnavailable(f"DB API returned {response.status_code}")
        LIVE_API_CALLS.labels(endpoint, "ok").inc()
        self.cache.set(key, response.text, ttl)
        return response.text

    def station_stops(self, eva: str, when: datetime) -> list[TimetableStop]:
        """Planned stops for the hour of ``when`` merged with the current changes."""
        plan = parse_plan(self._get(f"/plan/{eva}/{when:%y%m%d}/{when:%H}", "plan", 3600))
        changes = parse_changes(self._get(f"/fchg/{eva}", "fchg", self.ttl))
        stops = []
        for stop_id, p in plan.items():
            c = changes.get(stop_id, {})
            stops.append(TimetableStop(
                stop_id=stop_id, category=p["category"], number=p["number"], line=p["line"],
                planned_departure=p["pt_dep"], changed_departure=c.get("ct_dep") or p["pt_dep"],
                planned_arrival=p["pt_arr"], changed_arrival=c.get("ct_arr") or p["pt_arr"],
                platform=p["pp"], changed_platform=c.get("cp"), cancelled=bool(c.get("cancelled")),
            ))
        return stops
