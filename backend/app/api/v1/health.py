from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.services import engine_state

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    database = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        database = "unreachable"
    eng = engine_state._engine
    return {
        "status": "ok",
        "database": database,
        "timetable_loaded": eng is not None,
        "model_version": eng.model.version if eng else None,
        "accounts_enabled": get_settings().accounts_enabled,
    }


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
