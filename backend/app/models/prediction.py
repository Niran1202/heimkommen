"""Prediction log, matched outcomes, and model registry."""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class PredictionLog(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journey_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    from_station_id: Mapped[str] = mapped_column(String, nullable=False)
    to_station_id: Mapped[str] = mapped_column(String, nullable=False)
    planned_departure: Mapped[str] = mapped_column(String, nullable=False)  # HH:MM
    planned_arrival: Mapped[str] = mapped_column(String, nullable=False)
    target_minutes: Mapped[int] = mapped_column(Integer, default=0)  # on-time tolerance
    p_on_time: Mapped[float] = mapped_column(Float, nullable=False)
    p_stranded: Mapped[float] = mapped_column(Float, nullable=False)
    p_connections: Mapped[float] = mapped_column(Float, nullable=False)
    expected_delay: Mapped[float] = mapped_column(Float, default=0.0)
    legs: Mapped[list] = mapped_column(JSON, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), unique=True, index=True
    )
    # "on_time", "late", "missed_connection", "stranded", "unknown"
    status: Mapped[str] = mapped_column(String, nullable=False)
    connections_held: Mapped[bool | None] = mapped_column(Boolean)
    on_time: Mapped[bool | None] = mapped_column(Boolean)
    actual_arrival_delay: Mapped[float | None] = mapped_column(Float)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    train_months: Mapped[str | None] = mapped_column(String)
    test_months: Mapped[str | None] = mapped_column(String)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
