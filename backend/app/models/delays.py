"""Historical train stop records (regional subset of the piebro dataset)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainStopHistory(Base):
    __tablename__ = "train_stop_history"
    __table_args__ = (
        Index("ix_tsh_train_day", "train_number", "eva", "service_date"),
        Index("ix_tsh_eva_time", "eva", "departure_planned"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ride_id: Mapped[str | None] = mapped_column(String, index=True)
    station_num: Mapped[int | None] = mapped_column(Integer)
    eva: Mapped[str] = mapped_column(String, nullable=False)
    station_name: Mapped[str] = mapped_column(String, nullable=False)
    train_type: Mapped[str | None] = mapped_column(String)
    train_number: Mapped[str | None] = mapped_column(String)
    line_number: Mapped[str | None] = mapped_column(String)
    final_destination: Mapped[str | None] = mapped_column(String)
    service_date: Mapped[str | None] = mapped_column(String)  # YYYY-MM-DD of the planned time
    arrival_planned: Mapped[datetime | None] = mapped_column(DateTime)
    arrival_actual: Mapped[datetime | None] = mapped_column(DateTime)
    departure_planned: Mapped[datetime | None] = mapped_column(DateTime)
    departure_actual: Mapped[datetime | None] = mapped_column(DateTime)
    arrival_delay: Mapped[int | None] = mapped_column(Integer)
    departure_delay: Mapped[int | None] = mapped_column(Integer)
    arrival_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    departure_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
