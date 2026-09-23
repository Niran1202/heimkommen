import math

from fastapi import APIRouter, Query

from app.api.deps import EngineDep
from app.schemas.journeys import StationOut, StationsResponse

router = APIRouter(prefix="/api/v1", tags=["stations"])


@router.get("/stations", response_model=StationsResponse)
def list_stations(
    eng: EngineDep,
    search: str = Query("", max_length=80),
    limit: int = Query(10, ge=1, le=50),
    rail_only: bool = False,
) -> StationsResponse:
    stations = eng.store.search_stations(search, limit=limit, rail_only=rail_only)
    return StationsResponse(
        query=search,
        stations=[StationOut(id=s.id, name=s.name, lat=s.lat, lon=s.lon, is_rail=s.is_rail) for s in stations],
    )


@router.get("/stations/nearby", response_model=StationsResponse)
def nearby_stations(
    eng: EngineDep,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    limit: int = Query(5, ge=1, le=20),
    rail_only: bool = False,
) -> StationsResponse:
    """Closest stations to a position (the browser's geolocation never leaves this request)."""
    scale = math.cos(math.radians(lat))
    candidates = [s for s in eng.store.stations
                  if s.stops and s.lat is not None and s.lon is not None and (s.is_rail or not rail_only)]
    candidates.sort(key=lambda s: (s.lat - lat) ** 2 + ((s.lon - lon) * scale) ** 2)  # type: ignore[operator]
    return StationsResponse(
        query=f"{lat:.4f},{lon:.4f}",
        stations=[StationOut(id=s.id, name=s.name, lat=s.lat, lon=s.lon, is_rail=s.is_rail)
                  for s in candidates[:limit]],
    )
