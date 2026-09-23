"""Build the station_map table (GTFS station <-> DB EVA number).

    python scripts/match_stations.py --delays data/raw/piebro/data-2026-08.parquet

Uses a handful of weekdays from the delay file that are inside the GTFS feed period.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, insert  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import engine, init_db  # noqa: E402
from app.engine.categories import is_rail  # noqa: E402
from app.engine.timetable import TimetableStore  # noqa: E402
from app.etl.station_matching import StationMatcher  # noqa: E402
from app.models.timetable import StationMap  # noqa: E402


def gtfs_events(store: TimetableStore, day: date):
    tt = store.for_day(day)
    for pattern in tt.patterns:
        if not is_rail(pattern.base.category):
            continue
        stations = [store.stations[store.stop_station[s]].id for s in pattern.base.stops.tolist()]
        for row, trip_idx in enumerate(pattern.trips.tolist()):
            number = store.trips[trip_idx].train_number
            if not number:
                continue
            midnight = datetime.combine(day, time())
            for pos, station in enumerate(stations):
                # Times are relative to the query day (previous-day trips are already shifted).
                secs = int(pattern.dep_raw[row, pos]) if pos < len(stations) - 1 else int(pattern.arr[row, pos])
                when = midnight + timedelta(seconds=secs)
                yield number, f"{when:%Y-%m-%d %H:%M}", station


def db_events(path: Path, days: list[date]):
    table = pq.read_table(path, columns=["eva", "station_name", "train_number",
                                         "arrival_planned_time", "departure_planned_time"])
    planned = pc.coalesce(table["departure_planned_time"], table["arrival_planned_time"])
    day_strings = pc.strftime(planned, format="%Y-%m-%d")
    mask = pc.is_in(day_strings, value_set=pa.array([d.isoformat() for d in days]))
    table = table.filter(mask)
    planned = pc.coalesce(table["departure_planned_time"], table["arrival_planned_time"])
    when = pc.strftime(planned, format="%Y-%m-%d %H:%M").to_pylist()
    trains = table["train_number"].to_pylist()
    evas = table["eva"].to_pylist()
    names = dict(zip(evas, table["station_name"].to_pylist(), strict=True))
    events = [(t, w, e) for t, w, e in zip(trains, when, evas, strict=True) if t and w]
    return events, names


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delays", type=Path, default=ROOT / "data/raw/piebro/data-2026-08.parquet")
    parser.add_argument("--days", default="2026-08-11,2026-08-12,2026-08-15,2026-08-16",
                        help="Comma-separated dates inside both the GTFS feed and the delay file")
    args = parser.parse_args()
    days = [date.fromisoformat(d) for d in args.days.split(",")]

    init_db()
    store = TimetableStore.load(engine, get_settings().data_dir / "timetable_cache.pkl")
    g_events = [e for d in days for e in gtfs_events(store, d)]
    d_events, db_names = db_events(args.delays, days)
    print(f"{len(g_events)} GTFS events, {len(d_events)} DB events")

    gtfs_names = {s.id: s.name for s in store.stations}
    by_timetable = StationMatcher.match_by_timetable(g_events, d_events, names=(gtfs_names, db_names))
    rows = {}
    for station_id, (eva, _votes, share) in by_timetable.items():
        station = store.stations[store.station_index[station_id]]
        rows[station_id] = {"station_id": station_id, "eva": eva, "gtfs_name": station.name,
                            "db_name": db_names.get(eva, ""), "method": "timetable", "score": round(share, 3)}

    # Name fallback for rail stations without timetable evidence.
    missing = [{"stop_id": s.id, "stop_name": s.name} for s in store.stations
               if s.is_rail and s.stops and s.id not in rows]
    db_rows = [{"eva": e, "name": n} for e, n in db_names.items()]
    used = {r["eva"] for r in rows.values()}
    for station_id, eva in StationMatcher.match_stations(missing, db_rows).items():
        if eva in used:
            continue
        station = store.stations[store.station_index[station_id]]
        rows[station_id] = {"station_id": station_id, "eva": eva, "gtfs_name": station.name,
                            "db_name": db_names.get(eva, ""), "method": "name", "score": 0.5}

    with engine.begin() as conn:
        conn.execute(delete(StationMap.__table__))
        if rows:
            conn.execute(insert(StationMap.__table__), list(rows.values()))
    export = ROOT / "ml" / "artifacts" / "station_map.csv"
    with export.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["station_id", "eva", "gtfs_name", "db_name", "method", "score"])
        writer.writeheader()
        writer.writerows(rows.values())
    rail_total = sum(1 for s in store.stations if s.is_rail and s.stops)
    by_method = {m: sum(1 for r in rows.values() if r["method"] == m) for m in ("timetable", "name")}
    print(f"matched {len(rows)} of {rail_total} rail stations: {by_method}")
    for name in ("Villingen Bahnhof/ZOB", "Stuttgart Hauptbahnhof (oben)", "Freiburg Hauptbahnhof",
                 "Konstanz Bahnhof", "Rottweil Bahnhof", "Donaueschingen Bahnhof", "Offenburg Bahnhof"):
        hit = [r for r in rows.values() if r["gtfs_name"] == name]
        print(f"  {name:32s} -> {hit[0]['eva'] + ' ' + hit[0]['db_name'] if hit else 'NO MATCH'}")


if __name__ == "__main__":
    main()
