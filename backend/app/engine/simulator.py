"""Monte Carlo journey simulator with rerouting and stranding.

For every run we sample, per leg, a departure delay and an arrival delay (drawn with the
same uniform number, so a late train stays late) and a cancellation. At each transfer the
traveller is ready at ``actual arrival + change time``; if the connecting train has already
left (or is cancelled) they take the first *alternative* continuation from that station
that they can still catch. If there is none, the run is **stranded**.

Simplifications (see docs/assumptions.md): legs are independent of each other; an
alternative's own transfers are simulated but not rerouted again (a missed connection on
the fallback counts as stranded, which is pessimistic); buses/trams run on time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.engine.features import sample_from_quantiles

STRANDED = np.inf


@dataclass
class SimLeg:
    planned_dep: int  # seconds
    planned_arr: int
    dep_q: np.ndarray  # delay quantiles in minutes
    arr_q: np.ndarray
    p_cancel: float
    change_before: int = 0  # seconds needed at the boarding stop after the previous leg arrives


@dataclass
class SimJourney:
    legs: list[SimLeg]
    # alternatives[i]: continuations used when boarding leg i fails (i = 0: next departures
    # from the origin; i > 0: continuations from the transfer station before leg i).
    alternatives: dict[int, list[list[SimLeg]]] = field(default_factory=dict)


@dataclass
class SimResult:
    runs: int
    arrival: np.ndarray  # seconds, inf when stranded
    connections_held: np.ndarray  # bool per run: the planned journey worked end to end
    failed_at: np.ndarray  # int per run: index of the first failed boarding, -1 if none
    alternative_used: np.ndarray  # int per run: index into alternatives[failed_at], -1 if none

    @property
    def p_stranded(self) -> float:
        return float(np.mean(~np.isfinite(self.arrival)))

    @property
    def p_connections(self) -> float:
        return float(np.mean(self.connections_held))

    def p_arrive_by(self, deadline: int) -> float:
        return float(np.mean(self.arrival <= deadline))

    def arrival_quantile(self, q: float) -> float:
        finite = self.arrival[np.isfinite(self.arrival)]
        if finite.size == 0 or np.mean(np.isfinite(self.arrival)) < q:
            return float("inf")
        return float(np.quantile(self.arrival, q))

    def p_fail_at(self, index: int) -> float:
        return float(np.mean(self.failed_at == index))


class JourneySimulator:
    def __init__(self, runs: int = 2000, seed: int | None = None) -> None:
        self.runs = runs
        self.rng = np.random.default_rng(seed)

    def _sample_legs(self, legs: list[SimLeg]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = len(legs)
        # One uniform per leg and run, shared by its departure and arrival delay.
        u = self.rng.random((n, self.runs))
        dep_q = np.array([leg.dep_q for leg in legs])
        arr_q = np.array([leg.arr_q for leg in legs])
        dep_delay = np.maximum(sample_from_quantiles(dep_q, u), 0.0)
        arr_delay = np.maximum(sample_from_quantiles(arr_q, u), -2.0)
        planned_dep = np.array([[leg.planned_dep] for leg in legs], dtype=float)
        planned_arr = np.array([[leg.planned_arr] for leg in legs], dtype=float)
        actual_dep = planned_dep + dep_delay * 60
        # A train cannot arrive before it departed plus its scheduled running time minus slack.
        actual_arr = np.maximum(planned_arr + arr_delay * 60, actual_dep + 0.85 * (planned_arr - planned_dep))
        cancelled = self.rng.random((n, self.runs)) < np.array([[leg.p_cancel] for leg in legs])
        return actual_dep, actual_arr, cancelled

    def _run_chain(self, legs: list[SimLeg], ready: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                                                          np.ndarray]:
        """Simulate legs without rerouting.

        Returns (arrival, ok, failed_at, ready_at_failure) with ``ready`` the time the
        traveller is ready to board the first leg.
        """
        actual_dep, actual_arr, cancelled = self._sample_legs(legs)
        ok = np.ones(self.runs, dtype=bool)
        failed_at = np.full(self.runs, -1)
        ready_at_failure = np.full(self.runs, np.nan)
        current_ready = ready.astype(float)
        for i, leg in enumerate(legs):
            if i > 0:
                current_ready = actual_arr[i - 1] + leg.change_before
            boards = (current_ready <= actual_dep[i]) & ~cancelled[i]
            newly_failed = ok & ~boards
            failed_at[newly_failed] = i
            ready_at_failure[newly_failed] = current_ready[newly_failed]
            ok &= boards
        arrival = np.where(ok, actual_arr[-1], STRANDED)
        return arrival, ok, failed_at, ready_at_failure

    def simulate(self, journey: SimJourney, ready_at_origin: int | None = None) -> SimResult:
        start = journey.legs[0].planned_dep if ready_at_origin is None else ready_at_origin
        arrival, ok, failed_at, ready_at_failure = self._run_chain(
            journey.legs, np.full(self.runs, float(start)))
        alternative_used = np.full(self.runs, -1)
        final = arrival.copy()

        for index, alternatives in journey.alternatives.items():
            pending = (failed_at == index)
            if not pending.any():
                continue
            for alt_idx, alt_legs in enumerate(alternatives):
                if not pending.any():
                    break
                ready = np.where(pending, ready_at_failure, np.inf)
                # The traveller is at the station from ``ready``; they take the alternative if
                # its first train has not left yet.
                alt_arrival, _alt_ok, alt_failed_at, _ = self._run_chain(alt_legs, np.nan_to_num(ready, nan=np.inf))
                # alt_failed_at == 0 means the fallback's first train was also missed or cancelled.
                catchable = pending & (alt_failed_at != 0)
                final[catchable] = alt_arrival[catchable]
                alternative_used[catchable] = alt_idx
                pending &= ~catchable
        return SimResult(
            runs=self.runs,
            arrival=final,
            connections_held=ok,
            failed_at=failed_at,
            alternative_used=alternative_used,
        )
