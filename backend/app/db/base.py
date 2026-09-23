from typing import cast

from sqlalchemy import Table
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative base so one ``create_all`` creates every table."""


def import_all_models() -> None:
    """Register every model on ``Base.metadata``."""
    from app.models import delays, prediction, timetable, user  # noqa: F401


def table_of(model: type[Base]) -> Table:
    """The Core ``Table`` of a mapped class (typed, for bulk insert/delete)."""
    return cast(Table, model.__table__)
