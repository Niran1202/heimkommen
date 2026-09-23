from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    trips: Mapped[list["SavedTrip"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class SavedTrip(Base):
    __tablename__ = "saved_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str | None] = mapped_column(String)
    from_station_id: Mapped[str] = mapped_column(String, nullable=False)
    from_station_name: Mapped[str] = mapped_column(String, nullable=False)
    to_station_id: Mapped[str] = mapped_column(String, nullable=False)
    to_station_name: Mapped[str] = mapped_column(String, nullable=False)
    usual_departure: Mapped[str | None] = mapped_column(String)  # "HH:MM"
    regional_only: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="trips")
