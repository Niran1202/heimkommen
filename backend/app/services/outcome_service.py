"""Nightly job logic: match logged predictions with what actually happened."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.categories import MODELLED_CATEGORIES
from app.models.delays import TrainStopHistory
from app.models.prediction import Outcome, PredictionLog
from app.services.engine_state import Engine

log = logging.getLogger(__name__)
ON_TIME_TOLERANCE = timedelta(minutes=5)


def _find(db: Session, train_number: str | None, eva: str | None, planned: datetime, arrival: bool):
    if not train_number or not eva:
        return None
    column = TrainStopHistory.arrival_planned if arrival else TrainStopHistory.departure_planned
    return db.scalar(select(TrainStopHistory).where(
        TrainStopHistory.train_number == train_number, TrainStopHistory.eva == eva, column == planned))


def evaluate_prediction(db: Session, eng: Engine | None, prediction: PredictionLog) -> Outcome:
    midnight = datetime.combine(prediction.service_date, time())
    actual: list[tuple[datetime, datetime, bool]] = []
    for leg in prediction.legs:
        planned_dep = midnight + timedelta(seconds=leg["departure"])
        planned_arr = midnight + timedelta(seconds=leg["arrival"])
        # No delay data for buses: assume they ran as planned.
        if leg.get("category") not in MODELLED_CATEGORIES:
            actual.append((planned_dep, planned_arr, False))  # buses/trams: assumed on time
            continue
        dep = _find(db, leg.get("train_number"), leg.get("from_eva"), planned_dep, arrival=False)
        arr = _find(db, leg.get("train_number"), leg.get("to_eva"), planned_arr, arrival=True)
        if dep is None or arr is None:
            return Outcome(prediction_id=prediction.id, status="unknown")
        cancelled = bool(dep.departure_cancelled or arr.arrival_cancelled)
        actual.append((dep.departure_actual or planned_dep, arr.arrival_actual or planned_arr, cancelled))

    held = True
    failed_index = None
    for i, (dep, _arr, cancelled) in enumerate(actual):
        if cancelled:
            held, failed_index = False, i
            break
        if i > 0:
            change = timedelta(seconds=prediction.legs[i].get("change_before", 240))
            if actual[i - 1][1] + change > dep:
                held, failed_index = False, i
                break
    planned_arrival = midnight + timedelta(seconds=prediction.legs[-1]["arrival"])
    if held:
        arrival = actual[-1][1]
        on_time = arrival <= planned_arrival + ON_TIME_TOLERANCE
        return Outcome(prediction_id=prediction.id, status="on_time" if on_time else "late", connections_held=True,
                       on_time=on_time, actual_arrival_delay=(arrival - planned_arrival).total_seconds() / 60)

    status = "missed_connection"
    if eng is not None and failed_index is not None:
        # Stranded if the timetable has no way on from where the traveller got stuck.
        ready = actual[failed_index - 1][1] if failed_index > 0 else midnight + timedelta(
            seconds=prediction.legs[0]["departure"])
        where = prediction.legs[failed_index]
        stop_station = _station_for_eva(eng, where.get("from_eva"))
        destination = eng.store.resolve_station(prediction.to_station_id)
        if stop_station is not None and destination is not None:
            after = int((ready - midnight).total_seconds())
            options = eng.planner.router.journey_options(prediction.service_date, stop_station.stops,
                                                         destination.stops, after, count=1)
            if not options:
                status = "stranded"
    return Outcome(prediction_id=prediction.id, status=status, connections_held=False, on_time=False)


def _station_for_eva(eng: Engine, eva: str | None):
    if not eva:
        return None
    for station_id, value in eng.station_eva.items():
        if value == eva:
            return eng.store.stations[eng.store.station_index[station_id]]
    return None


def retry_unknown(db: Session, day: date) -> int:
    """Drop "unknown" outcomes of ``day`` so the next matching run tries them again."""
    ids = select(PredictionLog.id).where(PredictionLog.service_date == day)
    stale = db.scalars(select(Outcome).where(Outcome.status == "unknown", Outcome.prediction_id.in_(ids))).all()
    for outcome in stale:
        db.delete(outcome)
    db.commit()
    return len(stale)


def match_outcomes(db: Session, eng: Engine | None, day: date) -> dict[str, int]:
    predictions = db.scalars(
        select(PredictionLog).where(PredictionLog.service_date == day)
        .where(~PredictionLog.id.in_(select(Outcome.prediction_id)))
    ).all()
    counts: dict[str, int] = {}
    for prediction in predictions:
        outcome = evaluate_prediction(db, eng, prediction)
        db.add(outcome)
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    db.commit()
    log.info("matched outcomes for %s: %s", day, counts)
    return counts
