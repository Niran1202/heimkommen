"""Celery worker + beat schedule (Redis broker).

    celery -A app.workers.celery_app worker --loglevel=info
    celery -A app.workers.celery_app beat --loglevel=info

The same jobs can be run without Celery: ``python scripts/run_job.py etl|eval|retrain``.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

broker = get_settings().redis_url or "redis://localhost:6379/0"

celery_app = Celery("heimkommen", broker=broker, backend=broker,
                    include=["app.workers.tasks_etl", "app.workers.tasks_eval", "app.workers.tasks_retrain"])
celery_app.conf.update(
    timezone=get_settings().timezone,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        # piebro publishes the raw API responses of a day a few hours later.
        "daily-delay-update": {"task": "heimkommen.daily_delay_update", "schedule": crontab(hour=6, minute=15)},
        "nightly-outcome-matching": {"task": "heimkommen.nightly_outcome_matching",
                                     "schedule": crontab(hour=7, minute=0)},
        "weekly-retrain": {"task": "heimkommen.weekly_retrain",
                           "schedule": crontab(day_of_week="sunday", hour=3, minute=30)},
    },
)
