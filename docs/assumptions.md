# Assumptions and limitations

## Scope
- **Region**: rail in all of Baden-Württemberg (so long regional trips route), buses/trams only in the counties
  Schwarzwald-Baar-Kreis (08326), Rottweil (08325) and Tuttlingen (08327). Bus trips from Stuttgart or Freiburg city
  centres to the station are not included.
- **Timetable**: the NVBW feed imported (currently valid 2026-05-03 to 2026-12-12). Requests outside that range are
  rejected with a clear message.
- Trips of the previous service day that run past midnight are included, so a search at 00:30 works. A journey is
  "stranded" if nothing reaches the destination before the end of the service day (~03:00 next morning).

## Delays
- **Buses and trams run on time.** Only trains (RE/RB/S/IC/ICE, category from the route name) get delays and
  cancellations. Rail replacement buses (SEV) are treated like buses.
- Leg delays are **independent** of each other; within one leg the departure and arrival delays use the same random
  number (a late train stays late). The replay shows this makes tight connections look too safe
  (see [evaluation.md](evaluation.md)).
- A train never departs early (departure delay ≥ 0); it can arrive up to 2 minutes early and at most 15 % faster
  than scheduled.
- At planning time the delay at the previous stop is unknown; the model was trained with that feature masked for
  half the rows so it handles both cases. Live data is not yet fed into the simulator.
- Cancellation probability is a historical rate per line × station, not a model.
- Trains with little history fall back to line-, then product-level behaviour (LightGBM handles unseen stations and
  lines as missing categories).

## Transfers
- Minimum change time: `transfers.txt` where given, otherwise 4 minutes, both for staying on the platform and for
  walking between platforms of the same station. Walking between different stations is not supported.
- When a connection is missed the traveller takes the first catchable of the next two continuations from that
  station. If a fallback itself has a failing connection, the run counts as stranded (pessimistic; no second
  rerouting).

## Matching
- GTFS stations are matched to DB EVA numbers by timetable co-occurrence (same train number at the same minute), with
  a name-based fallback. 1,016 of ~1,800 rail stations in the feed are matched; the rest are mostly outside
  Germany or served only by operators not in the DB data. Unmatched stations still route but use line-level delays.

## Data
- The piebro dataset has gaps (e.g. 102 missing hours in July 2026); missing hours reduce data, they are not treated
  as "no delay".
- All timestamps are local time (Europe/Berlin), as in both sources.
- This is decision support, **not** an official DB or NVBW service.
