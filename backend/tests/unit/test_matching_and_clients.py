from datetime import datetime

import httpx

from app.clients.db_timetables import DBTimetablesClient, LiveDataUnavailable
from app.core.cache import TTLCache
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.etl.station_matching import StationMatcher

PLAN = """<?xml version='1.0' encoding='UTF-8'?><timetable station='Villingen(Schwarzw)'>
<s id="123-2609251940-5"><tl f="N" t="p" o="800" c="RB" n="69755"/>
<ar pt="2609251934" pp="1" l="RB42"/><dp pt="2609251940" pp="1" l="RB42"/></s>
<s id="456-2609251951-3"><tl f="N" t="p" o="800" c="RE" n="4738"/><dp pt="2609251951" pp="3" l="RE2"/></s>
</timetable>"""
CHANGES = """<timetable station="Villingen(Schwarzw)" eva="8000366">
<s id="123-2609251940-5" eva="8000366"><ar ct="2609251941"/><dp ct="2609251946" cp="2"/></s>
<s id="456-2609251951-3" eva="8000366"><dp cs="c"/></s>
</timetable>"""


def test_timetable_voting_matches_stations_despite_different_names() -> None:
    gtfs = [("69755", "2026-08-11 19:40", "villingen_parent"), ("69755", "2026-08-11 20:11", "rottweil_parent"),
            ("4738", "2026-08-11 19:51", "villingen_parent"), ("4739", "2026-08-11 20:51", "villingen_parent")]
    db = [("69755", "2026-08-11 19:40", "08000366"), ("69755", "2026-08-11 20:11", "08000322"),
          ("4738", "2026-08-11 19:51", "08000366"), ("4739", "2026-08-11 20:51", "08000366")]
    matches = StationMatcher.match_by_timetable(gtfs, db, min_trains=2)
    assert matches["villingen_parent"][0] == "08000366"
    assert "rottweil_parent" not in matches  # a single train is not enough


def test_timetable_voting_ignores_a_train_number_collision_repeated_every_day() -> None:
    days = [f"2026-08-{d}" for d in (11, 12, 13, 14)]
    # One train number collides with another operator's train at the same minute on every day.
    gtfs = [("81234", f"{d} 07:02", "marxzell") for d in days]
    db = [("81234", f"{d} 07:02", "stolberg") for d in days]
    assert StationMatcher.match_by_timetable(gtfs, db) == {}  # 4 events, but only one train

    # Two trains agree, but the names share no word: needs 5 trains, so it is rejected.
    gtfs += [("81236", f"{d} 08:02", "marxzell") for d in days]
    db += [("81236", f"{d} 08:02", "stolberg") for d in days]
    names = ({"marxzell": "Marxzell"}, {"stolberg": "Stolberg (Rheinl) Hbf"})
    assert StationMatcher.match_by_timetable(gtfs, db, names=names) == {}
    assert StationMatcher.match_by_timetable(gtfs, db)["marxzell"][0] == "stolberg"


def test_name_matching_fallback_uses_core_names() -> None:
    gtfs_stops = [{"stop_id": "S1", "stop_name": "Villingen (Schwarzwald)"},
                  {"stop_id": "S2", "stop_name": "Freiburg Hauptbahnhof"},
                  {"stop_id": "S3", "stop_name": "Rottweil Bahnhof"}]
    rows = [{"eva": "8000150", "name": "Villingen (Schwarzwald)"},
            {"eva": "8000107", "name": "Freiburg (Breisgau) Hbf"},
            {"eva": "8000322", "name": "Rottweil"}]
    matches = StationMatcher.match_stations(gtfs_stops, rows)
    assert matches == {"S1": "8000150", "S2": "8000107", "S3": "8000322"}


def _client(handler, **kwargs) -> DBTimetablesClient:
    return DBTimetablesClient("https://api.example", "id", "key", TTLCache(), transport=httpx.MockTransport(handler),
                              **kwargs)


def test_db_client_merges_plan_and_changes_and_caches() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["DB-Client-Id"] == "id"
        return httpx.Response(200, text=PLAN if "/plan/" in request.url.path else CHANGES)

    client = _client(handler)
    stops = {s.number: s for s in client.station_stops("08000366", datetime(2026, 9, 25, 19, 40))}
    assert stops["69755"].departure_delay == 6
    assert stops["69755"].changed_platform == "2"
    assert stops["4738"].cancelled
    client.station_stops("08000366", datetime(2026, 9, 25, 19, 40))
    assert len(calls) == 2  # second call served from the cache


def test_db_client_rate_limit_and_missing_credentials() -> None:
    client = _client(lambda request: httpx.Response(200, text=PLAN), max_per_minute=1)
    try:
        client._get("/fchg/1", "fchg", 60)
        client._get("/fchg/2", "fchg", 60)
        raise AssertionError("expected rate limit")
    except LiveDataUnavailable as exc:
        assert "rate limit" in str(exc)
    unconfigured = DBTimetablesClient("https://api.example", "", "", TTLCache())
    try:
        unconfigured._get("/fchg/1", "fchg", 60)
        raise AssertionError("expected missing credentials")
    except LiveDataUnavailable as exc:
        assert "credentials" in str(exc)


def test_passwords_and_tokens() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)
    assert decode_access_token(create_access_token(42)) == 42
    assert decode_access_token("not-a-token") is None
