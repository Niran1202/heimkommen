from __future__ import annotations

from datetime import date, timedelta

from app.core.metrics import JOB_RUNS
from app.db.session import SessionLocal, init_db
from app.services.engine_state import TimetableUnavailable, get_engine
from app.services.outcome_service import match_outcomes, retry_unknown
from app.workers.celery_app import celery_app


def nightly_outcome_matching(day: date | None = None) -> dict[str, int]:
    """Compare yesterday's predictions with what really happened."""
    day = day or date.today() - timedelta(days=1)
    init_db()
    try:
        eng = get_engine()
    except TimetableUnavailable:
        eng = None
    db = SessionLocal()
    try:
        # Journeys arriving after midnight only get their data with the next day's ETL:
        # retry the previous day's "unknown" outcomes first.
        retry_unknown(db, day - timedelta(days=1))
        match_outcomes(db, eng, day - timedelta(days=1))
        counts = match_outcomes(db, eng, day)
    except Exception:
        JOB_RUNS.labels("nightly_outcome_matching", "failure").inc()
        raise
    finally:
        db.close()
    JOB_RUNS.labels("nightly_outcome_matching", "success").inc()
    return counts


@celery_app.task(name="heimkommen.nightly_outcome_matching")
def nightly_outcome_matching_task(day: str | None = None) -> dict[str, int]:
    return nightly_outcome_matching(date.fromisoformat(day) if day else None)
