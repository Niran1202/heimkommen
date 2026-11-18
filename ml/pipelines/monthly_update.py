"""Monthly refresh: fetch new piebro months, keep a rolling 6-month window, retrain, optionally upload.

    python ml/pipelines/monthly_update.py [--window 6] [--upload user@host] [--dry-run]

Run on the laptop on/after the 10th of each month (see scripts/schedule_monthly_update.ps1).
1. Find the months published upstream (HEAD request) up to the last complete month.
2. Download + filter the ones missing in data/processed (download_data.py).
3. Delete processed (and raw) months older than the window.
4. Train with the two newest months as test set. train.py only activates the new model if it is
   at least as good as the current one.
5. With --upload, push the artifacts to the server (scripts/upload_artifacts.sh).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
URL = "https://huggingface.co/datasets/piebro/deutsche-bahn-data/resolve/main/monthly_processed_data/data-{month}.parquet"


def month_range(end: date, count: int) -> list[str]:
    """The `count` months ending with the last complete month before `end`."""
    y, m = end.year, end.month
    out = []
    for _ in range(count):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return sorted(out)


def published(month: str) -> bool:
    req = urllib.request.Request(URL.format(month=month), method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30):  # noqa: S310 - fixed https URL
            return True
    except urllib.error.HTTPError:
        return False


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=6, help="Months of history to keep for training")
    parser.add_argument("--upload", metavar="USER@HOST", help="Upload artifacts to the server afterwards")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wanted = [m for m in month_range(date.today(), args.window) if published(m)]
    if len(wanted) < 3:
        raise SystemExit(f"only {wanted} published upstream; nothing to do")
    have = {p.stem.replace("delays-", "") for p in PROCESSED.glob("delays-*.parquet")}
    missing = [m for m in wanted if m not in have]
    print(f"window {wanted}; missing {missing or 'none'}")
    if args.dry_run:
        return

    if missing:
        run([sys.executable, "ml/pipelines/download_data.py", "--months", *missing])
    for old in sorted(have - set(wanted)):
        (PROCESSED / f"delays-{old}.parquet").unlink()
        (ROOT / "data" / "raw" / "piebro" / f"data-{old}.parquet").unlink(missing_ok=True)
        print(f"deleted {old}")
    if not missing:
        print("no new month since the last run; skipping training")
        return

    run([sys.executable, "ml/pipelines/train.py", "--test-months", *wanted[-2:]])
    if args.upload:
        run(["bash", "scripts/upload_artifacts.sh", args.upload])


if __name__ == "__main__":
    main()
