# 0001 · Own RAPTOR router instead of an external routing engine

**Status:** accepted

## Context
The simulator needs *many* routing calls per request: the journey options, the last connections of the night,
and alternatives from every transfer station. It also needs details external engines hide: per-leg trip ids and
train numbers (to join with delay data), stop positions, and change times. OpenTripPlanner or MOTIS would
need a JVM or a separate service with several GB of RAM, too big for a free-tier VM, and are harder to query at
this granularity.

## Decision
Implement RAPTOR (Delling et al., 2012) in Python over an in-memory timetable of the regional subset, with
patterns built once and filtered per service day. Keep it simple: successive earliest-arrival queries instead of
rRAPTOR profile queries; `array.array` columns and `bisect` in the hot loop.

## Consequences
- 0.1–0.15 s per query on 66k trips, fast enough; a home check makes 10–30 queries (1–4 s).
- Full control: Deutschlandticket filter, pickup/drop-off rules, trips past midnight, change times.
- No walking between separate stations and no street routing. Acceptable for "which train home".
- If latency matters later: rRAPTOR (one scan for all departures in a window) or a compiled hot loop.
