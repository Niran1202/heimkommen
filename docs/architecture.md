# Architecture

```mermaid
flowchart TB
  subgraph offline["Offline, on the laptop"]
    HF[piebro monthly parquet<br/>all of Germany, ~600 MB/month] -->|download_data.py| PR[data/processed<br/>BW stations only, ~65 MB/month]
    PR -->|train.py| ART[ml/artifacts/delay_model_vN<br/>8 LightGBM boosters + tables]
    PR -->|evaluate_replay.py| EV[evaluation.json + charts]
    SM[match_stations.py] --> CSV[station_map.csv]
  end

  subgraph server["Server: docker-compose.prod.yml"]
    CADDY[Caddy<br/>HTTPS, static React app] --> API
    API[FastAPI] --> ENG
    subgraph ENG[Engine, in memory]
      TT[TimetableStore<br/>patterns per service day] --> RAP[RAPTOR]
      DM[DelayModel] --> SIM[Monte Carlo simulator]
      RAP --> PL[Planners: home check,<br/>deadline, Plan B]
      SIM --> PL
    end
    API --> PG[(Postgres)]
    API --> RD[(Redis<br/>live cache)]
    API --> DBAPI[DB Timetables API]
    WORKER[Celery worker + beat] --> PG
    PROM[Prometheus] --> API
    GRAF[Grafana] --> PROM
  end
  ART -. upload_artifacts.sh .-> DM
  CSV -. upload_artifacts.sh .-> PG
```

## Components

| Path | What it does |
|---|---|
| `backend/app/etl/gtfs_loader.py` | Streams the 700 MB NVBW ZIP (10M stop times) and keeps rail statewide plus buses in the region: 66k trips / 1.1M stop times, 80 s. Times are stored as seconds so `25:10:00` works. |
| `backend/app/etl/station_matching.py` | GTFS station ↔ EVA number by timetable co-occurrence (votes counted per distinct train), name fallback. |
| `backend/app/engine/timetable.py` | Loads the timetable once (pickle cache), groups trips into *patterns* (same route, same stop sequence), builds a per-day view including after-midnight trips of the previous day. |
| `backend/app/engine/raptor.py` | Round-based RAPTOR with change times, footpaths between platforms, pickup/drop-off rules, a Deutschlandticket filter, Pareto set by (arrival, transfers); `journey_options` runs successive queries. 0.1–0.15 s per query on the full regional network. |
| `backend/app/engine/delay_model.py` | Loads the active LightGBM quantile models; predicts departure/arrival delay quantiles and cancellation probability per leg. Falls back to prior distributions if no artifact exists. |
| `backend/app/engine/simulator.py` | Vectorised (NumPy) Monte Carlo: inverse-CDF sampling from quantiles, cancellations, transfer checks, rerouting to alternatives, stranding. 5,000 runs of a 3-leg journey with alternatives in well under 1 s. Seedable. |
| `backend/app/engine/planners.py` | Home check (options + last connections + latest safe departure), deadline planner (walks back from the deadline), Plan B (most-used alternative per failed connection), weak point. |
| `backend/app/services/*` | API mapping, prediction logging, live status, nightly outcome matching, accuracy statistics. |
| `backend/app/workers/*` | Celery tasks: daily delay ETL (raw piebro API responses for yesterday), nightly outcome matching, weekly retrain with a "only if better" gate. `scripts/run_job.py` runs them without Celery. |
| `frontend/` | React + TypeScript + Vite, types generated from the OpenAPI schema (`npm run gen:api`), Leaflet/OSM map, light and dark mode, phone-first. |

## Request flow: get-home check

1. Resolve station names or ids, and the service day (today by default, in Europe/Berlin).
2. RAPTOR: next options after the requested time, plus the last connections of the night (searching backwards
   from 03:00 hour by hour).
3. For each journey: predict delay quantiles per leg, find two alternatives from every transfer station (cached per
   request and in an LRU cache across requests), simulate 2,000 evenings.
4. Latest safe departure = the latest journey whose probability to get home ≥ the requested confidence.
5. Log every shown prediction to `predictions`.

Typical latency on a laptop: 1–4 s per home check, most of it RAPTOR calls for alternatives.

## Data kept where

| Data | Size | Where |
|---|---|---|
| NVBW GTFS ZIP | 700 MB | downloaded, imported, deleted on the server |
| Regional timetable (DB) | ~270 MB SQLite / similar in Postgres | server |
| Raw piebro monthly files | ~600 MB/month | laptop only (can be deleted after filtering) |
| Filtered delay history | ~65 MB/month | laptop only |
| Model artifact | ~28 MB | server (`ml/artifacts`, gitignored, released via GitHub Releases) |
| `train_stop_history` (yesterday's actuals) | ~110k rows/day for region stations | server, for the nightly accuracy job |

## Deployment

One small Azure for Students VM (B1ms/B2s, Ubuntu) runs `docker-compose.prod.yml`:

1. Create the VM, give it a DNS label (`<name>.westeurope.cloudapp.azure.com`), open ports 80/443 only.
2. `git clone` the repository to `~/heimkommen`, create `.env` from `.env.example` (set `DOMAIN`,
   `POSTGRES_PASSWORD`, `JWT_SECRET`, `GRAFANA_ADMIN_PASSWORD`, DB API keys).
3. From the laptop: `scripts/upload_artifacts.sh user@host` (model, evaluation, station map).
4. On the VM: `docker compose -f docker-compose.prod.yml up -d --build`, then
   `GTFS_URL=... scripts/bootstrap_server.sh` (imports the timetable, loads the station map, seeds the demo account).
5. Cron: `30 2 * * * ~/heimkommen/scripts/backup_db.sh`.
6. GitHub Actions `deploy.yml` redeploys on every green build of `main` (secrets `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_SSH_KEY`).

Caddy obtains Let's Encrypt certificates automatically. Grafana is served at `/grafana`; `/metrics` is only
reachable inside the Docker network.
