"""Prometheus metrics (scraped from /metrics by the self-hosted Prometheus)."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter("heimkommen_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "heimkommen_http_request_seconds", "HTTP request latency", ["route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)
PLANNER_SECONDS = Histogram(
    "heimkommen_planner_seconds", "Planner (routing + simulation) time", ["planner"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)
JOB_RUNS = Counter("heimkommen_job_runs_total", "Background job runs", ["job", "outcome"])
LIVE_API_CALLS = Counter("heimkommen_db_api_calls_total", "DB Timetables API calls", ["endpoint", "outcome"])
