#!/usr/bin/env bash
# One-time setup on the VM after `docker compose -f docker-compose.prod.yml up -d`:
# download the NVBW feed, import the regional subset, load the station map, seed the demo.
set -euo pipefail
cd "$(dirname "$0")/.."
GTFS_URL="${GTFS_URL:?set GTFS_URL to the current NVBW bwgesamt.zip download link}"
mkdir -p data
curl -fL -o data/bwgesamt.zip "$GTFS_URL"
run() { docker compose -f docker-compose.prod.yml run --rm -v "$PWD/scripts:/scripts:ro" api python "$@"; }
run /scripts/ingest_gtfs.py --path /data/bwgesamt.zip
rm data/bwgesamt.zip
run /scripts/load_station_map.py /artifacts/station_map.csv
run /scripts/seed_demo.py
docker compose -f docker-compose.prod.yml restart api worker
