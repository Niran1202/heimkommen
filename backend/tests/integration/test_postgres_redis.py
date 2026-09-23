"""Integration tests against real Postgres and Redis (testcontainers).

Skipped automatically when Docker or testcontainers is not available (CI runs them).
"""

import shutil

import pytest

testcontainers = pytest.importorskip("testcontainers")
if shutil.which("docker") is None:
    pytest.skip("docker is not available", allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402
from testcontainers.redis import RedisContainer  # noqa: E402

from app.core.cache import TTLCache  # noqa: E402
from app.db.session import build_engine, init_db  # noqa: E402
from app.engine.raptor import Raptor, parse_hhmm, seconds_to_hhmm  # noqa: E402
from app.engine.timetable import TimetableStore  # noqa: E402
from app.etl.gtfs_loader import GTFSLoader, RegionFilter  # noqa: E402
from tests.conftest import FRIDAY, MINI_GTFS  # noqa: E402


@pytest.fixture(scope="module")
def postgres_engine():
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        db = build_engine(pg.get_connection_url())
        init_db(db)
        yield db
        db.dispose()


def test_gtfs_import_and_routing_on_postgres(postgres_engine) -> None:
    stats = GTFSLoader(MINI_GTFS, region=RegionFilter()).ingest(postgres_engine)
    assert stats.trips == 7
    with postgres_engine.connect() as conn:
        assert conn.execute(text("SELECT MAX(arrival_secs) FROM stop_times")).scalar_one() == 24 * 3600 + 45 * 60
    store = TimetableStore.load(postgres_engine)
    villingen, stuttgart = store.resolve_station("Villingen"), store.resolve_station("Stuttgart Hbf")
    journeys = Raptor(store).earliest_arrival(FRIDAY, villingen.stops, stuttgart.stops, parse_hhmm("19:30"))
    assert seconds_to_hhmm(min(j.arrival for j in journeys)) == "21:10"


def test_redis_cache_roundtrip() -> None:
    with RedisContainer("redis:7-alpine") as redis:
        url = f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"
        cache = TTLCache(url)
        assert cache._redis is not None
        cache.set("k", {"a": 1}, ttl=60)
        assert cache.get("k") == {"a": 1}
