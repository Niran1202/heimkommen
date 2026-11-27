-- Delay data platform, phase 4: find trains that left late because they waited for a late feeder train.
--
-- The data has no explicit "waited for" link, so this is an INFERENCE. A departure D at a station counts as
-- having waited for a feeder A (a different train arriving at the same station) when ALL of this holds:
--   1. D left at least p_min_hold minutes late (it was held, not just a little late).
--   2. A and D formed a planned connection: A was planned to arrive between p_min_transfer and p_max_transfer
--      minutes before D's planned departure.
--   3. A was still not at the station when D should have left (A's actual arrival is after D's planned
--      departure). Otherwise D had no reason to wait.
--   4. D left after A arrived and within p_max_gap minutes of it (D left shortly after A showed up).
--   5. Neither train was cancelled.
-- If several feeders qualify, the one that arrived last is taken: it is the one D most likely waited for.
-- Expect false positives (a coincidence looks the same as a wait). Phase 4 reports how many pairs were
-- checked by hand in docs/. Use it to rank stations and corridors, not to blame single trains.
--
-- Both ends of the join are limited to a time window so the (eva, event_ts) index is used; D is taken from
-- [p_from, p_to), feeders from two hours around it.

CREATE OR REPLACE FUNCTION rail.waits_for_feeder(
    p_from         timestamp,
    p_to           timestamp,
    p_min_hold     double precision DEFAULT 2,
    p_max_gap      double precision DEFAULT 5,
    p_min_transfer double precision DEFAULT 2,
    p_max_transfer double precision DEFAULT 15
) RETURNS TABLE (
    eva                    text,
    station_name           text,
    departure_id           text,
    departure_ride_id      text,
    departure_line         text,
    departure_planned      timestamp,
    held_min               double precision,   -- departure delay of the connecting train
    feeder_id              text,
    feeder_ride_id         text,
    feeder_line            text,
    feeder_arrival_delay   double precision,   -- how late the feeder was
    planned_transfer_min   double precision,
    gap_after_feeder_min   double precision    -- how long after the feeder arrived D left
)
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (d.id, d.event_ts)
           d.eva, d.station_name, d.id, d.ride_id, d.line_number, d.departure_planned,
           d.departure_delay_min,
           a.id, a.ride_id, a.line_number, a.arrival_delay_min,
           EXTRACT(EPOCH FROM d.departure_planned - a.arrival_planned) / 60,
           EXTRACT(EPOCH FROM d.departure_actual - a.arrival_actual) / 60
    FROM rail.fact_stop_event d
    JOIN rail.fact_stop_event a
      ON a.eva = d.eva
     AND a.ride_id <> d.ride_id
     AND a.event_ts >= d.event_ts - interval '2 hours'
     AND a.event_ts <= d.event_ts + interval '2 hours'
    WHERE d.event_ts >= p_from AND d.event_ts < p_to
      AND d.departure_planned IS NOT NULL AND d.departure_actual IS NOT NULL
      AND NOT d.departure_cancelled
      AND d.departure_delay_min >= p_min_hold
      AND a.arrival_planned IS NOT NULL AND a.arrival_actual IS NOT NULL
      AND NOT a.arrival_cancelled
      AND a.arrival_planned <= d.departure_planned - p_min_transfer * interval '1 minute'
      AND a.arrival_planned >= d.departure_planned - p_max_transfer * interval '1 minute'
      AND a.arrival_actual  >  d.departure_planned
      AND a.arrival_actual  <= d.departure_actual
      AND d.departure_actual - a.arrival_actual <= p_max_gap * interval '1 minute'
    ORDER BY d.id, d.event_ts, a.arrival_actual DESC
$$;
