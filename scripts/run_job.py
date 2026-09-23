"""Run a background job directly (without Celery).

    python scripts/run_job.py etl [--date 2026-09-22]
    python scripts/run_job.py eval [--date 2026-09-22]
    python scripts/run_job.py retrain
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=["etl", "eval", "retrain"])
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.job == "etl":
        from app.workers.tasks_etl import daily_delay_update

        print(f"loaded {daily_delay_update(args.date)} stop events")
    elif args.job == "eval":
        from app.workers.tasks_eval import nightly_outcome_matching

        print(nightly_outcome_matching(args.date))
    else:
        from app.workers.tasks_retrain import weekly_retrain

        print(weekly_retrain())


if __name__ == "__main__":
    main()
