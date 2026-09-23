# Data sources

Heimkommen uses three official data sources. It does **not** use unofficial DB interfaces (DB Navigator backend,
bahn.de web API) and is not affiliated with Deutsche Bahn or NVBW.

## 1. NVBW GTFS timetable, Baden-Württemberg

- Publisher: NVBW – Nahverkehrsgesellschaft Baden-Württemberg mbH, <https://www.nvbw.de/open-data>
- Dataset: "bwgesamt" GTFS feed (all public transport in BW). Imported version: `20260913`, valid 2026-05-03 to
  2026-12-12.
- License: Creative Commons Attribution (CC BY 4.0), as stated on the NVBW open data portal. Check the portal
  for the current terms before deploying.
- Use: rail trips statewide and bus/tram trips in the Schwarzwald-Baar-Heuberg counties, imported into the
  database (`scripts/ingest_gtfs.py`). The feed itself is not redistributed.
- Attribution in the app footer: "Timetable © NVBW".

## 2. Historical delays: piebro/deutsche-bahn-data

- Source: <https://github.com/piebro/deutsche-bahn-data>, data on
  <https://huggingface.co/datasets/piebro/deutsche-bahn-data>
- License: CC BY 4.0, data by Deutsche Bahn (collected from the DB Timetables API).
- Use: monthly processed files (2026-03 to 2026-08) filtered to ~1,000 BW stations for training and evaluation
  (kept on the laptop only); the raw daily API responses of the previous day for the nightly accuracy job.
- Attribution in the app footer and the README.

## 3. DB Timetables API

- Source: DB API Marketplace, <https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables>
  (free plan).
- Use: live status of a journey, only when a user presses "Live status". Responses are cached for 60 seconds
  (planned timetables for an hour) and requests are rate limited to 30/minute. No continuous polling.
- Terms: see the API Marketplace terms of use.

## Also used
- Map tiles © OpenStreetMap contributors (ODbL), loaded only when a user opens a map, following the OSMF tile
  usage policy.
