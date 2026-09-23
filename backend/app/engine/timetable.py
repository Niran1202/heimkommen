"""In-memory timetable used by RAPTOR.

The whole regional timetable is loaded once (from the database, cached to a pickle in
``data/``) and split into *patterns*: groups of trips of the same route that call at
exactly the same stop sequence. For a given service date we select the active trips of
each pattern (plus trips of the previous service day that run past midnight).
"""

from __future__ import annotations

import logging
import pickle
import re
import threading
from array import array
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, text

from app.engine.categories import is_rail

log = logging.getLogger(__name__)

INF = 10**9
DAY = 86_400
CACHE_VERSION = 6


@dataclass
class Station:
    id: str
    name: str
    lat: float | None
    lon: float | None
    is_rail: bool
    stops: list[int] = field(default_factory=list)


@dataclass
class TripInfo:
    trip_id: str
    route_name: str
    category: str
    headsign: str | None
    train_number: str | None
    service: int  # index into TimetableStore.services


@dataclass
class Pattern:
    route_id: str
    category: str
    stops: np.ndarray  # (k,) stop indices
    trips: np.ndarray  # (n,) global trip indices
    arr: np.ndarray  # (n, k) seconds
    dep: np.ndarray  # (n, k) seconds
    can_board: np.ndarray  # (n, k) bool
    can_alight: np.ndarray  # (n, k) bool


@dataclass
class DayPattern:
    base: Pattern
    trips: np.ndarray  # global trip indices active on the day (sorted by first departure)
    arr: np.ndarray  # (n, k) planned arrivals
    dep_raw: np.ndarray  # (n, k) planned departures (sorted per column for FIFO trips)
    day_offset: np.ndarray  # 0 for the query day, -1 for trips of the previous service day
    # Compact copies for the RAPTOR inner loop (array.array indexing is much cheaper than numpy's):
    stops_list: list[int]
    dep_cols: list[array]  # per position: departures, INF where boarding is not allowed
    dep_raw_cols: list[array]  # per position: raw departures (for bisect)
    arr_rows: list[array]  # per trip: arrivals, INF where alighting is not allowed


