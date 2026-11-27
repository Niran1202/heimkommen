"""Runner for the delay data platform (SQL layer).

    python scripts/rail_db.py init                         # apply sql/*.sql in order
    python scripts/rail_db.py load --months 2026-05 2026-06 # parquet -> staging -> fact table
    python scripts/rail_db.py counts                       # rows per partition

Connects to the Postgres from docker-compose.platform.yml (override with RAIL_DATABASE_URL).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import psycopg
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
PROCESSED = ROOT / "data" / "processed"
URL = os.environ.get("RAIL_DATABASE_URL", "postgresql://rail:rail@localhost:5433/rail")
STAGING_COLUMNS = [
    "id", "eva", "station_name", "train_type", "train_number", "line_number", "final_destination_station",
    "train_line_ride_id", "train_line_station_num", "arrival_planned_time", "arrival_change_time",
    "departure_planned_time", "departure_change_time", "arrival_is_canceled", "departure_is_canceled",
    "is_additional_stop", "is_replacement_train",
]

# Phase 1 merge: plain insert. Phase 2 replaces this by the validating rail.load_month() function.
MERGE_SQL = """
INSERT INTO rail.fact_stop_event (
    id, event_ts, source_month, ride_id, station_num, eva, station_name, train_type, train_number, line_number,
    final_destination, arrival_planned, arrival_actual, departure_planned, departure_actual,
    arrival_delay_min, departure_delay_min, arrival_cancelled, departure_cancelled, is_replacement)
SELECT id, COALESCE(departure_planned_time, arrival_planned_time), %(month)s, train_line_ride_id,
       train_line_station_num, eva, station_name, train_type, train_number, line_number,
       final_destination_station, arrival_planned_time, arrival_change_time, departure_planned_time,
       departure_change_time,
       EXTRACT(EPOCH FROM arrival_change_time - arrival_planned_time) / 60,
       EXTRACT(EPOCH FROM departure_change_time - departure_planned_time) / 60,
       COALESCE(arrival_is_canceled, false), COALESCE(departure_is_canceled, false),
       COALESCE(is_replacement_train, false)
FROM rail.stg_delay_month
WHERE NOT COALESCE(is_additional_stop, false)
  AND COALESCE(departure_planned_time, arrival_planned_time) IS NOT NULL
  AND train_line_ride_id IS NOT NULL AND train_line_station_num IS NOT NULL
ON CONFLICT (id, event_ts) DO NOTHING
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(URL, autocommit=True)


def init() -> None:
    with connect() as conn:
        for path in sorted(SQL_DIR.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
            print(f"applied {path.name}")


def load_month(conn: psycopg.Connection, month: str) -> None:
    source = PROCESSED / f"delays-{month}.parquet"
    expected = pq.ParquetFile(source).metadata.num_rows
    conn.execute("TRUNCATE rail.stg_delay_month")
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "month.csv"
        # Streaming the CSV through COPY is far faster than inserting rows from Python.
        table = pq.read_table(source, columns=STAGING_COLUMNS)
        pacsv.write_csv(table, csv_path, pacsv.WriteOptions(include_header=False))
        del table
        cols = ", ".join(STAGING_COLUMNS)
        with conn.cursor() as cur, csv_path.open("rb") as handle, \
                cur.copy(f"COPY rail.stg_delay_month ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
            while chunk := handle.read(1 << 20):
                copy.write(chunk)
    staged = conn.execute("SELECT count(*) FROM rail.stg_delay_month").fetchone()[0]
    if staged != expected:
        raise SystemExit(f"{month}: staged {staged:,} rows but the file has {expected:,}")
    # Partitions for every month the planned times touch (a ride can start in the previous month).
    for (first,) in conn.execute(
            "SELECT DISTINCT date_trunc('month', COALESCE(departure_planned_time, arrival_planned_time)) "
            "FROM rail.stg_delay_month WHERE COALESCE(departure_planned_time, arrival_planned_time) IS NOT NULL"
    ).fetchall():
        conn.execute("SELECT rail.ensure_partition(%s)", (first,))
    cur = conn.execute(MERGE_SQL, {"month": month})
    conn.execute("TRUNCATE rail.stg_delay_month")
    print(f"{month}: staged {staged:,}, merged {cur.rowcount:,} rows")


def counts() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.relname, c.reltuples::bigint FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'rail.fact_stop_event'::regclass ORDER BY 1").fetchall()
        for name, _ in rows:
            n = conn.execute(f"SELECT count(*) FROM rail.{name}").fetchone()[0]
            print(f"{name}: {n:,}")
        print("total:", f"{conn.execute('SELECT count(*) FROM rail.fact_stop_event').fetchone()[0]:,}")
        print("by source month:", conn.execute(
            "SELECT source_month, count(*) FROM rail.fact_stop_event GROUP BY 1 ORDER BY 1").fetchall())


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("counts")
    load = sub.add_parser("load")
    load.add_argument("--months", nargs="+", required=True)
    args = parser.parse_args()
    if args.cmd == "init":
        init()
    elif args.cmd == "counts":
        counts()
    else:
        with connect() as conn:
            for month in args.months:
                load_month(conn, month)


if __name__ == "__main__":
    sys.exit(main())
