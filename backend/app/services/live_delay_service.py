"""Live status of a planned journey from the DB Timetables API."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.db_timetables import DBTimetablesClient, LiveDataUnavailable
from app.core.cache import get_cache
from app.core.config import get_settings
from app.engine.raptor import seconds_to_hhmm
from app.schemas.journeys import LiveJourneyResponse, LiveStop
from app.services.engine_state import Engine
from app.services.journey_service import PlanningError, decode_journey_id

_client: DBTimetablesClient | None = None


def get_client() -> DBTimetablesClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = DBTimetablesClient(settings.db_api_base_url, settings.db_api_client_id, settings.db_api_key,
                                     get_cache(), ttl=settings.live_cache_seconds)
    return _client


class LiveDelayService:
    def __init__(self, eng: Engine, db: Session, client: DBTimetablesClient | None = None) -> None:
        self.eng = eng
        self.db = db
        self.client = client or get_client()

    def journey_status(self, journey_id: str) -> LiveJourneyResponse:
        decoded = decode_journey_id(journey_id)
        service_date = decoded["date"]
        midnight = datetime.combine(service_date, time())
        stops: list[LiveStop] = []
        notes: list[str] = []
        for trip_id, board_pos, _alight_pos in decoded["legs"]:
            rows = self.db.execute(text(
                "SELECT st.stop_id, st.departure_secs, t.trip_short_name, r.route_short_name, r.category "
                "FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id "
                "WHERE st.trip_id = :trip ORDER BY st.stop_sequence"), {"trip": trip_id}).all()
            if not rows or board_pos >= len(rows):
                raise PlanningError("journey no longer matches the imported timetable")
            stop_id, dep_secs, number, route, category = rows[board_pos]
            station = self.eng.store.station_of_stop(self.eng.store.stop_index[stop_id])
            eva = self.eng.station_eva.get(station.id)
            train = f"{route or category} {number or ''}".strip()
            planned = midnight + timedelta(seconds=int(dep_secs))
            live = LiveStop(station=station.name, eva=eva or "", train=train,
                            planned_departure=seconds_to_hhmm(int(dep_secs)))
            if eva is None or not number:
                notes.append(f"No live data for {train} at {station.name} (bus or unmatched station).")
                stops.append(live)
                continue
            try:
                match = next((s for s in self.client.station_stops(eva, planned)
                              if s.number == number and s.planned_departure == planned), None)
            except LiveDataUnavailable as exc:
                return LiveJourneyResponse(journey_id=journey_id, available=False, source="DB Timetables API",
                                           legs=stops, notes=[str(exc)])
            if match is None:
                notes.append(f"{train} not found in the live timetable at {station.name}.")
            else:
                live.expected_departure = match.changed_departure.strftime("%H:%M") if match.changed_departure else None
                live.delay_minutes = match.departure_delay
                live.cancelled = match.cancelled
                live.platform = match.changed_platform or match.platform
            stops.append(live)
        return LiveJourneyResponse(journey_id=journey_id, available=True, source="DB Timetables API",
                                   legs=stops, notes=notes)
