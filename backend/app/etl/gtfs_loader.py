"""Stream a GTFS feed (directory or ZIP) into the timetable tables.

The NVBW feed covers all of Baden-Württemberg (~10M stop times). To keep the
database small enough for a tiny server we keep:

* every rail trip in the feed (RE/RB/S/IC/...), so long regional journeys route, and
* every other trip (bus, tram, SEV) that touches one of the region's counties.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, insert

from app.db.base import Base, import_all_models, table_of
from app.engine.categories import classify_route, is_rail
from app.models.timetable import Calendar, CalendarDate, Route, Stop, StopTime, Transfer, Trip

log = logging.getLogger(__name__)

# Schwarzwald-Baar-Kreis, Rottweil, Tuttlingen (Regionalverband Schwarzwald-Baar-Heuberg)
DEFAULT_REGION_COUNTIES = ("08326", "08325", "08327")
BATCH_SIZE = 20_000


@dataclass
class RegionFilter:
    counties: tuple[str, ...] = DEFAULT_REGION_COUNTIES
    keep_all_rail: bool = True
    keep_everything: bool = False

    def stop_in_region(self, stop_id: str) -> bool:
        parts = stop_id.split(":")
        return len(parts) > 1 and parts[1] in self.counties


@dataclass
class IngestStats:
    routes: int = 0
    trips: int = 0
    stop_times: int = 0
    stops: int = 0
    services: int = 0
    calendar_dates: int = 0
    transfers: int = 0
    non_contiguous_trips: int = 0
    categories: dict[str, int] = field(default_factory=dict)


def parse_gtfs_time(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) == 2:
        parts.append("0")
    hours, minutes, seconds = (int(p) for p in parts)
    return hours * 3600 + minutes * 60 + seconds


def _to_int(value: str | None, default: int | None = 0) -> int | None:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


class GTFSLoader:
    """Load a GTFS feed into the timetable schema."""

    def __init__(self, base_path: str | Path, region: RegionFilter | None = None):
        self.base_path = Path(base_path)
        self.region = region or RegionFilter(keep_everything=True)

    # ---------------------------------------------------------------- reading
    @contextmanager
    def _open(self, name: str) -> Iterator[Iterable[dict[str, str]] | None]:
        if self.base_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(self.base_path) as archive:
                if name not in archive.namelist():
                    yield None
                    return
                with archive.open(name) as raw:
                    yield csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            return
        path = self.base_path / name
        if not path.exists():
            yield None
            return
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield csv.DictReader(handle)

    def _read_all(self, name: str) -> list[dict[str, str]]:
        with self._open(name) as rows:
            return list(rows) if rows is not None else []

    # Backwards-compatible readers used by notebooks.
    def load_stops(self) -> list[dict[str, str]]:
        return self._read_all("stops.txt")

    def load_routes(self) -> list[dict[str, str]]:
        return self._read_all("routes.txt")

    def load_trips(self) -> list[dict[str, str]]:
        return self._read_all("trips.txt")

    def load_calendar(self) -> list[dict[str, str]]:
        return self._read_all("calendar.txt")

    # ----------------------------------------------------------------- ingest
    def ingest(self, engine: Engine, replace: bool = True) -> IngestStats:
        import_all_models()
        tables = [table_of(Stop), table_of(Route), table_of(Trip), table_of(StopTime),
                  table_of(Calendar), table_of(CalendarDate), table_of(Transfer)]
        Base.metadata.create_all(bind=engine, tables=tables)
        stats = IngestStats()

        with engine.begin() as conn:
            if replace:
                for table in tables:
                    conn.execute(delete(table))

        routes: dict[str, dict[str, Any]] = {}
        for row in self._read_all("routes.txt"):
            route_type = _to_int(row.get("route_type"), 3) or 0
            category = classify_route(route_type, row.get("route_short_name", ""))
            routes[row["route_id"]] = {
                "route_id": row["route_id"],
                "agency_id": row.get("agency_id"),
                "route_short_name": (row.get("route_short_name") or "").strip(),
                "route_long_name": (row.get("route_long_name") or "").strip() or None,
                "route_type": route_type,
                "category": category,
            }

        trips: dict[str, dict[str, Any]] = {}
        with self._open("trips.txt") as rows:
            for row in rows or []:
                route = routes.get(row["route_id"])
                if route is None:
                    continue
                trips[row["trip_id"]] = {
                    "trip_id": row["trip_id"],
                    "route_id": row["route_id"],
                    "service_id": row.get("service_id", ""),
                    "trip_headsign": (row.get("trip_headsign") or "").strip() or None,
                    "trip_short_name": (row.get("trip_short_name") or "").strip() or None,
                    "direction_id": _to_int(row.get("direction_id"), None),
                }
        log.info("read %s routes and %s trips", len(routes), len(trips))

        kept_trips: set[str] = set()
        used_stops: set[str] = set()
        rail_stops: set[str] = set()
        decided: set[str] = set()

        def trip_category(trip_id: str) -> str:
            return routes[trips[trip_id]["route_id"]]["category"]

        with engine.begin() as conn:
            batch: list[dict] = []

            def flush() -> None:
                if batch:
                    conn.execute(insert(table_of(StopTime)), batch)
                    stats.stop_times += len(batch)
                    batch.clear()

            def decide(trip_id: str, rows: list[dict]) -> None:
                if trip_id in decided:
                    stats.non_contiguous_trips += 1
                decided.add(trip_id)
                if trip_id not in trips or len(rows) < 2:
                    return
                category = trip_category(trip_id)
                keep = (
                    self.region.keep_everything
                    or (self.region.keep_all_rail and is_rail(category))
                    or any(self.region.stop_in_region(r["stop_id"]) for r in rows)
                )
                if not keep:
                    return
                kept_trips.add(trip_id)
                for r in rows:
                    used_stops.add(r["stop_id"])
                    if is_rail(category):
                        rail_stops.add(r["stop_id"])
                batch.extend(rows)
                if len(batch) >= BATCH_SIZE:
                    flush()

            current: str | None = None
            buffer: list[dict] = []
            with self._open("stop_times.txt") as rows:
                for row in rows or []:
                    trip_id = row["trip_id"]
                    if trip_id != current:
                        if current is not None:
                            decide(current, buffer)
                        current, buffer = trip_id, []
                    arrival = parse_gtfs_time(row.get("arrival_time"))
                    departure = parse_gtfs_time(row.get("departure_time"))
                    if arrival is None and departure is None:
                        continue  # untimed intermediate stop; not needed for routing
                    buffer.append({
                        "trip_id": trip_id,
                        "stop_id": row["stop_id"],
                        "stop_sequence": _to_int(row.get("stop_sequence")),
                        "arrival_secs": arrival if arrival is not None else departure,
                        "departure_secs": departure if departure is not None else arrival,
                        "pickup_type": _to_int(row.get("pickup_type")),
                        "drop_off_type": _to_int(row.get("drop_off_type")),
                    })
                if current is not None:
                    decide(current, buffer)
            flush()

            # Trips
            kept_trip_rows = [trips[t] for t in kept_trips]
            for start in range(0, len(kept_trip_rows), BATCH_SIZE):
                conn.execute(insert(table_of(Trip)), kept_trip_rows[start:start + BATCH_SIZE])
            stats.trips = len(kept_trip_rows)

            # Routes
            used_routes = {trips[t]["route_id"] for t in kept_trips}
            route_rows = [routes[r] for r in used_routes]
            if route_rows:
                conn.execute(insert(table_of(Route)), route_rows)
            stats.routes = len(route_rows)
            for t in kept_trips:
                cat = routes[trips[t]["route_id"]]["category"]
                stats.categories[cat] = stats.categories.get(cat, 0) + 1

            # Stops (+ their parent stations)
            all_stops = {r["stop_id"]: r for r in self._read_all("stops.txt")}
            parents = {all_stops[s].get("parent_station") for s in used_stops if s in all_stops}
            rail_parents = {all_stops[s].get("parent_station") for s in rail_stops if s in all_stops}
            wanted: set[str] = {s for s in used_stops | parents if s}
            stop_rows = []
            for stop_id in wanted:
                src = all_stops.get(stop_id)
                if src is None:
                    continue
                stop_rows.append({
                    "stop_id": stop_id,
                    "stop_name": (src.get("stop_name") or "").strip(),
                    "lat": _to_float(src.get("stop_lat") or src.get("lat")),
                    "lon": _to_float(src.get("stop_lon") or src.get("lon")),
                    "location_type": _to_int(src.get("location_type")),
                    "parent_station": (src.get("parent_station") or "").strip() or None,
                    "platform_code": (src.get("platform_code") or "").strip() or None,
                    "is_rail": int(stop_id in rail_stops or stop_id in rail_parents),
                })
            for start in range(0, len(stop_rows), BATCH_SIZE):
                conn.execute(insert(table_of(Stop)), stop_rows[start:start + BATCH_SIZE])
            stats.stops = len(stop_rows)

            # Calendar
            services = {trips[t]["service_id"] for t in kept_trips}
            cal_rows = []
            for row in self._read_all("calendar.txt"):
                if row["service_id"] not in services:
                    continue
                cal_rows.append({
                    "service_id": row["service_id"],
                    **{day: _to_int(row.get(day)) for day in
                       ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")},
                    "start_date": datetime.strptime(row["start_date"], "%Y%m%d").date(),
                    "end_date": datetime.strptime(row["end_date"], "%Y%m%d").date(),
                })
            if cal_rows:
                conn.execute(insert(table_of(Calendar)), cal_rows)
            stats.services = len(cal_rows)

            date_batch: list[dict] = []
            with self._open("calendar_dates.txt") as rows:
                for row in rows or []:
                    if row["service_id"] not in services:
                        continue
                    date_batch.append({
                        "service_id": row["service_id"],
                        "date": datetime.strptime(row["date"], "%Y%m%d").date(),
                        "exception_type": _to_int(row.get("exception_type"), 1),
                    })
                    if len(date_batch) >= BATCH_SIZE:
                        conn.execute(insert(table_of(CalendarDate)), date_batch)
                        stats.calendar_dates += len(date_batch)
                        date_batch = []
            if date_batch:
                conn.execute(insert(table_of(CalendarDate)), date_batch)
                stats.calendar_dates += len(date_batch)

            transfer_rows = []
            with self._open("transfers.txt") as rows:
                for row in rows or []:
                    if row.get("from_stop_id") in wanted and row.get("to_stop_id") in wanted:
                        transfer_rows.append({
                            "from_stop_id": row["from_stop_id"],
                            "to_stop_id": row["to_stop_id"],
                            "transfer_type": _to_int(row.get("transfer_type")),
                            "min_transfer_time": _to_int(row.get("min_transfer_time"), None),
                        })
            for start in range(0, len(transfer_rows), BATCH_SIZE):
                conn.execute(insert(table_of(Transfer)), transfer_rows[start:start + BATCH_SIZE])
            stats.transfers = len(transfer_rows)

        log.info("GTFS ingest finished: %s", stats)
        return stats
