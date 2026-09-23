# 0003 · Train locally, deploy only small artifacts

**Status:** accepted

## Context
The project must run for €0. Six months of delay history are ~3.7 GB of raw parquet (all of Germany) and ~18M
rows for Baden-Württemberg. A managed database or a large VM would use up student credit quickly.

## Decision
- The raw and filtered delay history, feature building, training and the replay evaluation stay on the laptop.
- The server gets: the regional GTFS subset (imported on the server from the official ZIP), the model artifact,
  `station_map.csv`, and a rolling table of yesterday's actual train times (for the accuracy job).
- SQLite for local development (no Docker needed), Postgres in Docker/production; the same SQLAlchemy models and
  Alembic migrations serve both.

## Consequences
- One small VM with Docker Compose is enough; if the credit runs out, everything still runs locally.
- The weekly retrain task only works where the delay data lives (the laptop). On the server the job is disabled
  or points to a mounted data directory.
- New model versions are deployed by uploading the artifact (`scripts/upload_artifacts.sh`), gated by
  "at least as good as the current model".
