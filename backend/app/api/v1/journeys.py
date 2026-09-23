from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession, EngineDep
from app.core.metrics import PLANNER_SECONDS
from app.schemas.journeys import DeadlineResponse, HomeCheckResponse, LiveJourneyResponse
from app.services.journey_service import JourneyService, PlanningError
from app.services.live_delay_service import LiveDelayService

router = APIRouter(prefix="/api/v1/journeys", tags=["journeys"])

Time = Annotated[str, Query(pattern=r"^\d{1,2}:\d{2}$", examples=["19:30"])]


@router.get("/home-check", response_model=HomeCheckResponse)
def home_check(
    eng: EngineDep,
    db: DbSession,
    from_: Annotated[str, Query(alias="from", min_length=2, description="Station id or name")],
    to: Annotated[str, Query(min_length=2, description="Station id or name")],
    after: Time,
    date_: Annotated[date | None, Query(alias="date", description="Service date (default: today)")] = None,
    regional_only: bool = True,
    confidence: Annotated[float, Query(ge=0.5, le=0.999)] = 0.95,
) -> HomeCheckResponse:
    """Journeys home with stranding risk, weak point, Plan B, and the latest safe departure."""
    with PLANNER_SECONDS.labels("home_check").time():
        try:
            return JourneyService(eng).home_check(from_, to, after, date_, regional_only, confidence, db)
        except PlanningError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/deadline", response_model=DeadlineResponse)
def deadline(
    eng: EngineDep,
    from_: Annotated[str, Query(alias="from", min_length=2)],
    to: Annotated[str, Query(min_length=2)],
    arrive_by: Time,
    date_: Annotated[date | None, Query(alias="date")] = None,
    confidence: Annotated[float, Query(ge=0.5, le=0.999)] = 0.9,
    regional_only: bool = True,
) -> DeadlineResponse:
    """The latest departure that arrives by ``arrive_by`` with at least ``confidence``."""
    with PLANNER_SECONDS.labels("deadline").time():
        try:
            return JourneyService(eng).deadline(from_, to, arrive_by, date_, confidence, regional_only)
        except PlanningError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{journey_id}/live", response_model=LiveJourneyResponse)
def live(journey_id: str, eng: EngineDep, db: DbSession) -> LiveJourneyResponse:
    """Current delays for the trains of a journey (DB Timetables API, cached for 60 s)."""
    try:
        return LiveDelayService(eng, db).journey_status(journey_id)
    except PlanningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
