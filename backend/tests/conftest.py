"""Test configuration: an isolated SQLite database loaded with a tiny GTFS network.

Mini network (weekdays in 2026, except Monday 2026-09-28):

    Villingen --RB 42 19:40/20:40 (31 min)--> Rottweil --RE 87 20:17/21:17/23:30--> Stuttgart
    Villingen --IC 2 19:50 -> 21:10--> Stuttgart            (long distance: no Deutschlandticket)
    Rottweil  --bus 550 20:20--> Dorf                        (bus in the region)
    Stuttgart --bus 99--> ...                                (bus outside the region)
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="heimkommen-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["ARTIFACTS_DIR"] = str(_TMP / "artifacts")
os.environ["DATA_DIR"] = str(_TMP)
os.environ["JWT_SECRET"] = "test-secret"
os.environ.pop("REDIS_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import engine, init_db  # noqa: E402
from app.engine.delay_model import DelayModel  # noqa: E402
from app.engine.planners import Planner  # noqa: E402
from app.engine.timetable import TimetableStore  # noqa: E402
from app.etl.gtfs_loader import GTFSLoader, RegionFilter  # noqa: E402
from app.services import engine_state  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
MINI_GTFS = FIXTURES / "mini_gtfs"
FRIDAY = __import__("datetime").date(2026, 9, 25)
STATION_EVA = {
    "de:08326:1_Parent": "08000366",
    "de:08325:2_Parent": "08000322",
    "de:08111:3_Parent": "08000096",
}


@pytest.fixture(scope="session")
def loaded_db():
    init_db()
    stats = GTFSLoader(MINI_GTFS, region=RegionFilter()).ingest(engine)
    return stats


@pytest.fixture(scope="session")
def store(loaded_db) -> TimetableStore:
    return TimetableStore.load(engine, cache_path=None)


@pytest.fixture(scope="session")
def planner(store) -> Planner:
    return Planner(store, DelayModel.prior(), STATION_EVA, runs=2000, seed=1)


@pytest.fixture()
def api(store, planner):
    engine_state.set_engine(engine_state.Engine(store, planner.model, STATION_EVA, planner))
    from app.main import app

    with TestClient(app) as client:
        yield client
    engine_state.set_engine(None)