class TimetableStore:
    """All patterns, stops and calendars of the imported feed."""

    def __init__(self) -> None:
        self.stop_ids: list[str] = []
        self.stop_names: list[str] = []
        self.stop_coords: list[tuple[float | None, float | None]] = []
        self.stop_station: list[int] = []
        self.stations: list[Station] = []
        self.station_index: dict[str, int] = {}
        self.stop_index: dict[str, int] = {}
        self.change_time: list[int] = []
        self.footpaths: list[list[tuple[int, int]]] = []
        self.trips: list[TripInfo] = []
        self.patterns: list[Pattern] = []
        self.services: list[str] = []
        self.service_weekdays: np.ndarray = np.zeros((0, 7), dtype=bool)
        self.service_range: list[tuple[date, date]] = []
        self.service_exceptions: dict[date, dict[int, int]] = {}
        self.feed_start: date | None = None
        self.feed_end: date | None = None
        self.default_change = 240
        self._day_cache: OrderedDict[date, DayTimetable] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- loading
    @classmethod
    def load(cls, engine: Engine, cache_path: Path | None = None, default_change: int = 240) -> TimetableStore:
        signature = cls._signature(engine)
        if cache_path and cache_path.exists():
            try:
                with cache_path.open("rb") as handle:
                    payload = pickle.load(handle)  # noqa: S301 - our own local cache file
                if payload.get("version") == CACHE_VERSION and payload.get("signature") == signature:
                    store: TimetableStore = payload["store"]
                    store._day_cache = OrderedDict()
                    store._lock = threading.Lock()
                    log.info("timetable loaded from cache %s", cache_path)
                    return store
            except Exception:  # pragma: no cover - corrupt cache
                log.warning("ignoring unreadable timetable cache %s", cache_path)
        store = cls._build(engine, default_change)
        if cache_path and store.patterns:
            lock, cache = store._lock, store._day_cache
            store._lock, store._day_cache = None, OrderedDict()  # type: ignore[assignment]
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("wb") as handle:
                    pickle.dump({"version": CACHE_VERSION, "signature": signature, "store": store}, handle,
                                protocol=pickle.HIGHEST_PROTOCOL)
            except OSError:
                # A read-only data directory only costs a slower start next time.
                log.warning("could not write timetable cache %s", cache_path)
            finally:
                store._lock, store._day_cache = lock, cache
        return store

    @staticmethod
    def _signature(engine: Engine) -> tuple:
        with engine.connect() as conn:
            return (
                conn.execute(text("SELECT COUNT(*) FROM stop_times")).scalar_one(),
                conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM stop_times")).scalar_one(),
                conn.execute(text("SELECT COUNT(*) FROM trips")).scalar_one(),
                conn.execute(text("SELECT COUNT(*) FROM calendar_dates")).scalar_one(),
            )

    @classmethod
    def _build(cls, engine: Engine, default_change: int) -> TimetableStore:
        store = cls()
        store.default_change = default_change
        with engine.connect() as conn:
            stops = conn.execute(text(
                "SELECT stop_id, stop_name, lat, lon, location_type, parent_station, is_rail FROM stops"
            )).all()
            routes = {
                r.route_id: r for r in conn.execute(
                    text("SELECT route_id, route_short_name, category FROM routes")).all()
            }
            trips = conn.execute(text(
                "SELECT trip_id, route_id, service_id, trip_headsign, trip_short_name FROM trips"
            )).all()
            calendar = conn.execute(text(
                "SELECT service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday, "
                "start_date, end_date FROM calendar")).all()
            cal_dates = conn.execute(text("SELECT service_id, date, exception_type FROM calendar_dates")).all()
            transfers = conn.execute(text(
                "SELECT from_stop_id, to_stop_id, min_transfer_time FROM transfers "
                "WHERE min_transfer_time IS NOT NULL")).all()
            stop_times = conn.execute(text(
                "SELECT trip_id, stop_id, arrival_secs, departure_secs, pickup_type, drop_off_type "
                "FROM stop_times ORDER BY trip_id, stop_sequence")).all()

        # Stations and stops
        parent_rows = {s.stop_id: s for s in stops}
        for s in stops:
            station_id = s.parent_station or _loose_station_id(s.stop_id, s.stop_name)
            if station_id not in store.station_index:
                src = parent_rows.get(station_id, s)
                name = src.stop_name if s.parent_station else _PLATFORM_SUFFIX.sub("", src.stop_name)
                store.station_index[station_id] = len(store.stations)
                store.stations.append(Station(station_id, name, src.lat, src.lon, bool(src.is_rail)))
            if s.location_type == 1:
                continue
            idx = len(store.stop_ids)
            store.stop_index[s.stop_id] = idx
            store.stop_ids.append(s.stop_id)
            store.stop_names.append(s.stop_name)
            store.stop_coords.append((s.lat, s.lon))
            station_idx = store.station_index[station_id]
            store.stop_station.append(station_idx)
            store.stations[station_idx].stops.append(idx)
            if s.is_rail:
                store.stations[station_idx].is_rail = True

        n_stops = len(store.stop_ids)
        store.change_time = [default_change] * n_stops
        pair_time: dict[tuple[int, int], int] = {}
        for t in transfers:
            a, b = store.stop_index.get(t.from_stop_id), store.stop_index.get(t.to_stop_id)
            if a is None or b is None:
                continue
            if a == b:
                store.change_time[a] = max(60, int(t.min_transfer_time))
            else:
                pair_time[(a, b)] = int(t.min_transfer_time)
        store.footpaths = [[] for _ in range(n_stops)]
        for station in store.stations:
            platforms = station.stops
            if len(platforms) < 2 or len(platforms) > 80:
                continue
            for a in platforms:
                for b in platforms:
                    if a != b:
                        store.footpaths[a].append((b, max(pair_time.get((a, b), default_change), 60)))

        # Services
        service_index: dict[str, int] = {}

        def service_idx(service_id: str) -> int:
            if service_id not in service_index:
                service_index[service_id] = len(store.services)
                store.services.append(service_id)
            return service_index[service_id]

        weekdays: dict[int, tuple] = {}
        ranges: dict[int, tuple[date, date]] = {}
        for c in calendar:
            i = service_idx(c.service_id)
            weekdays[i] = (c.monday, c.tuesday, c.wednesday, c.thursday, c.friday, c.saturday, c.sunday)
            ranges[i] = (_as_date(c.start_date), _as_date(c.end_date))
        for cd in cal_dates:
            i = service_idx(cd.service_id)
            store.service_exceptions.setdefault(_as_date(cd.date), {})[i] = int(cd.exception_type)

        # Trips
        trip_index: dict[str, int] = {}
        for t in trips:
            route = routes.get(t.route_id)
            if route is None:
                continue
            trip_index[t.trip_id] = len(store.trips)
            store.trips.append(TripInfo(
                trip_id=t.trip_id,
                route_name=route.route_short_name or "",
                category=route.category,
                headsign=t.trip_headsign,
                train_number=t.trip_short_name,
                service=service_idx(t.service_id),
            ))
        trip_route = {trip_index[t.trip_id]: t.route_id for t in trips if t.trip_id in trip_index}

        n_services = len(store.services)
        store.service_weekdays = np.zeros((n_services, 7), dtype=bool)
        store.service_range = [(date.max, date.min)] * n_services
        for i, wd in weekdays.items():
            store.service_weekdays[i] = [bool(x) for x in wd]
            store.service_range[i] = ranges[i]
        all_dates = [r[0] for r in ranges.values()] + [r[1] for r in ranges.values()] + list(store.service_exceptions)
        if all_dates:
            store.feed_start, store.feed_end = min(all_dates), max(all_dates)

        # Patterns
        groups: dict[tuple, list[tuple[int, list]]] = defaultdict(list)
        current: str | None = None
        rows: list = []

        def close(trip_id: str | None, trip_rows: list) -> None:
            if trip_id is None or trip_id not in trip_index or len(trip_rows) < 2:
                return
            stop_seq = tuple(store.stop_index.get(r[1], -1) for r in trip_rows)
            if -1 in stop_seq:
                return
            t_idx = trip_index[trip_id]
            groups[(trip_route[t_idx], stop_seq)].append((t_idx, trip_rows))

        for row in stop_times:
            if row[0] != current:
                close(current, rows)
                current, rows = row[0], []
            rows.append(row)
        close(current, rows)

        for (route_id, stop_seq), members in groups.items():
            members.sort(key=lambda m: m[1][0][3])
            n, k = len(members), len(stop_seq)
            arr = np.empty((n, k), dtype=np.int32)
            dep = np.empty((n, k), dtype=np.int32)
            board = np.ones((n, k), dtype=bool)
            alight = np.ones((n, k), dtype=bool)
            for i, (_, trip_rows) in enumerate(members):
                for j, r in enumerate(trip_rows):
                    arr[i, j] = r[2]
                    dep[i, j] = r[3]
                    board[i, j] = r[4] != 1
                    alight[i, j] = r[5] != 1
            board[:, -1] = False
            alight[:, 0] = False
            category = store.trips[members[0][0]].category
            store.patterns.append(Pattern(
                route_id=route_id, category=category, stops=np.array(stop_seq, dtype=np.int32),
                trips=np.array([m[0] for m in members], dtype=np.int32),
                arr=arr, dep=dep, can_board=board, can_alight=alight,
            ))
        log.info("timetable built: %s stops, %s stations, %s trips, %s patterns",
                 n_stops, len(store.stations), len(store.trips), len(store.patterns))
        return store

    # ------------------------------------------------------------ calendars
    def active_services(self, day: date) -> np.ndarray:
        active = np.zeros(len(self.services), dtype=bool)
        weekday = day.weekday()
        for i, (start, end) in enumerate(self.service_range):
            if start <= day <= end and self.service_weekdays[i, weekday]:
                active[i] = True
        for i, exception in self.service_exceptions.get(day, {}).items():
            active[i] = exception == 1
        return active

    def for_day(self, day: date) -> DayTimetable:
        with self._lock:
            cached = self._day_cache.get(day)
            if cached is not None:
                self._day_cache.move_to_end(day)
                return cached
        built = DayTimetable(self, day)
        with self._lock:
            self._day_cache[day] = built
            while len(self._day_cache) > 4:
                self._day_cache.popitem(last=False)
        return built

    # --------------------------------------------------------------- lookup
    def station_of_stop(self, stop_idx: int) -> Station:
        return self.stations[self.stop_station[stop_idx]]

    def search_stations(self, query: str, limit: int = 10, rail_only: bool = False) -> list[Station]:
        needle = _normalize(query)
        if not needle:
            return []
        scored = []
        for station in self.stations:
            if not station.stops or (rail_only and not station.is_rail):
                continue
            name = _normalize(station.name)
            if needle not in name:
                continue
            score = (0 if name.startswith(needle) else 1, 0 if station.is_rail else 1, len(name))
            scored.append((score, station))
        scored.sort(key=lambda item: item[0])
        return [s for _, s in scored[:limit]]

    def resolve_station(self, value: str) -> Station | None:
        """Accept a station id or a (partial) station name."""
        if value in self.station_index:
            station = self.stations[self.station_index[value]]
            return station if station.stops else None
        if value in self.stop_index:
            return self.station_of_stop(self.stop_index[value])
        matches = self.search_stations(value, limit=5)
        if not matches:
            return None
        exact = [s for s in matches if _normalize(s.name) == _normalize(value)]
        return (exact or matches)[0]


