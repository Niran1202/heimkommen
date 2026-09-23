import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.accuracy import router as accuracy_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.journeys import router as journeys_router
from app.api.v1.me import router as me_router
from app.api.v1.stations import router as stations_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import LATENCY, REQUESTS
from app.db.session import init_db
from app.services.engine_state import TimetableUnavailable, get_engine

log = logging.getLogger(__name__)


def _warm_up() -> None:
    try:
        get_engine()
    except TimetableUnavailable as exc:
        log.warning("timetable not available yet: %s", exc)
    except Exception:  # pragma: no cover
        log.exception("engine warm-up failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    init_db()
    if get_settings().app_env != "test":
        # Load the timetable in the background so /health answers immediately.
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(
    title="Heimkommen API",
    version="1.0.0",
    description="Regional journey planning with delay risk for Schwarzwald-Baar-Heuberg. "
                "Not an official Deutsche Bahn service.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    # Label by route template, not raw URL, to keep metric cardinality small.
    path = getattr(route, "path", "unmatched")
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    LATENCY.labels(path).observe(time.perf_counter() - started)
    return response


app.include_router(health_router)
app.include_router(stations_router)
app.include_router(journeys_router)
if get_settings().accounts_enabled:
    app.include_router(auth_router)
    app.include_router(me_router)
app.include_router(accuracy_router)


_static = get_settings().static_dir
if _static is not None and (_static / "index.html").exists():
    static_root: Path = _static.resolve()
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Serve the React app; unknown paths fall back to index.html (client-side routing)."""
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (static_root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_root):
            return FileResponse(candidate)
        return FileResponse(static_root / "index.html")
else:

    @app.get("/")
    def read_root() -> dict[str, str]:
        return {"message": "Heimkommen backend is running", "docs": "/docs"}
