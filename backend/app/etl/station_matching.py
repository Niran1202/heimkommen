"""Match GTFS stations (parent stop ids) to DB EVA numbers.

Station names differ a lot between the two sources ("Villingen Bahnhof/ZOB" vs.
"Villingen (Schwarzw)", "Freiburg Hauptbahnhof" vs. "Freiburg (Breisgau) Hbf"), so
the primary method is *timetable co-occurrence*: if GTFS train 69755 departs station X
at 19:40 on a day and the DB data has train 69755 departing EVA Y at 19:40 that same
day, that is a vote for X <-> Y. Normalized-name matching is only a fallback.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

_DROP_WORDS = {"bahnhof", "bf", "bhf", "gleis", "zob", "hauptbahnhof", "hbf", "pbf"}


@dataclass(frozen=True)
class StationMatch:
    station_id: str
    eva: str
    gtfs_name: str
    db_name: str
    method: str  # "timetable" or "name"
    score: float


class StationMatcher:
    """Match GTFS stop names to EVA station numbers."""

    @staticmethod
    def normalize(value: str) -> str:
        value = value.lower()
        for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            value = value.replace(src, dst)
        value = value.replace("-", " ")
        value = re.sub(r"[^a-z0-9\s]", "", value)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def core_name(cls, value: str) -> str:
        """Normalized name without station words or bracketed qualifiers."""
        is_main = bool(re.search(r"\b(hbf|hauptbahnhof)\b", value, re.IGNORECASE))
        value = re.sub(r"\(.*?\)", " ", value)
        words = [w for w in cls.normalize(value.replace("/", " ")).split() if w not in _DROP_WORDS]
        core = " ".join(words)
        return f"{core} hbf" if is_main else core

    @classmethod
    def match_stations(cls, gtfs_stops: list[dict], station_rows: list[dict]) -> dict[str, str]:
        """Name-based matching: exact normalized name first, then the core name."""
        exact: dict[str, str] = {}
        core: dict[str, set[str]] = defaultdict(set)
        for row in station_rows:
            eva = str(row.get("eva") or row.get("eva_number") or row.get("station_eva") or "").strip()
            label = row.get("name") or row.get("station_name") or row.get("stop_name") or ""
            if eva and label:
                exact[cls.normalize(label)] = eva
                core[cls.core_name(label)].add(eva)

        matches: dict[str, str] = {}
        for stop in gtfs_stops:
            stop_name = stop.get("stop_name") or stop.get("station_name") or ""
            stop_id = str(stop.get("stop_id") or stop.get("station_id"))
            key = cls.normalize(stop_name)
            if key in exact:
                matches[stop_id] = exact[key]
                continue
            candidates = core.get(cls.core_name(stop_name), set())
            if len(candidates) == 1:
                matches[stop_id] = next(iter(candidates))
        return matches

    @classmethod
    def match_by_timetable(
        cls,
        gtfs_events: Iterable[tuple[str, str, str]],
        db_events: Iterable[tuple[str, str, str]],
        min_trains: int = 2,
        min_share: float = 0.6,
        names: tuple[dict[str, str], dict[str, str]] | None = None,
        min_trains_without_name_overlap: int = 5,
    ) -> dict[str, tuple[str, int, float]]:
        """Vote on station pairs from shared (train_number, day+minute) events.

        ``gtfs_events``: (train_number, "YYYY-MM-DD HH:MM", station_id)
        ``db_events``:   (train_number, "YYYY-MM-DD HH:MM", eva)

        Votes are counted per *distinct train*: a train number that happens to collide with
        another operator's train (e.g. a Karlsruhe tram-train and a Berlin S-Bahn) repeats
        its coincidence every day, so counting events would let one collision win.
        ``names`` = (station_id -> GTFS name, eva -> DB name); pairs whose names share no word
        need stronger evidence. Returns ``station_id -> (eva, trains, share)``.
        """
        db_index: dict[tuple[str, str], set[str]] = defaultdict(set)
        for train, when, eva in db_events:
            db_index[(train, when)].add(eva)
        trains: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for train, when, station in gtfs_events:
            for eva in db_index.get((train, when), ()):
                trains[station][eva].add(train)
        result: dict[str, tuple[str, int, float]] = {}
        for station, by_eva in trains.items():
            eva, supporting = max(by_eva.items(), key=lambda item: len(item[1]))
            count = len(supporting)
            share = count / sum(len(t) for t in by_eva.values())
            if count < min_trains or share < min_share:
                continue
            if names is not None and count < min_trains_without_name_overlap:
                gtfs_words = set(cls.core_name(names[0].get(station, "")).split())
                db_words = set(cls.core_name(names[1].get(eva, "")).split())
                if not gtfs_words & db_words:
                    continue
            result[station] = (eva, count, share)
        return result
