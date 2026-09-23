"""Process-wide engine: timetable, delay model and planner, loaded lazily once."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import engine
from app.engine.delay_model import DelayModel
from app.engine.planners import Planner
from app.engine.timetable import TimetableStore

log = logging.getLogger(__name__)


class TimetableUnavailable(RuntimeError):
    """No GTFS feed has been imported (or the database is unreachable)."""


@dataclass
class Engine:
    store: TimetableStore
    model: DelayModel
    station_eva: dict[str, str]
    planner: Planner


_lock = threading.Lock()
_engine: Engine | None = None


def _load_station_eva() -> dict[str, str]:
    try:
        with engine.connect() as conn:
            return {r[0]: r[1] for r in conn.execute(text("SELECT station_id, eva FROM station_map"))}
    except SQLAlchemyError:
        return {}


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        settings = get_settings()
        try:
            store = TimetableStore.load(engine, settings.data_dir / "timetable_cache.pkl",
                                        default_change=settings.default_transfer_minutes * 60)
        except SQLAlchemyError as exc:
            raise TimetableUnavailable("timetable database is not reachable") from exc
        if not store.patterns:
            raise TimetableUnavailable("no GTFS timetable has been imported yet")
        model = DelayModel.load(settings.artifacts_dir)
        station_eva = _load_station_eva()
        planner = Planner(store, model, station_eva, runs=settings.simulator_runs)
        _engine = Engine(store, model, station_eva, planner)
        log.info("engine ready: model %s, %s matched stations", model.version, len(station_eva))
        return _engine


def reload_model() -> str:
    """Swap in the currently active model artifact (after a retrain)."""
    current = get_engine()
    model = DelayModel.load(get_settings().artifacts_dir)
    current.model = model
    current.planner.model = model
    return model.version


def set_engine(value: Engine | None) -> None:
    """Used by tests to inject a small engine."""
    global _engine
    _engine = value
