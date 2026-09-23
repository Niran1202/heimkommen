"""Write the model's event-level feature tables to data/features/ (for inspection and notebooks).

    python ml/pipelines/build_features.py [--months 2026-07 2026-08]

train.py builds the same features on the fly with ``app.engine.features.events_from_stops``,
the function the API uses at prediction time, so training and serving cannot drift apart.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine.features import FEATURES, events_from_stops  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "features"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", nargs="*", help="Default: every processed month")
    args = parser.parse_args()
    months = args.months or sorted(p.stem.replace("delays-", "") for p in PROCESSED.glob("delays-*.parquet"))
    OUT.mkdir(parents=True, exist_ok=True)
    for month in months:
        stops = pd.read_parquet(PROCESSED / f"delays-{month}.parquet")
        events = events_from_stops(stops[~stops["is_additional_stop"]])
        columns = ["ride_id", "train_number", "planned", *FEATURES, "delay", "cancelled"]
        events[columns].to_parquet(OUT / f"events-{month}.parquet", index=False)
        print(f"{month}: {len(events):,} events -> data/features/events-{month}.parquet")


if __name__ == "__main__":
    main()
