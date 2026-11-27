-- Delay data platform, phase 1: schema, staging table, partitioned fact table.
-- Hand-written SQL, no ORM. Safe to run repeatedly (every statement is idempotent).

CREATE SCHEMA IF NOT EXISTS rail;

-- Staging: a raw copy of one monthly parquet file, exactly as published (after the regional filter).
-- UNLOGGED = no WAL, fast to load, thrown away after every month, so crash safety does not matter.
CREATE UNLOGGED TABLE IF NOT EXISTS rail.stg_delay_month (
    id                          text,
    eva                         text,
    station_name                text,
    train_type                  text,
    train_number                text,
    line_number                 text,
    final_destination_station   text,
    train_line_ride_id          text,
    train_line_station_num      integer,
    arrival_planned_time        timestamp,
    arrival_change_time         timestamp,
    departure_planned_time      timestamp,
    departure_change_time       timestamp,
    arrival_is_canceled         boolean,
    departure_is_canceled       boolean,
    is_additional_stop          boolean,
    is_replacement_train        boolean
);

-- Fact table: one row per train, station and day, partitioned by month of the planned event time.
-- event_ts = planned departure, or planned arrival for the last stop of a ride (it has no departure).
-- The partition key has to be part of the primary key in Postgres, hence (id, event_ts).
CREATE TABLE IF NOT EXISTS rail.fact_stop_event (
    id                  text        NOT NULL,
    event_ts            timestamp   NOT NULL,
    source_month        char(7)     NOT NULL,           -- month of the file the row came from, e.g. 2026-10
    ride_id             text        NOT NULL,
    station_num         integer     NOT NULL,           -- position of the stop within the ride
    eva                 text        NOT NULL,
    station_name        text        NOT NULL,
    train_type          text,
    train_number        text,
    line_number         text,
    final_destination   text,
    arrival_planned     timestamp,
    arrival_actual      timestamp,
    departure_planned   timestamp,
    departure_actual    timestamp,
    arrival_delay_min   double precision,               -- NULL when there is no arrival or no actual time
    departure_delay_min double precision,
    arrival_cancelled   boolean     NOT NULL DEFAULT false,
    departure_cancelled boolean     NOT NULL DEFAULT false,
    is_replacement      boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (id, event_ts)
) PARTITION BY RANGE (event_ts);

-- Walk along one ride (window functions in phase 3) and find everything at one station and time (phases 4, 5).
CREATE INDEX IF NOT EXISTS ix_fact_ride_stop ON rail.fact_stop_event (ride_id, station_num);
CREATE INDEX IF NOT EXISTS ix_fact_eva_time  ON rail.fact_stop_event (eva, event_ts);

-- Create the monthly partition that contains a given timestamp, if it does not exist yet.
CREATE OR REPLACE FUNCTION rail.ensure_partition(ts timestamp) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    first_day date := date_trunc('month', ts)::date;
    name text := format('fact_stop_event_%s', to_char(first_day, 'YYYY_MM'));
BEGIN
    IF to_regclass(format('rail.%I', name)) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE rail.%I PARTITION OF rail.fact_stop_event FOR VALUES FROM (%L) TO (%L)',
            name, first_day, (first_day + interval '1 month')::date);
    END IF;
END $$;
