"""Get-home check, deadline planner and Plan B on top of RAPTOR + delay model + simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.engine.categories import allowed_with_deutschlandticket
from app.engine.delay_model import DelayModel, LegPrediction, LegQuery
from app.engine.raptor import Journey, Leg, Raptor
from app.engine.simulator import JourneySimulator, SimJourney, SimLeg, SimResult
from app.engine.timetable import DAY, Station, TimetableStore

ON_TIME_TOLERANCE = 5 * 60
ALTERNATIVES_PER_POINT = 2


@dataclass
class EvaluatedJourney:
    journey: Journey
    predictions: list[LegPrediction]
    result: SimResult
    # For each boarding index: the alternatives that were considered.
    alternatives: dict[int, list[Journey]] = field(default_factory=dict)

    @property
    def p_home(self) -> float:
        return 1.0 - self.result.p_stranded

    def p_on_time(self, tolerance: int = ON_TIME_TOLERANCE) -> float:
        return self.result.p_arrive_by(self.journey.arrival + tolerance)

    def weak_point(self) -> int | None:
        """Index of the boarding (1..n-1 transfers, or 0 = first train) most likely to fail."""
        if not self.journey.legs:
            return None
        probs = [self.result.p_fail_at(i) for i in range(len(self.journey.legs))]
        best = int(np.argmax(probs))
        return best if probs[best] > 0 else None

    def plan_b(self, index: int) -> Journey | None:
        """The alternative used most often when boarding ``index`` failed."""
        used = self.result.alternative_used[self.result.failed_at == index]
        used = used[used >= 0]
        options = self.alternatives.get(index) or []
        if used.size == 0:
            return options[0] if options else None
        return options[int(np.bincount(used).argmax())]


class Planner:
    def __init__(self, store: TimetableStore, model: DelayModel, station_eva: dict[str, str],
                 runs: int = 2000, seed: int | None = None) -> None:
        self.store = store
        self.router = Raptor(store)
        self.model = model
        self.station_eva = station_eva
        self.runs = runs
        self.seed = seed

    # ------------------------------------------------------------ helpers
    def category_filter(self, regional_only: bool):
        return allowed_with_deutschlandticket if regional_only else None

    def options(self, day: date, origin: Station, destination: Station, after: int, count: int,
                regional_only: bool, until: int | None = None) -> list[Journey]:
        found = self.router.journey_options(day, origin.stops, destination.stops, after, count=count + 2,
                                            category_filter=self.category_filter(regional_only), until=until)
        return remove_dominated(found)[:count]

    def eva_of_stop(self, stop_idx: int) -> str | None:
        return self.station_eva.get(self.store.station_of_stop(stop_idx).id)

    def predict(self, journey: Journey) -> list[LegPrediction]:
        weekday = journey.service_date.weekday()
        queries = [LegQuery(
            category=leg.category, route_name=leg.route, train_number=leg.train_number,
            board_eva=self.eva_of_stop(leg.from_stop), alight_eva=self.eva_of_stop(leg.to_stop),
            board_hour=(leg.departure // 3600) % 24, alight_hour=(leg.arrival // 3600) % 24,
            weekday=weekday, board_pos=leg.board_pos, alight_pos=leg.alight_pos, stop_count=leg.stop_count,
        ) for leg in journey.legs]
        return self.model.predict(queries)

    def change_time(self, arrived: Leg, next_leg: Leg) -> int:
        if arrived.to_stop == next_leg.from_stop:
            return self.store.change_time[arrived.to_stop]
        for other, walk in self.store.footpaths[arrived.to_stop]:
            if other == next_leg.from_stop:
                return walk
        return self.store.default_change

    def to_sim_legs(self, journey: Journey, predictions: list[LegPrediction]) -> list[SimLeg]:
        legs = []
        for i, (leg, pred) in enumerate(zip(journey.legs, predictions, strict=True)):
            legs.append(SimLeg(
                planned_dep=leg.departure, planned_arr=leg.arrival, dep_q=pred.dep_q, arr_q=pred.arr_q,
                p_cancel=pred.p_cancel,
                change_before=self.change_time(journey.legs[i - 1], leg) if i > 0 else 0,
            ))
        return legs

    # ------------------------------------------------------------ evaluate
    def evaluate(self, journey: Journey, destination: Station, regional_only: bool,
                 alternatives_cache: dict | None = None, origin: Station | None = None,
                 later_from_origin: list[Journey] | None = None) -> EvaluatedJourney:
        """Simulate ``journey``; ``later_from_origin`` (if known) are the next departures from the
        origin, used when the first train is missed or cancelled."""
        cache = alternatives_cache if alternatives_cache is not None else {}
        predictions = self.predict(journey)
        sim = SimJourney(legs=self.to_sim_legs(journey, predictions))
        alternatives: dict[int, list[Journey]] = {}
        for i, leg in enumerate(journey.legs):
            if i == 0:
                if later_from_origin is not None:
                    alts = [j for j in later_from_origin if j.departure > leg.departure][:ALTERNATIVES_PER_POINT]
                    if alts:
                        alternatives[0] = alts
                        sim.alternatives[0] = [self.to_sim_legs(a, self.predict(a)) for a in alts]
                    continue
                if origin is None:
                    continue
                station = origin
                after = leg.departure + 60
            else:
                station = self.store.station_of_stop(leg.from_stop)
                after = journey.legs[i - 1].arrival
            key = (journey.service_date, station.id, after, regional_only)
            if key not in cache:
                cache[key] = self.options(journey.service_date, station, destination, after,
                                          ALTERNATIVES_PER_POINT, regional_only)
            alts = [a for a in cache[key] if a.key() != _suffix_key(journey, i)]
            if not alts:
                continue
            alternatives[i] = alts
            sim.alternatives[i] = [self.to_sim_legs(a, self.predict(a)) for a in alts]
        result = JourneySimulator(self.runs, self.seed).simulate(sim)
        return EvaluatedJourney(journey, predictions, result, alternatives)

    # ------------------------------------------------------------ planners
    def home_check(self, day: date, origin: Station, destination: Station, after: int, regional_only: bool,
                   count: int = 4, confidence: float = 0.95) -> dict:
        cache: dict = {}
        options = self.options(day, origin, destination, after, count + ALTERNATIVES_PER_POINT, regional_only)
        tail = self.last_connections(day, origin, destination, regional_only)
        tail = [j for j in tail if j.departure >= after]
        known = remove_dominated(options + tail)
        options = options[:count]
        evaluated: dict[str, EvaluatedJourney] = {}

        def get(journey: Journey) -> EvaluatedJourney:
            if journey.key() not in evaluated:
                evaluated[journey.key()] = self.evaluate(journey, destination, regional_only, cache, origin,
                                                         later_from_origin=known)
            return evaluated[journey.key()]

        for journey in options:
            get(journey)
        # Latest safe departure: walk backwards from the last connections of the night.
        last = get(tail[-1]) if tail else None
        latest_safe = None
        for journey in reversed(remove_dominated(tail + options)):
            ev = get(journey)
            if ev.p_home >= confidence:
                latest_safe = ev
                break
        return {"options": [evaluated[j.key()] for j in options], "latest_safe": latest_safe, "last": last}

    def last_connections(self, day: date, origin: Station, destination: Station, regional_only: bool,
                         n: int = 4) -> list[Journey]:
        """The final departures of the service day (searching backwards hour by hour)."""
        for start in range(DAY + 3 * 3600, 10 * 3600, -3600):
            found = self.options(day, origin, destination, start, n, regional_only, until=DAY + 6 * 3600)
            if found:
                earlier = self.options(day, origin, destination, start - 2 * 3600, n + 2, regional_only,
                                       until=DAY + 6 * 3600)
                return remove_dominated(earlier + found)
        return []

    def deadline(self, day: date, origin: Station, destination: Station, arrive_by: int, regional_only: bool,
                 confidence: float, window: int = 4 * 3600) -> dict:
        cache: dict = {}
        candidates = self.options(day, origin, destination, max(arrive_by - window, 0), 12, regional_only,
                                  until=arrive_by)
        candidates = [j for j in candidates if j.arrival <= arrive_by]
        evaluated: list[tuple[EvaluatedJourney, float]] = []
        chosen = None
        for journey in sorted(candidates, key=lambda j: j.departure, reverse=True):
            ev = self.evaluate(journey, destination, regional_only, cache, origin)
            p = ev.result.p_arrive_by(arrive_by)
            evaluated.append((ev, p))
            if p >= confidence:
                chosen = (ev, p)
                break
        return {"chosen": chosen, "checked": evaluated}


def remove_dominated(journeys: list[Journey]) -> list[Journey]:
    """Drop journeys for which a later departure arrives no later."""
    keep: list[Journey] = []
    best_arrival = np.inf
    for journey in sorted(journeys, key=lambda j: (-j.departure, j.arrival, j.transfers)):
        if journey.arrival < best_arrival:
            keep.append(journey)
            best_arrival = journey.arrival
    keep.reverse()
    return keep


def _suffix_key(journey: Journey, index: int) -> str:
    return "|".join(f"{leg.trip_id}@{leg.board_pos}-{leg.alight_pos}" for leg in journey.legs[index:])
