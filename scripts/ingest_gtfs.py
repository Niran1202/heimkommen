"""Import the NVBW GTFS feed (ZIP or extracted directory) into the Heimkommen database.

    python scripts/ingest_gtfs.py --path data/bwgesamt.zip
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.session import engine, init_db  # noqa: E402
from app.etl.gtfs_loader import DEFAULT_REGION_COUNTIES, GTFSLoader, RegionFilter  # noqa: E402

REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a GTFS feed into Heimkommen.")
    parser.add_argument("--path", type=Path, default=Path("data/bwgesamt.zip"),
                        help="GTFS ZIP file or directory containing the GTFS text files")
    parser.add_argument("--counties", default=",".join(DEFAULT_REGION_COUNTIES),
                        help="County codes (AGS) whose buses/trams are kept; rail is always kept")
    parser.add_argument("--all", action="store_true", help="Import the whole feed without region filtering")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.path.suffix.lower() == ".zip":
        with zipfile.ZipFile(args.path) as archive:
            names = set(archive.namelist())
        missing = [n for n in REQUIRED_FILES if n not in names]
    else:
        missing = [n for n in REQUIRED_FILES if not (args.path / n).exists()]
    if missing:
        raise SystemExit(f"Missing GTFS files in {args.path}: {', '.join(missing)}")

    region = RegionFilter(counties=tuple(c.strip() for c in args.counties.split(",") if c.strip()),
                          keep_everything=args.all)
    init_db()
    started = time.perf_counter()
    stats = GTFSLoader(args.path, region=region).ingest(engine)
    print(f"Imported GTFS feed from {args.path} in {time.perf_counter() - started:.0f}s")
    print(stats)


if __name__ == "__main__":
    main()