class DayTimetable:
    """Patterns restricted to trips running on one service day."""

    def __init__(self, store: TimetableStore, day: date) -> None:
        self.store = store
        self.day = day
        today = store.active_services(day)
        yesterday = store.active_services(day - timedelta(days=1))
        self.patterns: list[DayPattern] = []
        self.stop_patterns: list[list[tuple[int, int]]] = [[] for _ in store.stop_ids]
        for pattern in store.patterns:
            services = np.array([store.trips[t].service for t in pattern.trips], dtype=np.int32)
            on_today = today[services]
            # Trips of the previous service day still running after midnight.
            on_prev = yesterday[services] & (pattern.arr[:, -1] >= DAY)
            if not on_today.any() and not on_prev.any():
                continue
            arr = np.concatenate([pattern.arr[on_today], pattern.arr[on_prev] - DAY])
            dep = np.concatenate([pattern.dep[on_today], pattern.dep[on_prev] - DAY])
            board = np.concatenate([pattern.can_board[on_today], pattern.can_board[on_prev]])
            alight = np.concatenate([pattern.can_alight[on_today], pattern.can_alight[on_prev]])
            trips = np.concatenate([pattern.trips[on_today], pattern.trips[on_prev]])
            offset = np.concatenate([np.zeros(on_today.sum(), dtype=np.int8),
                                     -np.ones(on_prev.sum(), dtype=np.int8)])
            order = np.argsort(dep[:, 0], kind="stable")
            dep_sorted = dep[order]
            dep_board = np.where(board[order], dep_sorted, INF).astype(np.int32)
            arr_alight = np.where(alight[order], arr[order], INF).astype(np.int32)
            idx = len(self.patterns)
            self.patterns.append(DayPattern(
                base=pattern, trips=trips[order], arr=arr[order], dep_raw=dep_sorted, day_offset=offset[order],
                stops_list=pattern.stops.tolist(),
                dep_cols=[array("i", dep_board[:, j].tobytes()) for j in range(dep_board.shape[1])],
                dep_raw_cols=[array("i", np.ascontiguousarray(dep_sorted[:, j], dtype=np.int32).tobytes())
                              for j in range(dep_sorted.shape[1])],
                arr_rows=[array("i", row.tobytes()) for row in arr_alight],
            ))
            for pos, stop in enumerate(pattern.stops.tolist()):
                self.stop_patterns[stop].append((idx, pos))

    @property
    def is_rail_pattern(self) -> list[bool]:
        return [is_rail(p.base.category) for p in self.patterns]


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


_PLATFORM_SUFFIX = re.compile(r"\s+(Gleis|Bstg\.?)\s+[0-9A-Za-z]{1,3}$")
_ABBREVIATIONS = {"hbf": "hauptbahnhof", "bhf": "bahnhof", "bf": "bahnhof", "str": "strasse"}


def _loose_station_id(stop_id: str, stop_name: str) -> str:
    """Group parentless platforms (``de:08326:828:0:1``/``:0:2``) of the same stop area."""
    parts = stop_id.split(":")
    if len(parts) >= 3 and parts[0] in {"de", "at", "ch", "fr"}:
        return ":".join(parts[:3])
    return stop_id


def _normalize(value: str) -> str:
    value = value.lower()
    for src, dst in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        value = value.replace(src, dst)
    words = "".join(ch if ch.isalnum() else " " for ch in value).split()
    return " ".join(_ABBREVIATIONS.get(w, w) for w in words)
