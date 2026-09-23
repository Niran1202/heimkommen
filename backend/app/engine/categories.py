"""Classify GTFS routes into the categories the planner cares about."""

from __future__ import annotations

import re

LONG_DISTANCE_PREFIXES = {"ICE", "IC", "EC", "ECE", "EN", "NJ", "FLX", "TGV", "RJ", "RJX", "D", "IR", "EST"}
RAIL_CATEGORIES = {"FV", "RE", "RB", "S", "RAIL"}
# Categories covered by the Deutschlandticket (everything except long-distance trains).
DEUTSCHLANDTICKET_EXCLUDED = {"FV"}
# Categories whose delays we model; buses/trams are treated as on time (see docs/assumptions.md).
MODELLED_CATEGORIES = RAIL_CATEGORIES


def _prefix(short_name: str) -> str:
    match = re.match(r"[A-Za-zÄÖÜäöü]+", short_name.strip())
    return match.group(0).upper() if match else ""


def classify_route(route_type: int, short_name: str) -> str:
    prefix = _prefix(short_name or "")
    if prefix == "SEV":
        return "SEV"
    if route_type == 3 or 700 <= route_type < 800:
        return "BUS"
    if route_type == 2 or 100 <= route_type < 200:
        if prefix in LONG_DISTANCE_PREFIXES:
            return "FV"
        if prefix == "SEV":
            return "SEV"
        if prefix in {"RE", "IRE", "MEX", "RS", "SVG"}:
            return "RE"
        if prefix in {"RB", "R", "SWB", "HZL", "BSB", "RSB"}:
            return "RB"
        if prefix == "S":
            return "S"
        return "RAIL"
    if route_type in (0, 1, 900, 901, 902):
        # Karlsruhe/Heilbronn tram-trains are published as trams but run as S-Bahn.
        return "S" if prefix == "S" else "TRAM"
    return "OTHER"


def is_rail(category: str) -> bool:
    return category in RAIL_CATEGORIES


def allowed_with_deutschlandticket(category: str) -> bool:
    return category not in DEUTSCHLANDTICKET_EXCLUDED
