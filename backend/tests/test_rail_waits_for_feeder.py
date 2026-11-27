"""Tests for rail.waits_for_feeder (phase 4). Synthetic trains in the fake month 2099-01; real data is untouched."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import psycopg
import pytest

URL = os.environ.get("RAIL_DATABASE_URL", "postgresql://rail:rail@localhost:5433/rail")
MONTH = "2099-01"
T0 = datetime(2099, 1, 10, 8, 0)
WINDOW = (datetime(2099, 1, 10), datetime(2099, 1, 11))


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(URL, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("platform Postgres is not running")
    c.execute("SELECT rail.ensure_partition(%s)", (T0,))
    yield c
    c.execute("DROP TABLE IF EXISTS rail.fact_stop_event_2099_01")
    c.close()


def feeder(conn, ride: str, planned: float, actual: float, *, eva: str = "X", cancelled: bool = False) -> None:
    """A train that only arrives at the station (terminus), planned/actual minutes after 08:00."""
    conn.execute(
        """INSERT INTO rail.fact_stop_event (id, event_ts, source_month, ride_id, station_num, eva, station_name,
               arrival_planned, arrival_actual, arrival_delay_min, arrival_cancelled)
           VALUES (%s, %s, %s, %s, 9, %s, 'Station', %s, %s, %s, %s)""",
        (f"{ride}-arr", at(planned), MONTH, ride, eva, at(planned), at(actual), actual - planned, cancelled))


def departure(conn, ride: str, planned: float, actual: float, *, eva: str = "X", cancelled: bool = False) -> None:
    """A train that only departs from the station (origin)."""
    conn.execute(
        """INSERT INTO rail.fact_stop_event (id, event_ts, source_month, ride_id, station_num, eva, station_name,
               departure_planned, departure_actual, departure_delay_min, departure_cancelled)
           VALUES (%s, %s, %s, %s, 1, %s, 'Station', %s, %s, %s, %s)""",
        (f"{ride}-dep", at(planned), MONTH, ride, eva, at(planned), at(actual), actual - planned, cancelled))


def waits(conn, **kwargs) -> list[tuple]:
    args = ", ".join(f"p_{k} => %s" for k in kwargs)
    sql = "SELECT departure_ride_id, feeder_ride_id, held_min, feeder_arrival_delay, planned_transfer_min, " \
          "gap_after_feeder_min FROM rail.waits_for_feeder(%s, %s" + (", " + args if args else "") + ")"
    return conn.execute(sql, (*WINDOW, *kwargs.values())).fetchall()


def test_late_feeder_and_held_departure_is_a_wait(conn):
    feeder(conn, "F", planned=0, actual=7)          # planned 08:00, arrived 08:07
    departure(conn, "D", planned=5, actual=9)       # planned 08:05, left 08:09 (4 min late, 2 min after F)
    assert waits(conn) == [("D", "F", 4.0, 7.0, 5.0, 2.0)]


def test_on_time_departure_is_not_a_wait(conn):
    feeder(conn, "F", planned=0, actual=7)
    departure(conn, "D", planned=5, actual=5)
    assert waits(conn) == []


def test_feeder_that_arrived_before_the_departure_was_due_is_not_blocking(conn):
    feeder(conn, "F", planned=0, actual=4)          # arrived 08:04, before D's planned 08:05
    departure(conn, "D", planned=5, actual=9)       # D is late for some other reason
    assert waits(conn) == []


def test_departure_long_after_the_feeder_is_not_a_wait(conn):
    feeder(conn, "F", planned=0, actual=7)
    departure(conn, "D", planned=5, actual=20)      # left 13 min after F arrived: not waiting for it
    assert waits(conn) == []


def test_unplanned_connections_are_ignored(conn):
    feeder(conn, "F", planned=-30, actual=7)        # planned 35 min before D: not a connection
    departure(conn, "D", planned=5, actual=9)
    assert waits(conn) == []


def test_cancelled_feeder_is_ignored(conn):
    feeder(conn, "F", planned=0, actual=7, cancelled=True)
    departure(conn, "D", planned=5, actual=9)
    assert waits(conn) == []


def test_other_station_is_ignored(conn):
    feeder(conn, "F", planned=0, actual=7, eva="X")
    departure(conn, "D", planned=5, actual=9, eva="Y")
    assert waits(conn) == []


def test_with_several_feeders_the_last_to_arrive_is_chosen(conn):
    feeder(conn, "F1", planned=0, actual=6)
    feeder(conn, "F2", planned=1, actual=8)
    departure(conn, "D", planned=5, actual=10)
    assert [(r[0], r[1]) for r in waits(conn)] == [("D", "F2")]


def test_thresholds_can_be_changed(conn):
    feeder(conn, "F", planned=0, actual=7)
    departure(conn, "D", planned=5, actual=9)
    assert waits(conn, min_hold=5) == []
