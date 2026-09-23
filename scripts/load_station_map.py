"""Load ml/artifacts/station_map.csv (made locally by match_stations.py) into the database.

Used on the server, where the large delay files needed for matching are not available.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, insert  # noqa: E402

from app.db.base import table_of  # noqa: E402
from app.db.session import engine, init_db  # noqa: E402
from app.models.timetable import StationMap  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "ml" / "artifacts" / "station_map.csv"
    with path.open(encoding="utf-8") as handle:
        rows = [{**r, "score": float(r["score"])} for r in csv.DictReader(handle)]
    init_db()
    with engine.begin() as conn:
        conn.execute(delete(table_of(StationMap)))
        conn.execute(insert(table_of(StationMap)), rows)
    print(f"loaded {len(rows)} station matches")


if __name__ == "__main__":
    main()
