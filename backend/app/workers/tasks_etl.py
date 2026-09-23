from __future__ import annotations

from datetime import date, timedelta

from app.core.config import get_settings
from app.core.metrics import JOB_RUNS
from app.db.session import engine, init_db
from app.etl.delays_loader import load_raw_day, region_evas
from app.workers.celery_app import celery_app


def daily_delay_update(day: date | None = None) -> int:
    """Load yesterday's actual train times for the region's stations into train_stop_history."""
    day = day or date.today() - timedelta(days=1)
    try:
        init_db()
        evas = region_evas(engine)
        count = load_raw_day(engine, day, get_settings().data_dir / "raw" / "daily", evas)
    except Exception:
        JOB_RUNS.labels("daily_delay_update", "failure").inc()
        raise
    JOB_RUNS.labels("daily_delay_update", "success").inc()
    return count


@celery_app.task(name="heimkommen.daily_delay_update", autoretry_for=(OSError,), retry_backoff=600, max_retries=3)
def daily_delay_update_task(day: str | None = None) -> int:
    return daily_delay_update(date.fromisoformat(day) if day else None)
