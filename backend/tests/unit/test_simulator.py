import numpy as np
import pytest

from app.engine.features import QUANTILES, sample_from_quantiles
from app.engine.simulator import JourneySimulator, SimJourney, SimLeg

ZERO = np.zeros(len(QUANTILES))


def leg(dep: str, arr: str, q=ZERO, p_cancel: float = 0.0, change: int = 0) -> SimLeg:
    def secs(value: str) -> int:
        return int(value[:2]) * 3600 + int(value[3:]) * 60

    return SimLeg(planned_dep=secs(dep), planned_arr=secs(arr), dep_q=np.asarray(q, float),
                  arr_q=np.asarray(q, float), p_cancel=p_cancel, change_before=change)


def constant(minutes: float) -> np.ndarray:
    return np.full(len(QUANTILES), minutes)


def test_no_delays_means_every_connection_works() -> None:
    journey = SimJourney([leg("19:40", "20:11"), leg("20:17", "21:32", change=240)])
    result = JourneySimulator(runs=500, seed=1).simulate(journey)
    assert result.p_connections == 1.0
    assert result.p_stranded == 0.0
    assert result.p_arrive_by(21 * 3600 + 32 * 60) == 1.0


def test_late_feeder_without_alternative_strands_the_traveller() -> None:
    journey = SimJourney([leg("19:40", "20:11", q=constant(10)), leg("20:17", "21:32", change=240)])
    result = JourneySimulator(runs=500, seed=1).simulate(journey)
    assert result.p_connections == 0.0
    assert result.p_stranded == 1.0
    assert result.p_fail_at(1) == 1.0


def test_missed_connection_falls_back_to_plan_b() -> None:
    journey = SimJourney(
        legs=[leg("19:40", "20:11", q=constant(10)), leg("20:17", "21:32", change=240)],
        alternatives={1: [[leg("21:17", "22:43")]]},
    )
    result = JourneySimulator(runs=500, seed=1).simulate(journey)
    assert result.p_connections == 0.0
    assert result.p_stranded == 0.0
    assert result.arrival_quantile(0.5) == 22 * 3600 + 43 * 60
    assert set(result.alternative_used[result.failed_at == 1]) == {0}


def test_cancellations_are_sampled_and_seed_is_reproducible() -> None:
    journey = SimJourney([leg("19:40", "20:11", p_cancel=0.3)])
    first = JourneySimulator(runs=4000, seed=42).simulate(journey)
    second = JourneySimulator(runs=4000, seed=42).simulate(journey)
    assert first.p_stranded == second.p_stranded
    assert first.p_stranded == pytest.approx(0.3, abs=0.03)


def test_partial_risk_matches_delay_distribution() -> None:
    # Delay quantiles: median 1 min, 90th percentile 10 min. With a 6 min buffer and 4 min
    # change time the connection breaks when the delay exceeds 2 min.
    q = np.array([0, 0, 0, 1, 3, 10, 16, 26], dtype=float)
    journey = SimJourney([leg("19:40", "20:11", q=q), leg("20:17", "21:32", change=240)])
    result = JourneySimulator(runs=20000, seed=3).simulate(journey)
    assert 0.5 < result.p_connections < 0.8


def test_simulator_is_fast_enough() -> None:
    import time

    journey = SimJourney(
        legs=[leg("19:40", "20:11", q=constant(3)), leg("20:17", "21:32", q=constant(3), change=240),
              leg("21:40", "22:10", q=constant(3), change=240)],
        alternatives={1: [[leg("21:17", "22:43")]], 2: [[leg("22:40", "23:10")]]},
    )
    started = time.perf_counter()
    JourneySimulator(runs=5000, seed=1).simulate(journey)
    assert time.perf_counter() - started < 1.0


def test_quantile_sampling_is_monotone_and_hits_the_median() -> None:
    q = np.array([[0, 0, 0, 1, 3, 10, 16, 26]], dtype=float)
    u = np.linspace(0.001, 0.999, 999)[None, :]
    samples = sample_from_quantiles(q, u)[0]
    assert np.all(np.diff(samples) >= 0)
    assert samples[499] == pytest.approx(1.0, abs=0.1)
