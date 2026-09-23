"""Load delay history into ``train_stop_history``.

Two sources, both from the piebro dataset (CC BY 4.0, data by Deutsche Bahn):

* ``load_processed_month``: a monthly processed parquet file (already filtered to BW).
* ``load_raw_day``: the *raw* API responses for one day (published a few times per day),
  parsed with the same XML parsers the live client uses. This is what the nightly job
  uses to learn what actually happened yesterday.
"""

from __future__ import annotations

import csv
import json
import logging
import urllib.request
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from sqlalchemy import Engine, delete, insert, text

from app.clients.db_timetables import parse_changes, parse_plan
from app.db.base import table_of
from app.models.delays import TrainStopHistory

log = logging.getLogger(__name__)
HF_TREE = "https://huggingface.co/api/datasets/piebro/deutsche-bahn-data/tree/main/raw_data/year={y}/month={m}/day={d}"
HF_FILE = "https://huggingface.co/datasets/piebro/deutsche-bahn-data/resolve/main/{path}"
BATCH = 10_000


def _minutes(actual: datetime | None, planned: datetime | None) -> int | None:
    if actual is None or planned is None:
        return None
    return int((actual - planned).total_seconds() // 60)


def _insert(engine: Engine, rows: list[dict]) -> int:
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    with engine.begin() as conn:
        for start in range(0, len(ids), 900):
            conn.execute(delete(table_of(TrainStopHistory)).where(TrainStopHistory.id.in_(ids[start:start + 900])))
        for start in range(0, len(rows), BATCH):
            conn.execute(insert(table_of(TrainStopHistory)), rows[start:start + BATCH])
    return len(rows)


def region_evas(engine: Engine, counties: Iterable[str] | None = None) -> set[str]:
    """EVAs of matched stations, optionally restricted to county codes (``de:08326:...``)."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT station_id, eva FROM station_map")).all()
    if counties is None:
        return {eva for _, eva in rows}
    wanted = tuple(counties)
    return {eva for station_id, eva in rows if station_id.split(":")[1:2] and station_id.split(":")[1] in wanted}


# --------------------------------------------------------------- processed monthly files
def load_processed_month(engine: Engine, path: Path, evas: set[str] | None = None) -> int:
    table = pq.read_table(path)
    if evas:
        table = table.filter(pc.is_in(table["eva"], value_set=pa.array(sorted(evas))))
    rows = []
    for r in table.to_pylist():
        planned = r["departure_planned_time"] or r["arrival_planned_time"]
        rows.append({
            "id": r["id"], "ride_id": r["train_line_ride_id"], "station_num": r["train_line_station_num"],
            "eva": r["eva"], "station_name": r["station_name"], "train_type": r["train_type"],
            "train_number": r["train_number"], "line_number": r["line_number"],
            "final_destination": r["final_destination_station"],
            "service_date": planned.date().isoformat() if planned else None,
            "arrival_planned": r["arrival_planned_time"], "arrival_actual": r["arrival_change_time"],
            "departure_planned": r["departure_planned_time"], "departure_actual": r["departure_change_time"],
            "arrival_delay": _minutes(r["arrival_change_time"], r["arrival_planned_time"]),
            "departure_delay": _minutes(r["departure_change_time"], r["departure_planned_time"]),
            "arrival_cancelled": bool(r["arrival_is_canceled"]),
            "departure_cancelled": bool(r["departure_is_canceled"]),
        })
    return _insert(engine, rows)


# ------------------------------------------------------------------- raw daily files
def raw_files_for(day: date) -> list[str]:
    """HF paths of raw files that contain hours of ``day`` (they live in day and day+1 folders)."""
    paths = []
    for folder in (day, day + timedelta(days=1)):
        url = HF_TREE.format(y=folder.year, m=folder.month, d=folder.day)
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https host
                listing = json.load(response)
        except OSError:
            continue
        paths += [x["path"] for x in listing if f"date_{day.isoformat()}" in x["path"]]
    return paths


def download_raw(day: date, target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    local = []
    for path in raw_files_for(day):
        out = target_dir / Path(path).name
        if not out.exists():
            urllib.request.urlretrieve(HF_FILE.format(path=path), out)  # noqa: S310
        local.append(out)
    return local


def parse_raw_files(files: list[Path], evas: set[str], day: date) -> list[dict]:
    """Planned stops of ``day`` at ``evas`` merged with the latest known changes."""
    plans: dict[str, dict] = {}
    changes: dict[str, tuple[datetime, dict]] = {}
    for file in files:
        table = pq.read_table(file, columns=["timestamp", "url", "api_name", "response_data", "status_code"])
        table = table.filter(pc.is_in(table["api_name"], value_set=pa.array(["timetables/v1/plan",
                                                                              "timetables/v1/fchg"])))
        for row in table.to_pylist():
            if str(row["status_code"]) != "200" or not row["response_data"]:
                continue
            url = row["url"]
            if row["api_name"].endswith("plan"):
                eva = url.split("/plan/")[1].split("/")[0].lstrip("0")
            else:
                eva = url.rsplit("/", 1)[1].lstrip("0")
            eva_full = eva.zfill(8)
            if eva_full not in evas:
                continue
            try:
                if row["api_name"].endswith("plan"):
                    for stop_id, p in parse_plan(row["response_data"]).items():
                        p["eva"] = eva_full
                        plans[stop_id] = p
                else:
                    for stop_id, c in parse_changes(row["response_data"]).items():
                        previous = changes.get(stop_id)
                        if previous is None or previous[0] <= row["timestamp"]:
                            changes[stop_id] = (row["timestamp"], c)
            except Exception:  # malformed XML in the archive
                log.debug("skipping unparsable response for %s", url)
    rows = []
    for stop_id, p in plans.items():
        planned = p["pt_dep"] or p["pt_arr"]
        if planned is None or planned.date() != day:
            continue
        c = changes.get(stop_id, (None, {}))[1]
        arr_actual = c.get("ct_arr") or p["pt_arr"]
        dep_actual = c.get("ct_dep") or p["pt_dep"]
        rows.append({
            "id": stop_id, "ride_id": stop_id.rsplit("-", 2)[0], "station_num": _station_num(stop_id),
            "eva": p["eva"], "station_name": "", "train_type": p["category"], "train_number": p["number"],
            "line_number": p["line"], "final_destination": None, "service_date": day.isoformat(),
            "arrival_planned": p["pt_arr"], "arrival_actual": arr_actual,
            "departure_planned": p["pt_dep"], "departure_actual": dep_actual,
            "arrival_delay": _minutes(arr_actual, p["pt_arr"]), "departure_delay": _minutes(dep_actual, p["pt_dep"]),
            "arrival_cancelled": bool(c.get("cancelled")), "departure_cancelled": bool(c.get("cancelled")),
        })
    return rows


def _station_num(stop_id: str) -> int | None:
    try:
        return int(stop_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def load_raw_day(engine: Engine, day: date, raw_dir: Path, evas: set[str], keep_files: bool = False) -> int:
    files = download_raw(day, raw_dir)
    if not files:
        log.warning("no raw delay files published for %s yet", day)
        return 0
    rows = parse_raw_files(files, evas, day)
    count = _insert(engine, rows)
    if not keep_files:
        for file in files:
            file.unlink(missing_ok=True)
    log.info("loaded %s stop events for %s", count, day)
    return count


class DelaysLoader:
    """Small CSV loader (used for fixtures and quick experiments)."""

    def __init__(self, base_path: str | Path, region_stations: list[str] | None = None):
        self.base_path = Path(base_path)
        self.region_stations = region_stations or []

    def load_delay_history(self) -> list[dict[str, str]]:
        csv_path = self.base_path / "delay_history.csv"
        if not csv_path.exists():
            return []
        rows: list[dict[str, str]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                station_eva = row.get("station_eva") or row.get("eva") or ""
                if self.region_stations and station_eva not in self.region_stations:
                    continue
                row["delay_minutes"] = str(float(row.get("delay_minutes") or row.get("delay_min") or 0.0))
                rows.append(row)
        return rows
