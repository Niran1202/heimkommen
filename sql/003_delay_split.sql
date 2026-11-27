-- Delay data platform, phase 3: split every stop's delay into "brought" and "created".
--
-- For a stop on a ride (stops ordered along the ride):
--   brought_in_min       delay the train already had when it left the previous stop
--   created_en_route_min delay added (or recovered, if negative) between the previous stop and this one
--                        = arrival delay - brought_in
--   created_at_stop_min  delay added (or recovered) while standing here
--                        = departure delay - arrival delay
-- so  brought_in + created_en_route + created_at_stop = departure delay   (arrival delay at the last stop).
--
-- Rules that come from the data (checked on October 2026):
--  * Numbering starts at 1. A ride whose first row is not number 1 only enters the filtered region part-way,
--    so what it brought in is UNKNOWN (NULL), not zero. About 43% of rides are like this.
--  * The origin (number 1) has no arrival: it brings in nothing, everything it adds happens at the stop.
--  * The last stop has no departure: created_at_stop_min is NULL, delay_after_stop_min is the arrival delay.
--  * Numbers have gaps when stops are filtered out; the previous available row is used and gap_before says so.
--  * Missing times make the affected parts NULL; nothing is guessed.
-- The window is partitioned by ride, so a filter on ride_id is pushed down. A filter on time is not (a ride can
-- cross a partition), so for whole months use rail.delay_split_month() in phase 6 / a materialised table.

CREATE OR REPLACE VIEW rail.v_delay_split AS
WITH ordered AS (
    SELECT f.*,
           row_number() OVER w                      AS stop_seq,
           lag(f.station_num) OVER w                AS prev_station_num,
           lag(f.departure_delay_min) OVER w        AS prev_departure_delay_min
    FROM rail.fact_stop_event f
    WINDOW w AS (PARTITION BY f.ride_id ORDER BY f.station_num, f.event_ts, f.id)
), brought AS (
    SELECT o.*,
           CASE WHEN o.station_num = 1 THEN 0::double precision
                ELSE o.prev_departure_delay_min END AS brought_in
    FROM ordered o
)
SELECT b.id, b.event_ts, b.source_month, b.ride_id, b.station_num, b.stop_seq,
       b.eva, b.station_name, b.train_type, b.line_number,
       b.arrival_delay_min, b.departure_delay_min,
       b.brought_in                                                           AS brought_in_min,
       CASE WHEN b.arrival_delay_min IS NOT NULL AND b.brought_in IS NOT NULL
            THEN b.arrival_delay_min - b.brought_in END                       AS created_en_route_min,
       CASE WHEN b.departure_delay_min IS NULL THEN NULL
            WHEN b.arrival_delay_min IS NOT NULL THEN b.departure_delay_min - b.arrival_delay_min
            WHEN b.station_num = 1 THEN b.departure_delay_min                 -- origin: no arrival to compare
       END                                                                    AS created_at_stop_min,
       COALESCE(b.departure_delay_min, b.arrival_delay_min)                   AS delay_after_stop_min,
       (b.prev_station_num IS NOT NULL AND b.station_num - b.prev_station_num > 1) AS gap_before
FROM brought b;
