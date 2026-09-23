from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.services.accuracy_service import live_accuracy, offline_accuracy

router = APIRouter(prefix="/api/v1", tags=["accuracy"])


@router.get("/accuracy")
def accuracy(db: DbSession, period: str = Query("30d", pattern=r"^\d{1,3}d$")) -> dict:
    """Live calibration (predictions matched with what really happened) and offline evaluation."""
    try:
        live = live_accuracy(db, period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"live": live, "offline": offline_accuracy()}
