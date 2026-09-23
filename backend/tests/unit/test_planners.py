from app.engine.delay_model import DelayModel, LegQuery
from app.engine.features import product_of
from app.engine.planners import remove_dominated
from app.engine.raptor import Journey, parse_hhmm, seconds_to_hhmm
from tests.conftest import FRIDAY


def test_home_check_reports_risk_plan_b_and_latest_safe(store, planner) -> None:
    villingen, stuttgart = store.resolve_station("Villingen"), store.resolve_station("Stuttgart Hauptbahnhof")
    result = planner.home_check(FRIDAY, villingen, stuttgart, parse_hhmm("19:00"), regional_only=True, count=3,
                                confidence=0.95)
    options = result["options"]
    assert [seconds_to_hhmm(ev.journey.departure) for ev in options] == ["19:40", "20:40"]
    first = options[0]
    # The 6-minute change at Rottweil is the weak point, and the 21:17 RE is Plan B.
    assert first.weak_point() == 1
    plan_b = first.plan_b(1)
    assert plan_b is not None and seconds_to_hhmm(plan_b.departure) == "21:17"
    assert first.p_home > first.result.p_connections
    # The last connection of the night has only the 23:30 train as fallback.
    assert result["last"] is not None
    assert seconds_to_hhmm(result["last"].journey.departure) == "20:40"


def test_deadline_planner_walks_back_from_the_deadline(store, planner) -> None:
    villingen, stuttgart = store.resolve_station("Villingen"), store.resolve_station("Stuttgart Hauptbahnhof")
    result = planner.deadline(FRIDAY, villingen, stuttgart, parse_hhmm("23:00"), regional_only=True,
                              confidence=0.5)
    ev, probability = result["chosen"]
    assert seconds_to_hhmm(ev.journey.departure) == "20:40"
    assert probability >= 0.5


def test_remove_dominated_drops_earlier_departure_with_same_arrival() -> None:
    class FakeJourney(Journey):
        def __init__(self, departure: int, arrival: int) -> None:
            super().__init__(legs=[], service_date=FRIDAY)
            self._times = (departure, arrival)

        departure = property(lambda self: self._times[0])
        arrival = property(lambda self: self._times[1])
        transfers = property(lambda self: 0)

    a, b, c = FakeJourney(100, 500), FakeJourney(200, 500), FakeJourney(300, 700)
    assert remove_dominated([a, b, c]) == [b, c]


def test_prior_model_predicts_trains_but_not_buses() -> None:
    model = DelayModel.prior()
    train = LegQuery("RE", "RE 87", "50182", "08000322", "08000096", 20, 21, 4, 0, 5, 10)
    bus = LegQuery("BUS", "550", None, None, None, 20, 20, 4, 0, 1, 2)
    predictions = model.predict([train, bus])
    assert predictions[0].modelled and predictions[0].p_cancel > 0
    assert not predictions[1].modelled and predictions[1].p_cancel == 0


def test_product_mapping() -> None:
    assert product_of("RE2", "RE") == "RE"
    assert product_of("RB42", "SWE") == "RB"
    assert product_of(None, "ICE") == "FV"
    assert product_of("S6", "SBB") == "S"
