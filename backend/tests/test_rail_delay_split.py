"""Tests for rail.v_delay_split (phase 3). Synthetic rides in the fake month 2099-01; real data is never touched."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import psycopg
import pytest

URL = os.environ.get("RAIL_DATABASE_URL", "postgresql://rail:rail@localhost:5433/rail")
MONTH = "2099-01"
BASE = datetime(2099, 1, 10, 8, 0)


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(URL, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("platform Postgres is not running")
    c.execute("SELECT rail.ensure_partition(%s)", (BASE,))
    yield c
    c.execute("DELETE FROM rail.fact_stop_event WHERE source_month = %s", (MONTH,))
    c.execute("DROP TABLE IF EXISTS rail.fact_stop_event_2099_01")
    c.close()


def add_ride(conn, ride: str, stops: list[tuple[int, float | None, float | None]]) -> None:
    """stops = (station_num, arrival_delay, departure_delay); None means no arrival / departure at that stop."""
    for i, (num, arr, dep) in enumerate(stops):
        planned = BASE + timedelta(minutes=10 * i)
        conn.execute(
            """INSERT INTO rail.fact_stop_event (id, event_ts, source_month, ride_id, station_num, eva, station_name,
                   arrival_planned, arrival_delay_min, departure_planned, departure_delay_min)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (f"{ride}-{num}", planned, MONTH, ride, num, f"eva{num}", f"Stop {num}",
             planned if arr is not None else None, arr, planned if dep is not None else None, dep))


def split(conn, ride: str) -> dict[int, dict]:
    cur = conn.execute(
        """SELECT station_num, brought_in_min, created_en_route_min, created_at_stop_min, delay_after_stop_min,
                  gap_before FROM rail.v_delay_split WHERE ride_id = %s ORDER BY station_num""", (ride,))
    cols = [d.name for d in cur.description]
    return {row[0]: dict(zip(cols, row, strict=True)) for row in cur.fetchall()}


def test_full_ride_splits_into_brought_and_created(conn):
    # origin leaves 2 late; middle arrives 5 late and leaves 6 late; terminus arrives 4 late (recovered 2).
    add_ride(conn, "R1", [(1, None, 2.0), (2, 5.0, 6.0), (3, 4.0, None)])
    s = split(conn, "R1")
    assert (s[1]["brought_in_min"], s[1]["created_en_route_min"], s[1]["created_at_stop_min"]) == (0.0, None, 2.0)
    assert (s[2]["brought_in_min"], s[2]["created_en_route_min"], s[2]["created_at_stop_min"]) == (2.0, 3.0, 1.0)
    assert (s[3]["brought_in_min"], s[3]["created_en_route_min"], s[3]["created_at_stop_min"]) == (6.0, -2.0, None)
    assert s[3]["delay_after_stop_min"] == 4.0


def test_brought_plus_created_equals_total_delay(conn):
    add_ride(conn, "R2", [(1, None, 1.0), (2, 4.0, 4.5), (3, 9.0, 8.0), (4, 3.0, None)])
    for stop in split(conn, "R2").values():
        parts = [stop["brought_in_min"], stop["created_en_route_min"], stop["created_at_stop_min"]]
        assert stop["brought_in_min"] is not None
        total = sum(p for p in parts if p is not None)
        assert total == pytest.approx(stop["delay_after_stop_min"])


def test_ride_entering_the_region_midway_has_unknown_brought_in(conn):
    add_ride(conn, "R3", [(4, 3.0, 4.0), (5, 6.0, 6.0)])
    s = split(conn, "R3")
    assert s[4]["brought_in_min"] is None and s[4]["created_en_route_min"] is None  # unknown, not zero
    assert s[5]["brought_in_min"] == 4.0 and s[5]["created_en_route_min"] == 2.0


def test_gap_in_station_numbers_is_flagged(conn):
    add_ride(conn, "R4", [(1, None, 0.0), (4, 2.0, 2.0)])
    s = split(conn, "R4")
    assert s[1]["gap_before"] is False and s[4]["gap_before"] is True
    assert s[4]["brought_in_min"] == 0.0


def test_missing_actual_times_give_null_parts_not_guesses(conn):
    add_ride(conn, "R5", [(1, None, 1.0), (2, None, None), (3, 5.0, 5.0)])
    s = split(conn, "R5")
    assert s[2]["created_en_route_min"] is None and s[2]["created_at_stop_min"] is None
    assert s[3]["brought_in_min"] is None  # previous departure delay is unknown


def test_rides_do_not_leak_into_each_other(conn):
    add_ride(conn, "R6", [(1, None, 7.0), (2, 7.0, 7.0)])
    add_ride(conn, "R7", [(1, None, 0.0), (2, 1.0, 1.0)])
    assert split(conn, "R7")[2]["brought_in_min"] == 0.0
    assert split(conn, "R6")[2]["brought_in_min"] == 7.0
