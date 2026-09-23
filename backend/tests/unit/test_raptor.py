from datetime import date

from app.engine.categories import allowed_with_deutschlandticket
from app.engine.raptor import Raptor, parse_hhmm, seconds_to_hhmm
from tests.conftest import FRIDAY


def _stations(store, *names):
    return [store.resolve_station(n) for n in names]


def test_fastest_journey_uses_the_intercity(store) -> None:
    villingen, stuttgart = _stations(store, "Villingen", "Stuttgart Hauptbahnhof")
    journeys = Raptor(store).earliest_arrival(FRIDAY, villingen.stops, stuttgart.stops, parse_hhmm("19:30"))
    best = min(journeys, key=lambda j: j.arrival)
    assert seconds_to_hhmm(best.arrival) == "21:10"
    assert [leg.route for leg in best.legs] == ["IC 2"]


def test_deutschlandticket_filter_excludes_long_distance(store) -> None:
    villingen, stuttgart = _stations(store, "Villingen", "Stuttgart Hauptbahnhof")
    journeys = Raptor(store).earliest_arrival(FRIDAY, villingen.stops, stuttgart.stops, parse_hhmm("19:30"),
                                              category_filter=allowed_with_deutschlandticket)
    journey = journeys[0]
    assert [leg.route for leg in journey.legs] == ["RB 42", "RE 87"]
    assert seconds_to_hhmm(journey.departure) == "19:40"
    assert seconds_to_hhmm(journey.arrival) == "21:32"
    # The transfer is between two platforms of the same station.
    assert store.station_of_stop(journey.legs[0].to_stop).name == "Rottweil Bahnhof"


def test_journey_options_are_successive_and_cross_midnight(store) -> None:
    villingen, stuttgart = _stations(store, "Villingen", "Stuttgart Hauptbahnhof")
    options = Raptor(store).journey_options(FRIDAY, villingen.stops, stuttgart.stops, parse_hhmm("20:00"), count=3,
                                            category_filter=allowed_with_deutschlandticket)
    assert [(seconds_to_hhmm(j.departure), seconds_to_hhmm(j.arrival)) for j in options] == [("20:40", "22:43")]


def test_minimum_transfer_time_is_respected(store) -> None:
    villingen, stuttgart = _stations(store, "Villingen", "Stuttgart Hauptbahnhof")
    router = Raptor(store)
    rottweil_arrival_platform = store.stop_index["de:08325:2:1:1"]
    rottweil_departure_platform = store.stop_index["de:08325:2:1:2"]
    footpaths = store.footpaths[rottweil_arrival_platform]
    original = list(footpaths)
    try:
        # 7 minutes to change platforms: 21:11 + 7 > 21:17, so the 21:17 RE is missed.
        store.footpaths[rottweil_arrival_platform] = [(rottweil_departure_platform, 7 * 60)]
        router._cache.clear()
        journeys = router.earliest_arrival(FRIDAY, villingen.stops, stuttgart.stops, parse_hhmm("20:30"),
                                           category_filter=allowed_with_deutschlandticket)
        assert seconds_to_hhmm(journeys[0].arrival) == "00:45"
        assert journeys[0].arrival == 24 * 3600 + 45 * 60
    finally:
        store.footpaths[rottweil_arrival_platform] = original
        router._cache.clear()


def test_no_service_on_exception_dates_and_weekends(store) -> None:
    villingen, stuttgart = _stations(store, "Villingen", "Stuttgart Hauptbahnhof")
    router = Raptor(store)
    assert router.earliest_arrival(date(2026, 9, 28), villingen.stops, stuttgart.stops, 0) == []  # removed Monday
    assert router.earliest_arrival(date(2026, 9, 26), villingen.stops, stuttgart.stops, 0) == []  # Saturday


def test_bus_leg_reaches_village(store) -> None:
    villingen, dorf = _stations(store, "Villingen", "Dorf Rathaus")
    journeys = Raptor(store).earliest_arrival(FRIDAY, villingen.stops, dorf.stops, parse_hhmm("19:00"))
    assert [leg.category for leg in journeys[0].legs] == ["RB", "BUS"]
    assert seconds_to_hhmm(journeys[0].arrival) == "20:40"


def test_station_search_expands_abbreviations(store) -> None:
    assert store.search_stations("Stuttgart Hbf")[0].name == "Stuttgart Hauptbahnhof"
    assert store.resolve_station("de:08325:2_Parent").name == "Rottweil Bahnhof"
    assert store.resolve_station("Nowhere") is None
