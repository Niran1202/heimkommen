from datetime import date, datetime

from app.db.session import SessionLocal
from app.models.delays import TrainStopHistory
from app.models.prediction import Outcome, PredictionLog
from app.services.outcome_service import match_outcomes
from tests.conftest import FRIDAY


def test_health_and_metrics(api) -> None:
    body = api.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert "heimkommen_http_requests_total" in api.get("/metrics").text


def test_station_search(api) -> None:
    body = api.get("/api/v1/stations", params={"search": "rottw"}).json()
    assert body["stations"][0]["name"] == "Rottweil Bahnhof"
    assert body["stations"][0]["is_rail"] is True


def test_home_check_endpoint(api) -> None:
    response = api.get("/api/v1/journeys/home-check", params={
        "from": "Villingen", "to": "Stuttgart Hbf", "after": "19:00", "date": FRIDAY.isoformat()})
    assert response.status_code == 200
    body = response.json()
    first = body["journeys"][0]
    assert (first["departure"], first["arrival"], first["transfers"]) == ("19:40", "21:32", 1)
    assert first["legs"][0]["origin"]["lat"] == 48.0578
    assert first["weak_point"]["station"] == "Rottweil Bahnhof"
    assert first["connections"][1]["plan_b"]["departure"] == "21:17"
    assert 0 < first["risk"]["p_connections"] < 1
    assert body["last_connection"]["departure"] == "20:40"
    assert any("Buses" in note for note in body["notes"])


def test_home_check_validation_errors(api) -> None:
    base = {"from": "Villingen", "to": "Stuttgart Hbf", "after": "19:00"}
    assert api.get("/api/v1/journeys/home-check", params={**base, "to": "Atlantis"}).status_code == 422
    assert api.get("/api/v1/journeys/home-check", params={**base, "after": "7pm"}).status_code == 422
    outside = api.get("/api/v1/journeys/home-check", params={**base, "date": "2030-01-01"})
    assert outside.status_code == 422 and "outside the imported timetable" in outside.json()["detail"]


def test_deadline_endpoint(api) -> None:
    body = api.get("/api/v1/journeys/deadline", params={
        "from": "Villingen", "to": "Stuttgart Hbf", "arrive_by": "22:00", "date": FRIDAY.isoformat(),
        "confidence": 0.5}).json()
    assert body["recommended"]["departure"] == "19:40"
    assert body["p_arrive_by"] >= 0.5


def test_live_endpoint_without_credentials_is_honest(api) -> None:
    body = api.get("/api/v1/journeys/home-check", params={
        "from": "Villingen", "to": "Stuttgart Hbf", "after": "19:00", "date": FRIDAY.isoformat()}).json()
    live = api.get(f"/api/v1/journeys/{body['journeys'][0]['id']}/live").json()
    assert live["available"] is False
    assert "credentials" in live["notes"][0]
    assert api.get("/api/v1/journeys/not-an-id/live").status_code == 422


def test_register_login_trips_and_account_deletion(api) -> None:
    credentials = {"email": "Ana@example.org", "password": "long enough password"}
    assert api.post("/api/v1/auth/register", json=credentials).status_code == 201
    assert api.post("/api/v1/auth/register", json=credentials).status_code == 409
    assert api.post("/api/v1/auth/login", json={**credentials, "password": "wrong password"}).status_code == 401
    token = api.post("/api/v1/auth/login", json={**credentials, "email": "ana@example.org"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert api.get("/api/v1/me/trips").status_code == 401
    created = api.post("/api/v1/me/trips", headers=headers, json={
        "label": "Home from work", "from_station_id": "Stuttgart Hbf", "to_station_id": "Villingen",
        "usual_departure": "18:30"})
    assert created.status_code == 201
    assert created.json()["to_station_name"] == "Villingen Bahnhof"
    trips = api.get("/api/v1/me/trips", headers=headers).json()
    assert len(trips) == 1

    assert api.delete("/api/v1/me", headers=headers).status_code == 204
    assert api.get("/api/v1/me", headers=headers).status_code == 401
    with SessionLocal() as db:
        from app.models.user import SavedTrip

        assert db.query(SavedTrip).count() == 0


def test_outcome_matching_and_accuracy(api) -> None:
    day = date(2026, 9, 24)
    legs = [
        {"trip_id": "rb1", "train_number": "69755", "category": "RB", "from_eva": "08000366", "to_eva": "08000322",
         "departure": 19 * 3600 + 40 * 60, "arrival": 20 * 3600 + 11 * 60, "change_before": 0},
        {"trip_id": "re1", "train_number": "50182", "category": "RE", "from_eva": "08000322", "to_eva": "08000096",
         "departure": 20 * 3600 + 17 * 60, "arrival": 21 * 3600 + 32 * 60, "change_before": 240},
    ]
    with SessionLocal() as db:
        prediction = PredictionLog(
            journey_key="j1", service_date=day, from_station_id="de:08326:1_Parent", to_station_id="de:08111:3_Parent",
            planned_departure="19:40", planned_arrival="21:32", p_on_time=0.6, p_stranded=0.1, p_connections=0.7,
            legs=legs, model_version="prior-0")
        db.add(prediction)

        def stop(sid, number, eva, dep=None, dep_actual=None, arr=None, arr_actual=None):
            return TrainStopHistory(id=sid, eva=eva, station_name="", train_number=number, service_date=day.isoformat(),
                                    departure_planned=dep, departure_actual=dep_actual, arrival_planned=arr,
                                    arrival_actual=arr_actual)

        t = lambda h, m: datetime(2026, 9, 24, h, m)  # noqa: E731
        db.add_all([
            stop("a", "69755", "08000366", dep=t(19, 40), dep_actual=t(19, 42)),
            stop("b", "69755", "08000322", arr=t(20, 11), arr_actual=t(20, 16)),  # 5 min late: 20:16 + 4 > 20:17
            stop("c", "50182", "08000322", dep=t(20, 17), dep_actual=t(20, 18)),
            stop("d", "50182", "08000096", arr=t(21, 32), arr_actual=t(21, 33)),
        ])
        db.commit()
        counts = match_outcomes(db, None, day)
        assert counts == {"missed_connection": 1}
        outcome = db.query(Outcome).one()
        assert outcome.connections_held is False

    body = api.get("/api/v1/accuracy", params={"period": "365d"}).json()
    assert body["live"]["matched_predictions"] == 1
    assert body["live"]["brier"]["connections"] == round(0.7 ** 2, 4)
    assert body["live"]["brier"]["timetable_only_connections"] == 1.0
