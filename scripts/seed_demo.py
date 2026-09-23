"""Create (or reset) the demo account with a few saved trips.

    python scripts/seed_demo.py [--email demo@heimkommen.example] [--password ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models.user import SavedTrip, User  # noqa: E402
from app.services.engine_state import get_engine  # noqa: E402

TRIPS = [
    ("After work in Stuttgart", "Stuttgart Hauptbahnhof (oben)", "Villingen Bahnhof/ZOB", "18:30"),
    ("Uni Konstanz", "Konstanz Bahnhof", "Villingen Bahnhof/ZOB", "19:30"),
    ("Concert in Freiburg", "Freiburg Hauptbahnhof", "Donaueschingen Bahnhof", "22:00"),
    ("Home to Schonach", "Villingen Bahnhof/ZOB", "Schonach Rathaus", "17:00"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="demo@heimkommen.example")
    parser.add_argument("--password", default="heimkommen-demo")
    args = parser.parse_args()

    init_db()
    store = get_engine().store
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == args.email))
        if existing:
            db.delete(existing)
            db.commit()
        user = User(email=args.email, password_hash=hash_password(args.password))
        db.add(user)
        db.flush()
        for label, origin, destination, departure in TRIPS:
            a, b = store.resolve_station(origin), store.resolve_station(destination)
            if a is None or b is None:
                print(f"skipping {label}: station not in the imported timetable")
                continue
            db.add(SavedTrip(user_id=user.id, label=label, from_station_id=a.id, from_station_name=a.name,
                             to_station_id=b.id, to_station_name=b.name, usual_departure=departure,
                             regional_only=True))
        db.commit()
    print(f"demo account ready: {args.email} / {args.password}")


if __name__ == "__main__":
    main()
