import zipfile

from sqlalchemy import create_engine, text

from app.engine.categories import allowed_with_deutschlandticket, classify_route
from app.etl.gtfs_loader import GTFSLoader, RegionFilter, parse_gtfs_time
from tests.conftest import MINI_GTFS


def test_parse_gtfs_time_allows_times_after_midnight() -> None:
    assert parse_gtfs_time("24:45:00") == 24 * 3600 + 45 * 60
    assert parse_gtfs_time("07:05") == 7 * 3600 + 5 * 60
    assert parse_gtfs_time("") is None


def test_region_filter_keeps_all_rail_but_only_regional_buses(loaded_db) -> None:
    assert loaded_db.trips == 7  # 6 trains + the bus in the region; Stuttgart city bus dropped
    assert loaded_db.categories == {"RB": 2, "RE": 3, "FV": 1, "BUS": 1}
    assert loaded_db.non_contiguous_trips == 0


def test_loader_reads_zip_and_stores_seconds(tmp_path) -> None:
    archive = tmp_path / "feed.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for file in MINI_GTFS.iterdir():
            z.write(file, file.name)
    db = create_engine("sqlite:///:memory:")
    stats = GTFSLoader(archive, region=RegionFilter(keep_everything=True)).ingest(db)
    assert stats.trips == 8
    with db.connect() as conn:
        late = conn.execute(text("SELECT arrival_secs FROM stop_times WHERE trip_id='re3' ORDER BY stop_sequence"))
        assert [r[0] for r in late] == [23 * 3600 + 30 * 60, 24 * 3600 + 45 * 60]
        names = conn.execute(text("SELECT COUNT(*) FROM stops WHERE location_type = 1")).scalar_one()
        assert names == 3  # parent stations are imported for the platforms in use


def test_reimport_replaces_instead_of_duplicating(tmp_path) -> None:
    db = create_engine("sqlite:///:memory:")
    GTFSLoader(MINI_GTFS).ingest(db)
    GTFSLoader(MINI_GTFS).ingest(db)
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM trips")).scalar_one() == 8


def test_route_categories_and_deutschlandticket() -> None:
    assert classify_route(2, "ICE") == "FV"
    assert classify_route(2, "RE 87") == "RE"
    assert classify_route(2, "RB42") == "RB"
    assert classify_route(0, "S1") == "S"
    assert classify_route(0, "U12") == "TRAM"
    assert classify_route(3, "550") == "BUS"
    assert classify_route(3, "SEV") == "SEV"
    assert not allowed_with_deutschlandticket("FV")
    assert allowed_with_deutschlandticket("RE")
