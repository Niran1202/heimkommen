"""Tests for the delay data platform SQL (rail.load_month). Need the platform Postgres; skipped when it is down.

    docker compose -f docker-compose.platform.yml up -d && python scripts/rail_db.py init
Everything runs on a scratch staging table and the fake month 2099-01; real data is never touched.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import psycopg
import pytest

URL = os.environ.get("RAIL_DATABASE_URL", "postgresql://rail:rail@localhost:5433/rail")
MONTH = "2099-01"
STAGE = "rail.stg_test"
FAKE_BASELINE_MONTHS = ("2098-10", "2098-11", "2098-12")


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(URL, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("platform Postgres is not running")
    c.execute(f"DROP TABLE IF EXISTS {STAGE}")
    c.execute(f"CREATE UNLOGGED TABLE {STAGE} (LIKE rail.stg_delay_month)")
    yield c
    c.execute(f"DROP TABLE IF EXISTS {STAGE}")
    c.execute("DELETE FROM rail.fact_stop_event WHERE source_month = %s", (MONTH,))
    c.execute("DELETE FROM rail.load_log WHERE month = %s OR month = ANY(%s)", (MONTH, list(FAKE_BASELINE_MONTHS)))
    c.execute("DROP TABLE IF EXISTS rail.fact_stop_event_2099_01")
    c.close()


def stage_rows(conn, n: int, *, month_day: int = 15, delay_min: float = 3.0, dup_every: int = 0,
               null_ride_every: int = 0) -> None:
    base = datetime(2099, 1, month_day, 8, 0)
    rows = []
    for i in range(n):
        planned = base + timedelta(minutes=i % 600)
        rid = None if null_ride_every and i % null_ride_every == 0 else f"ride{i // 5}"
        row_id = f"row{i // 2}" if dup_every and i % dup_every == 1 else f"row{i}"
        rows.append((row_id, "8000001", "Test Hbf", "RE", "1234", "RE1", "Nowhere", rid, i % 5,
                     planned, planned + timedelta(minutes=delay_min), planned, planned + timedelta(minutes=delay_min),
                     False, False, False, False))
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO {STAGE} VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)


def fake_baseline(conn, rows: int = 1000) -> None:
    for m in FAKE_BASELINE_MONTHS:
        conn.execute("INSERT INTO rail.load_log (month, status, finished_at, rows_staged, rows_loaded) "
                     "VALUES (%s, 'loaded', now(), %s, %s)", (m, rows, rows))


def load(conn) -> str:
    return conn.execute("SELECT rail.load_month(%s, %s::regclass)", (MONTH, STAGE)).fetchone()[0]


def fact_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM rail.fact_stop_event WHERE source_month = %s", (MONTH,)).fetchone()[0]


def test_valid_month_is_loaded_and_logged(conn):
    stage_rows(conn, 1000)
    assert load(conn) == "loaded: 1000 rows"
    assert fact_count(conn) == 1000
    status, loaded = conn.execute(
        "SELECT status, rows_loaded FROM rail.load_log WHERE month = %s ORDER BY id DESC LIMIT 1", (MONTH,)).fetchone()
    assert (status, loaded) == ("loaded", 1000)


def test_loading_the_same_month_twice_does_not_duplicate(conn):
    stage_rows(conn, 1000)
    load(conn)
    load(conn)
    assert fact_count(conn) == 1000


def test_delay_is_computed_in_minutes(conn):
    stage_rows(conn, 10, delay_min=7.0)
    load(conn)
    assert conn.execute("SELECT min(arrival_delay_min), max(departure_delay_min) FROM rail.fact_stop_event "
                        "WHERE source_month = %s", (MONTH,)).fetchone() == (7.0, 7.0)


def test_truncated_file_is_rejected_and_loads_nothing(conn):
    fake_baseline(conn, 1000)
    stage_rows(conn, 600)  # 40% fewer rows than the trailing average of 1000
    result = load(conn)
    assert result.startswith("rejected") and "below the trailing average" in result
    assert fact_count(conn) == 0
    assert conn.execute("SELECT status FROM rail.load_log WHERE month = %s", (MONTH,)).fetchone()[0] == "rejected"


def test_file_slightly_below_average_is_accepted(conn):
    fake_baseline(conn, 1000)
    stage_rows(conn, 800)  # 20% fewer rows is within the 30% tolerance
    assert load(conn) == "loaded: 800 rows"


def test_empty_file_is_rejected(conn):
    assert load(conn) == "rejected: the file is empty"


def test_rows_with_missing_ride_are_rejected(conn):
    stage_rows(conn, 1000, null_ride_every=50)
    assert "miss an id, station, ride or planned time" in load(conn)
    assert fact_count(conn) == 0


def test_wrong_month_is_rejected(conn):
    stage_rows(conn, 1000)
    result = conn.execute("SELECT rail.load_month('2099-03', %s::regclass)", (STAGE,)).fetchone()[0]
    try:
        assert "wrong month" in result
    finally:
        conn.execute("DELETE FROM rail.load_log WHERE month = '2099-03'")


def test_extreme_delays_are_rejected(conn):
    stage_rows(conn, 1000, delay_min=3000.0)  # about two days late
    assert "beyond 24 hours" in load(conn)


def test_many_duplicate_ids_are_rejected(conn):
    stage_rows(conn, 1000, dup_every=2)
    assert "duplicate ids" in load(conn)
