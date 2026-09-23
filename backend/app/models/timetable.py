"""GTFS timetable tables (regional subset of the NVBW feed).

Times are stored as seconds after midnight of the service day, because GTFS allows
values past 24:00:00 for trips that run after midnight.
"""

from datetime import date

from sqlalchemy import Date, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Stop(Base):
    __tablename__ = "stops"

    stop_id: Mapped[str] = mapped_column(String, primary_key=True)
    stop_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_type: Mapped[int] = mapped_column(Integer, default=0)
    parent_station: Mapped[str | None] = mapped_column(String, index=True)
    platform_code: Mapped[str | None] = mapped_column(String)
    # True when at least one rail trip (RE/RB/S/IC/...) serves the stop or its siblings.
    is_rail: Mapped[int] = mapped_column(Integer, default=0)


class Route(Base):
    __tablename__ = "routes"

    route_id: Mapped[str] = mapped_column(String, primary_key=True)
    agency_id: Mapped[str | None] = mapped_column(String)
    route_short_name: Mapped[str] = mapped_column(String, default="")
    route_long_name: Mapped[str | None] = mapped_column(String)
    route_type: Mapped[int] = mapped_column(Integer, default=3)
    # Derived category: FV (long distance), RE, RB, S, TRAM, BUS, SEV, OTHER
    category: Mapped[str] = mapped_column(String, default="OTHER")


class Trip(Base):
    __tablename__ = "trips"

    trip_id: Mapped[str] = mapped_column(String, primary_key=True)
    route_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trip_headsign: Mapped[str | None] = mapped_column(String)
    trip_short_name: Mapped[str | None] = mapped_column(String)
    direction_id: Mapped[int | None] = mapped_column(Integer)


class StopTime(Base):
    __tablename__ = "stop_times"
    __table_args__ = (Index("ix_stop_times_trip_seq", "trip_id", "stop_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String, nullable=False)
    stop_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    arrival_secs: Mapped[int] = mapped_column(Integer, nullable=False)
    departure_secs: Mapped[int] = mapped_column(Integer, nullable=False)
    pickup_type: Mapped[int] = mapped_column(Integer, default=0)
    drop_off_type: Mapped[int] = mapped_column(Integer, default=0)


class Calendar(Base):
    __tablename__ = "calendar"

    service_id: Mapped[str] = mapped_column(String, primary_key=True)
    monday: Mapped[int] = mapped_column(Integer, nullable=False)
    tuesday: Mapped[int] = mapped_column(Integer, nullable=False)
    wednesday: Mapped[int] = mapped_column(Integer, nullable=False)
    thursday: Mapped[int] = mapped_column(Integer, nullable=False)
    friday: Mapped[int] = mapped_column(Integer, nullable=False)
    saturday: Mapped[int] = mapped_column(Integer, nullable=False)
    sunday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)


class CalendarDate(Base):
    __tablename__ = "calendar_dates"
    __table_args__ = (Index("ix_calendar_dates_date", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    exception_type: Mapped[int] = mapped_column(Integer, nullable=False)


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_stop_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    to_stop_id: Mapped[str] = mapped_column(String, nullable=False)
    transfer_type: Mapped[int] = mapped_column(Integer, default=0)
    min_transfer_time: Mapped[int | None] = mapped_column(Integer)


class StationMap(Base):
    """GTFS station (parent stop id) <-> DB EVA number."""

    __tablename__ = "station_map"

    station_id: Mapped[str] = mapped_column(String, primary_key=True)
    eva: Mapped[str] = mapped_column(String, nullable=False, index=True)
    gtfs_name: Mapped[str] = mapped_column(String, nullable=False)
    db_name: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=1.0)
