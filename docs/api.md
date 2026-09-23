# API

Interactive documentation with request/response schemas: `http://localhost:8000/docs` (FastAPI/OpenAPI).
The frontend's TypeScript types are generated from the same schema (`cd frontend && npm run gen:api`).

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | – | Create an account (email + password ≥ 8 chars) → bearer token. 409 if the email exists. |
| POST | `/api/v1/auth/login` | – | Bearer token (JWT, 7 days). 401 on wrong credentials. |
| GET | `/api/v1/stations?search=` | – | Station autocomplete ("Hbf" and "Bf" are expanded). |
| GET | `/api/v1/stations/nearby?lat=&lon=` | – | Closest stations to a position. |
| GET | `/api/v1/journeys/home-check?from=&to=&after=&date=&regional_only=&confidence=` | – | Journeys with risk, weak point, Plan B, latest safe departure, last connection. |
| GET | `/api/v1/journeys/deadline?from=&to=&arrive_by=&date=&confidence=&regional_only=` | – | Latest departure that arrives in time with the requested confidence. |
| GET | `/api/v1/journeys/{id}/live` | – | Live delays for the trains of a journey (DB Timetables API, cached 60 s). |
| GET | `/api/v1/me` | Bearer | Current user. |
| DELETE | `/api/v1/me` | Bearer | Delete the account and all saved trips (204). |
| GET, POST | `/api/v1/me/trips` | Bearer | List / save trips (max 50). |
| DELETE | `/api/v1/me/trips/{id}` | Bearer | Delete a saved trip. |
| GET | `/api/v1/accuracy?period=30d` | – | Live Brier scores and calibration + offline evaluation. |
| GET | `/health` | – | Liveness, database, whether the timetable is loaded, model version. |
| GET | `/metrics` | internal | Prometheus metrics. |

Stations can be given as ids (`de:08326:6592_Parent`) or names (`Villingen`, `Stuttgart Hbf`).

Errors: `422` for invalid input (unknown station, bad time, date outside the timetable) with a readable
`detail`; `503` while no timetable is imported.

## Example

```bash
curl "http://localhost:8000/api/v1/journeys/home-check?from=Stuttgart%20Hbf&to=Villingen&after=20:00&date=2026-09-25"
```

```jsonc
{
  "origin": {"id": "de:08111:6115_Parent", "name": "Stuttgart Hauptbahnhof (oben)", ...},
  "latest_safe_departure": {"departure": "21:14", "arrival": "23:18", "p_home": 0.99, ...},
  "last_connection": {"departure": "22:17", "arrival": "00:28", "p_home": 0.81, ...},
  "journeys": [{
    "departure": "20:23", "arrival": "22:18", "transfers": 1,
    "risk": {"p_connections": 0.37, "p_home": 0.97, "p_on_time": 0.22, "arrival_p50": "23:18", "level": "medium"},
    "weak_point": {"index": 1, "station": "Rottweil Bahnhof", "planned_buffer_minutes": 5, "p_miss": 0.6,
                   "plan_b": {"departure": "22:49", "arrival": "23:18", "summary": "RB 42 22:49 → Villingen Bahnhof/ZOB"}},
    "legs": [...]
  }],
  "model_version": "v1"
}
```
