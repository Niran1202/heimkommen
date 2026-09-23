from __future__ import annotations

import subprocess
import sys

from app.core.config import REPO_ROOT
from app.core.metrics import JOB_RUNS
from app.services.engine_state import reload_model
from app.workers.celery_app import celery_app


def weekly_retrain() -> str:
    """Retrain on the latest months; train.py only activates the new model if it scores at
    least as well as the current one. Needs the local delay data (runs on the laptop)."""
    script = REPO_ROOT / "ml" / "pipelines" / "train.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        JOB_RUNS.labels("weekly_retrain", "failure").inc()
        raise RuntimeError(result.stderr[-2000:])
    JOB_RUNS.labels("weekly_retrain", "success").inc()
    version = reload_model()
    return f"active model: {version}\n{result.stdout[-1000:]}"


@celery_app.task(name="heimkommen.weekly_retrain", time_limit=3 * 3600)
def weekly_retrain_task() -> str:
    return weekly_retrain()
