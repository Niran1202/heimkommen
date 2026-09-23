"""Round-based public transit routing (RAPTOR, Delling et al. 2012).

Labels are kept per round. ``arrival[k][s]`` is the arrival time at stop ``s`` by
vehicle using ``k`` trips; ``ready[k][s]`` is the time a traveller can board at ``s``
after ``k`` trips (arrival + change time, or walking between platforms of a station).
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

from app.engine.timetable import DAY, INF, DayTimetable, TimetableStore

MAX_ROUNDS = 5  # up to four transfers
MAX_TRAVEL = 6 * 3600


@dataclass
class Leg:
    trip_idx: int
    trip_id: str
    route: str
    category: str
    headsign: str | None
    train_number: str | None
    from_stop: int
    to_stop: int
    board_pos: int
    alight_pos: int
    departure: int  # seconds after midnight of the query day (can exceed 86400)
    arrival: int
    service_day_offset: int  # 0 = trip belongs to the query day, -1 = previous day
    stop_count: int  # number of stops in the whole trip (for "position along route")


@dataclass
class Journey:
    legs: list[Leg]
    service_date: date
    walk_before_first: int = 0
    tags: dict = field(default_factory=dict)

    @property
    def departure(self) -> int:
        return self.legs[0].departure

    @property
    def arrival(self) -> int:
        return self.legs[-1].arrival

    @property
    def transfers(self) -> int:
        return len(self.legs) - 1

    def key(self) -> str:
        return "|".join(f"{leg.trip_id}@{leg.board_pos}-{leg.alight_pos}" for leg in self.legs)


PatternFilter = Callable[[str], bool]


class Raptor:
    def __init__(self, store: TimetableStore) -> None:
        self.store = store
        self._cache: OrderedDict[tuple, list[Journey]] = OrderedDict()
        self._cache_lock = threading.Lock()

    # --------------------------------------------------------------- public
    def earliest_arrival(
        self,
        day: date,
        sources: Iterable[int],
        targets: Iterable[int],
        after: int,
        category_filter: PatternFilter | None = None,
        max_rounds: int = MAX_ROUNDS,
        first_board_offset: int = 0,
        max_travel: int = MAX_TRAVEL,
    ) -> list[Journey]:
        """Return the Pareto set (arrival time, number of trips) of journeys.

        ``first_board_offset`` is added to ``after`` before the first boarding (used by the
        simulator when a traveller arrives at a stop and has to change).
        """
        tt = self.store.for_day(day)
        sources = list(sources)
        target_set = set(targets)
        if not sources or not target_set:
            return []
        n = len(self.store.stop_ids)
        start = after + first_board_offset

        best = [INF] * n  # earliest arrival by vehicle at any round (for pruning)
        ready_prev = [INF] * n
        ready_parent_prev: list[int] = [-1] * n  # stop we arrived at (vehicle) before walking/changing
        for s in sources:
            ready_prev[s] = start
            ready_parent_prev[s] = -2  # source marker
        marked = set(sources)

        rounds_arrival: list[list[int]] = []
        rounds_vehicle: list[dict[int, tuple[int, int, int, int]]] = []
        rounds_ready_parent: list[list[int]] = [ready_parent_prev]
        rounds_ready: list[list[int]] = [ready_prev]
        allowed = self._allowed_patterns(tt, category_filter)
        # No regional journey takes longer than ``max_travel``: prune everything beyond it.
        best_target = start + max_travel

        for k in range(1, max_rounds + 1):
            queue: dict[int, int] = {}
            for stop in marked:
                for pat_idx, pos in tt.stop_patterns[stop]:
                    if allowed is not None and not allowed[pat_idx]:
                        continue
                    if pos < queue.get(pat_idx, 1 << 30):
                        queue[pat_idx] = pos
            arrival = [INF] * n
            vehicle: dict[int, tuple[int, int, int, int]] = {}
            improved: set[int] = set()

            for pat_idx, first_pos in queue.items():
                pattern = tt.patterns[pat_idx]
                stops = pattern.stops_list
                dep_cols = pattern.dep_cols
                raw_cols = pattern.dep_raw_cols
                arr_rows = pattern.arr_rows
                n_trips = len(arr_rows)
                row = -1
                board_pos = -1
                trip_arr = None
                for pos in range(first_pos, len(stops)):
                    stop = stops[pos]
                    if trip_arr is not None:
                        a = trip_arr[pos]
                        if a < best[stop] and a < best_target:
                            arrival[stop] = a
                            best[stop] = a
                            vehicle[stop] = (pat_idx, row, board_pos, pos)
                            improved.add(stop)
                            if stop in target_set:
                                best_target = a
                    r = ready_prev[stop]
                    if r >= INF:
                        continue
                    column = dep_cols[pos]
                    if row >= 0 and r > column[row]:
                        continue
                    # Raw departures are sorted (rows ordered by first departure, FIFO trips);
                    # ``column`` is INF where boarding is not allowed.
                    cand = bisect_left(raw_cols[pos], r)
                    limit = row if row >= 0 else n_trips
                    while cand < limit and (column[cand] < r or column[cand] >= INF):
                        cand += 1
                    if cand < limit:
                        row = cand
                        board_pos = pos
                        trip_arr = arr_rows[row]

            ready = list(ready_prev)
            ready_parent = list(ready_parent_prev)
            next_marked: set[int] = set()
            for stop in improved:
                t_change = arrival[stop] + self.store.change_time[stop]
                if t_change < ready[stop]:
                    ready[stop] = t_change
                    ready_parent[stop] = stop * 8 + k
                    next_marked.add(stop)
                for other, walk in self.store.footpaths[stop]:
                    t_walk = arrival[stop] + walk
                    if t_walk < ready[other]:
                        ready[other] = t_walk
                        ready_parent[other] = stop * 8 + k
                        next_marked.add(other)

            rounds_arrival.append(arrival)
            rounds_vehicle.append(vehicle)
            rounds_ready.append(ready)
            rounds_ready_parent.append(ready_parent)
            ready_prev, ready_parent_prev = ready, ready_parent
            marked = next_marked
            if not marked:
                break

        journeys: list[Journey] = []
        best_so_far = INF
        for k, arrival in enumerate(rounds_arrival, start=1):
            candidates = [(arrival[t], t) for t in target_set if arrival[t] < INF]
            if not candidates:
                continue
            arr_time, target = min(candidates)
            if arr_time >= best_so_far:
                continue
            best_so_far = arr_time
            legs = self._reconstruct(tt, k, target, rounds_vehicle, rounds_ready_parent)
            if legs:
                journeys.append(Journey(legs=legs, service_date=day))
        return journeys

    def journey_options(
        self,
        day: date,
        sources: list[int],
        targets: list[int],
        after: int,
        count: int = 4,
        category_filter: PatternFilter | None = None,
        until: int | None = None,
    ) -> list[Journey]:
        """Successive earliest-arrival journeys departing after ``after`` (a simple range query)."""
        key = (day, tuple(sources), tuple(targets), after, count, getattr(category_filter, "__name__", None), until)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return list(self._cache[key])
        options = self._journey_options(day, sources, targets, after, count, category_filter, until)
        with self._cache_lock:
            self._cache[key] = options
            while len(self._cache) > 512:
                self._cache.popitem(last=False)
        return list(options)

    def _journey_options(self, day, sources, targets, after, count, category_filter, until) -> list[Journey]:
        options: list[Journey] = []
        seen: set[str] = set()
        t = after
        for _ in range(count * 3):
            found = self.earliest_arrival(day, sources, targets, t, category_filter)
            if not found:
                break
            # Prefer the fewest transfers among journeys arriving within 5 minutes of the best.
            fastest = min(j.arrival for j in found)
            journey = min((j for j in found if j.arrival <= fastest + 300), key=lambda j: (j.transfers, j.arrival))
            if until is not None and journey.departure > until:
                break
            if journey.key() not in seen:
                seen.add(journey.key())
                options.append(journey)
                if len(options) >= count:
                    break
            t = journey.departure + 60
        return options

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _allowed_patterns(tt: DayTimetable, category_filter: PatternFilter | None) -> list[bool] | None:
        if category_filter is None:
            return None
        return [category_filter(p.base.category) for p in tt.patterns]

    def _reconstruct(self, tt: DayTimetable, k: int, target: int,
                     rounds_vehicle: list[dict], rounds_ready_parent: list[list[int]]) -> list[Leg]:
        legs: list[Leg] = []
        stop = target
        while k >= 1:
            entry = rounds_vehicle[k - 1].get(stop)
            if entry is None:
                return []
            pat_idx, row, board_pos, alight_pos = entry
            pattern = tt.patterns[pat_idx]
            trip_idx = int(pattern.trips[row])
            trip = self.store.trips[trip_idx]
            board_stop = int(pattern.base.stops[board_pos])
            offset = int(pattern.day_offset[row])
            legs.append(Leg(
                trip_idx=trip_idx,
                trip_id=trip.trip_id,
                route=trip.route_name,
                category=trip.category,
                headsign=trip.headsign,
                train_number=trip.train_number,
                from_stop=board_stop,
                to_stop=stop,
                board_pos=board_pos,
                alight_pos=alight_pos,
                departure=int(pattern.dep_raw[row, board_pos]),
                arrival=int(pattern.arr[row, alight_pos]),
                service_day_offset=offset,
                stop_count=len(pattern.base.stops),
            ))
            parent = rounds_ready_parent[k - 1][board_stop]
            if parent < 0 or k == 1:
                break
            stop, k = divmod(parent, 8)
        legs.reverse()
        return legs


def seconds_to_hhmm(value: int) -> str:
    value = int(value) % DAY if value >= 2 * DAY else int(value)
    hours, rem = divmod(value, 3600)
    return f"{hours % 24:02d}:{rem // 60:02d}"


def parse_hhmm(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"expected HH:MM, got {value!r}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60
