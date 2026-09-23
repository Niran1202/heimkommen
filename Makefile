PYTHON ?= python
MONTHS ?= 2026-03 2026-04 2026-05 2026-06 2026-07 2026-08

.PHONY: install gtfs stations delays train evaluate notebooks api web worker test lint up down prod seed screenshots

install:
	cd backend && $(PYTHON) -m pip install -e ".[dev]"
	cd frontend && npm ci

gtfs:            ## import data/bwgesamt.zip (regional subset)
	$(PYTHON) scripts/ingest_gtfs.py --path data/bwgesamt.zip

stations:        ## match GTFS stations to DB EVA numbers (needs one piebro month in data/raw/piebro)
	$(PYTHON) scripts/match_stations.py

delays:          ## download + filter piebro monthly delay data (laptop only)
	$(PYTHON) ml/pipelines/download_data.py --months $(MONTHS)

train:
	$(PYTHON) ml/pipelines/train.py

evaluate:
	$(PYTHON) ml/pipelines/evaluate_replay.py

notebooks:
	$(PYTHON) ml/notebooks/build_notebooks.py

api:
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

worker:
	cd backend && celery -A app.workers.celery_app worker --beat --loglevel=info

seed:
	$(PYTHON) scripts/seed_demo.py

screenshots:     ## needs api + web running and playwright installed
	$(PYTHON) scripts/screenshots.py

lint:
	cd backend && ruff check app tests ../scripts ../ml/pipelines ../desktop migrations && mypy app
	cd frontend && npm run lint

test: lint
	cd backend && pytest
	cd frontend && npm run build

up:
	docker compose up --build -d

down:
	docker compose down

prod:
	docker compose -f docker-compose.prod.yml up -d --build
