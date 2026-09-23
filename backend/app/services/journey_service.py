"""Turn planner results into API responses and log predictions."""

from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.engine.features import QUANTILES
from app.engine.planners import EvaluatedJourney
from app.engine.raptor import Journey, parse_hhmm, seconds_to_hhmm
from app.engine.timetable import Station
from app.models.prediction import PredictionLog
from app.schemas.journeys import (
    DeadlineCheck,
    DeadlineResponse,
    HomeCheckResponse,
    JourneyOut,
    JourneyRisk,
    JourneySummary,
    LegOut,
    LegRisk,
    PlanBOut,
    StationOut,
    StopOut,
    TransferOut,
)
from app.services.engine_state import Engine

log = logging.getLogger(__name__)
Q50 = QUANTILES.index(0.5)
Q90 = QUANTILES.index(0.9)


class PlanningError(ValueError):
    """Invalid request (unknown station, date outside the timetable, ...)."""


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def encode_journey_id(journey: Journey) -> str:
    payload = {"d": journey.service_date.isoformat(),
               "l": [[leg.trip_id, leg.board_pos, leg.alight_pos] for leg in journey.legs]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_journey_id(value: str) -> dict:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return {"date": date.fromisoformat(payload["d"]), "legs": [tuple(x) for x in payload["l"]]}
    except (ValueError, KeyError, TypeError) as exc:
        raise PlanningError("invalid journey id") from exc


class JourneyService:
    def __init__(self, eng: Engine) -> None:
        self.eng = eng
        self.store = eng.store

    # ------------------------------------------------------------- inputs
    def resolve(self, value: str) -> Station:
        station = self.store.resolve_station(value)
        if station is None:
            raise PlanningError(f"unknown station: {value}")
        return station

    def service_day(self, value: date | None) -> date:
        day = value or today()
        if self.store.feed_start and self.store.feed_end and not (self.store.feed_start <= day <= self.store.feed_end):
            raise PlanningError(
                f"{day} is outside the imported timetable ({self.store.feed_start} to {self.store.feed_end})")
        return day

    # ------------------------------------------------------------ outputs
    def station_out(self, station: Station) -> StationOut:
        return StationOut(id=station.id, name=station.name, lat=station.lat, lon=station.lon, is_rail=station.is_rail)

    def stop_out(self, stop_idx: int) -> StopOut:
        station = self.store.station_of_stop(stop_idx)
        lat, lon = self.store.stop_coords[stop_idx]
        name = self.store.stop_names[stop_idx]
        platform = None
        if name != station.name and name.startswith(station.name):
            platform = name[len(station.name):].strip(" ,") or None
        return StopOut(station_id=station.id, name=station.name, platform=platform,
                       lat=lat if lat is not None else station.lat, lon=lon if lon is not None else station.lon)

    def journey_out(self, ev: EvaluatedJourney) -> JourneyOut:
        journey, result = ev.journey, ev.result
        legs = []
        for leg, pred in zip(journey.legs, ev.predictions, strict=True):
            legs.append(LegOut(
                route=leg.route or leg.category, category=leg.category, headsign=leg.headsign,
                train_number=leg.train_number, origin=self.stop_out(leg.from_stop),
                destination=self.stop_out(leg.to_stop), departure=seconds_to_hhmm(leg.departure),
                arrival=seconds_to_hhmm(leg.arrival), duration_minutes=(leg.arrival - leg.departure) // 60,
                risk=LegRisk(modelled=pred.modelled, p_cancel=round(pred.p_cancel, 4),
                             departure_delay_p50=round(float(pred.dep_q[Q50]), 1),
                             arrival_delay_p50=round(float(pred.arr_q[Q50]), 1),
                             arrival_delay_p90=round(float(pred.arr_q[Q90]), 1)),
            ))
        connections = []
        for i, leg in enumerate(journey.legs):
            plan_b = ev.plan_b(i)
            connections.append(TransferOut(
                index=i,
                station=self.store.station_of_stop(leg.from_stop).name,
                planned_buffer_minutes=(leg.departure - journey.legs[i - 1].arrival) // 60 if i else None,
                p_miss=round(result.p_fail_at(i), 4),
                plan_b=self.plan_b_out(plan_b) if plan_b else None,
            ))
        weak = ev.weak_point()
        p_home = ev.p_home
        risk = JourneyRisk(
            p_connections=round(result.p_connections, 4),
            p_home=round(p_home, 4),
            p_stranded=round(result.p_stranded, 4),
            p_on_time=round(ev.p_on_time(), 4),
            arrival_p50=_fmt(result.arrival_quantile(0.5)),
            arrival_p90=_fmt(result.arrival_quantile(0.9)),
            level="low" if p_home >= 0.97 and result.p_connections >= 0.85 else "medium" if p_home >= 0.9 else "high",
        )
        return JourneyOut(
            id=encode_journey_id(journey), service_date=journey.service_date,
            departure=seconds_to_hhmm(journey.departure), arrival=seconds_to_hhmm(journey.arrival),
            duration_minutes=(journey.arrival - journey.departure) // 60, transfers=journey.transfers,
            legs=legs, connections=connections, risk=risk,
            weak_point=connections[weak] if weak is not None and connections[weak].p_miss >= 0.01 else None,
        )

    def plan_b_out(self, journey: Journey) -> PlanBOut:
        parts = [f"{leg.route or leg.category} {seconds_to_hhmm(leg.departure)}" for leg in journey.legs]
        destination = self.store.station_of_stop(journey.legs[-1].to_stop).name
        return PlanBOut(departure=seconds_to_hhmm(journey.departure), arrival=seconds_to_hhmm(journey.arrival),
                        summary=" → ".join(parts) + f" → {destination}", transfers=journey.transfers)

    def summary(self, ev: EvaluatedJourney | None) -> JourneySummary | None:
        if ev is None:
            return None
        return JourneySummary(departure=seconds_to_hhmm(ev.journey.departure),
                              arrival=seconds_to_hhmm(ev.journey.arrival),
                              p_home=round(ev.p_home, 4), journey_id=encode_journey_id(ev.journey))

    def notes(self) -> list[str]:
        notes = ["Buses and trams are assumed to run on time; only train delays are modelled."]
        if self.eng.model.is_prior:
            notes.append("No trained delay model is installed; using generic prior delay distributions.")
        return notes

    # ----------------------------------------------------------- planners
    def home_check(self, from_station: str, to_station: str, after: str, day: date | None,
                   regional_only: bool, confidence: float, db: Session | None = None) -> HomeCheckResponse:
        origin, destination = self.resolve(from_station), self.resolve(to_station)
        service_day = self.service_day(day)
        result = self.eng.planner.home_check(service_day, origin, destination, _parse_time(after), regional_only,
                                             count=get_settings().max_journey_options, confidence=confidence)
        journeys = [self.journey_out(ev) for ev in result["options"]]
        if db is not None:
            self.log_predictions(db, result["options"], journeys, origin, destination)
        notes = self.notes()
        if not journeys:
            notes.append("No connection found for the rest of this service day.")
        return HomeCheckResponse(
            origin=self.station_out(origin), destination=self.station_out(destination), service_date=service_day,
            after=after, regional_only=regional_only, model_version=self.eng.model.version, journeys=journeys,
            latest_safe_departure=self.summary(result["latest_safe"]), last_connection=self.summary(result["last"]),
            confidence=confidence, notes=notes,
        )

    def deadline(self, from_station: str, to_station: str, arrive_by: str, day: date | None, confidence: float,
                 regional_only: bool) -> DeadlineResponse:
        origin, destination = self.resolve(from_station), self.resolve(to_station)
        service_day = self.service_day(day)
        result = self.eng.planner.deadline(service_day, origin, destination, _parse_time(arrive_by), regional_only,
                                           confidence)
        chosen = result["chosen"]
        notes = self.notes()
        if chosen is None:
            notes.append("No departure reaches the destination in time with the requested confidence.")
        return DeadlineResponse(
            origin=self.station_out(origin), destination=self.station_out(destination), service_date=service_day,
            arrive_by=arrive_by, confidence=confidence, regional_only=regional_only,
            model_version=self.eng.model.version,
            recommended=self.journey_out(chosen[0]) if chosen else None,
            p_arrive_by=round(chosen[1], 4) if chosen else None,
            checked=[DeadlineCheck(departure=seconds_to_hhmm(ev.journey.departure),
                                   arrival=seconds_to_hhmm(ev.journey.arrival), p_arrive_by=round(p, 4))
                     for ev, p in result["checked"]],
            notes=notes,
        )

    def log_predictions(self, db: Session, evaluated: list[EvaluatedJourney], journeys: list[JourneyOut],
                        origin: Station, destination: Station) -> None:
        try:
            for ev, out in zip(evaluated, journeys, strict=True):
                db.add(PredictionLog(
                    journey_key=out.id, service_date=out.service_date, from_station_id=origin.id,
                    to_station_id=destination.id, planned_departure=out.departure, planned_arrival=out.arrival,
                    target_minutes=5, p_on_time=out.risk.p_on_time, p_stranded=out.risk.p_stranded,
                    p_connections=out.risk.p_connections,
                    expected_delay=float(ev.result.arrival_quantile(0.5) - ev.journey.arrival) / 60
                    if out.risk.arrival_p50 else 0.0,
                    legs=[{
                        "trip_id": leg.trip_id, "train_number": leg.train_number, "category": leg.category,
                        "from_eva": self.eng.station_eva.get(self.store.station_of_stop(leg.from_stop).id),
                        "to_eva": self.eng.station_eva.get(self.store.station_of_stop(leg.to_stop).id),
                        "departure": leg.departure, "arrival": leg.arrival,
                        "change_before": self.eng.planner.change_time(ev.journey.legs[i - 1], leg) if i else 0,
                    } for i, leg in enumerate(ev.journey.legs)],
                    model_version=self.eng.model.version,
                ))
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            log.exception("could not log predictions")


def _parse_time(value: str) -> int:
    try:
        return parse_hhmm(value)
    except ValueError as exc:
        raise PlanningError(str(exc)) from exc


def _fmt(seconds: float) -> str | None:
    if seconds == float("inf"):
        return None
    return seconds_to_hhmm(int(seconds))
