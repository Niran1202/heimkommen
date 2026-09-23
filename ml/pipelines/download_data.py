"""Download monthly piebro delay files and filter them to Baden-Württemberg stations.

    python ml/pipelines/download_data.py --months 2026-03 2026-04 ... [--keep-raw]

Raw monthly files (~600 MB, all of Germany) go to data/raw/piebro/; the filtered
files (only stations present in station_map) go to data/processed/delays-YYYY-MM.parquet.
Everything stays on the laptop; nothing here is deployed.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

URL = "https://huggingface.co/datasets/piebro/deutsche-bahn-data/resolve/main/monthly_processed_data/data-{month}.parquet"
RAW_DIR = ROOT / "data" / "raw" / "piebro"
OUT_DIR = ROOT / "data" / "processed"
COLUMNS = [
    "id", "eva", "station_name", "train_type", "train_number", "line_number", "final_destination_station",
    "train_line_ride_id", "train_line_station_num", "arrival_planned_time", "arrival_change_time",
    "departure_planned_time", "departure_change_time", "arrival_is_canceled", "departure_is_canceled",
    "is_additional_stop", "is_replacement_train",
]


def download(month: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / f"data-{month}.parquet"
    if target.exists():
        return target
    partial = target.with_suffix(".part")
    print(f"downloading {month} ...")
    urllib.request.urlretrieve(URL.format(month=month), partial)  # noqa: S310 - fixed https URL
    partial.rename(target)
    return target


def region_evas() -> list[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT DISTINCT eva FROM station_map"))]


def filter_month(raw: Path, evas: list[str]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / raw.name.replace("data-", "delays-")
    dataset = ds.dataset(raw, format="parquet")
    table = dataset.to_table(columns=COLUMNS, filter=pc.field("eva").isin(pa.array(evas)))
    # Buses (rail replacement) are out of scope: we treat buses as on time.
    table = table.filter(pc.invert(pc.equal(pc.utf8_lower(table["train_type"]), "bus")))
    pq.write_table(table, out, compression="zstd")
    print(f"{raw.name}: kept {table.num_rows:,} rows -> {out.relative_to(ROOT)}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", nargs="+",
                        default=["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])
    parser.add_argument("--keep-raw", action="store_true", help="Keep the ~600 MB raw monthly files")
    args = parser.parse_args()
    evas = region_evas()
    if not evas:
        raise SystemExit("station_map is empty - run scripts/match_stations.py first")
    for month in args.months:
        raw = download(month)
        filter_month(raw, evas)
        if not args.keep_raw:
            raw.unlink()


if __name__ == "__main__":
    main()
