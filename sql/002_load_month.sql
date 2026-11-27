-- Delay data platform, phase 2: one function that checks a staged month and merges it, or refuses it.
-- Every attempt is recorded in rail.load_log, so a failed monthly load is visible (and later alertable).

CREATE TABLE IF NOT EXISTS rail.load_log (
    id            bigserial PRIMARY KEY,
    month         char(7)     NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL CHECK (status IN ('loaded', 'rejected', 'failed')),
    rows_staged   integer,
    rows_loaded   integer,
    reason        text
);

-- rail.load_month(month, stage, min_ratio)
--   p_month      'YYYY-MM', the month the file is supposed to contain
--   p_stage      staging table holding the file (a parameter so tests can use a scratch table)
--   p_min_ratio  refuse the file if it has fewer rows than this share of the trailing average (default 70%,
--                that is "more than 30% fewer rows than usual")
-- Returns 'loaded: N rows' or 'rejected: <reasons>'. Rejection is a normal result, not an exception, so the
-- log row survives; the runner turns it into a non-zero exit code.
-- Loading the same month again replaces it (delete + insert in one transaction), never duplicates.
CREATE OR REPLACE FUNCTION rail.load_month(
    p_month text,
    p_stage regclass DEFAULT 'rail.stg_delay_month',
    p_min_ratio numeric DEFAULT 0.7
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    lo            timestamp := to_date(p_month || '-01', 'YYYY-MM-DD') - interval '1 day';
    hi            timestamp := to_date(p_month || '-01', 'YYYY-MM-DD') + interval '1 month' + interval '1 day';
    n_total       bigint;
    n_bad_keys    bigint;
    n_dupes       bigint;
    n_off_month   bigint;
    n_extreme     bigint;
    baseline      numeric;
    reasons       text[] := '{}';
    n_loaded      bigint;
    first_day     timestamp;
    log_id        bigint;
BEGIN
    INSERT INTO rail.load_log (month, status) VALUES (p_month, 'failed') RETURNING id INTO log_id;

    -- One pass over the staged file collects every number the checks need. Additional stops are excluded
    -- here exactly as they are excluded from the merge below.
    EXECUTE format($q$
        SELECT count(*),
               count(*) FILTER (WHERE id IS NULL OR eva IS NULL OR train_line_ride_id IS NULL
                                   OR train_line_station_num IS NULL
                                   OR COALESCE(departure_planned_time, arrival_planned_time) IS NULL),
               count(*) - count(DISTINCT id),
               count(*) FILTER (WHERE COALESCE(departure_planned_time, arrival_planned_time) < %L
                                   OR COALESCE(departure_planned_time, arrival_planned_time) >= %L),
               count(*) FILTER (WHERE abs(EXTRACT(EPOCH FROM arrival_change_time - arrival_planned_time)) > 86400
                                   OR abs(EXTRACT(EPOCH FROM departure_change_time - departure_planned_time)) > 86400)
        FROM %s
        WHERE NOT COALESCE(is_additional_stop, false)
    $q$, lo, hi, p_stage) INTO n_total, n_bad_keys, n_dupes, n_off_month, n_extreme;

    -- Trailing average of the last three successfully loaded months (other than this one).
    SELECT avg(rows_staged) INTO baseline FROM (
        SELECT rows_staged FROM rail.load_log
        WHERE status = 'loaded' AND month <> p_month
        ORDER BY finished_at DESC LIMIT 3) recent;

    IF n_total = 0 THEN
        reasons := reasons || 'the file is empty'::text;
    ELSE
        IF baseline IS NOT NULL AND n_total < p_min_ratio * baseline THEN
            reasons := reasons || format('%s rows is more than %s%% below the trailing average of %s',
                                         n_total, round((1 - p_min_ratio) * 100), round(baseline));
        END IF;
        IF n_bad_keys > 0 THEN
            reasons := reasons || format('%s rows miss an id, station, ride or planned time', n_bad_keys);
        END IF;
        IF n_dupes::numeric / n_total > 0.001 THEN
            reasons := reasons || format('%s duplicate ids', n_dupes);
        END IF;
        IF n_off_month::numeric / n_total > 0.01 THEN
            reasons := reasons || format('%s rows fall outside %s (wrong month?)', n_off_month, p_month);
        END IF;
        IF n_extreme::numeric / n_total > 0.001 THEN
            reasons := reasons || format('%s rows have delays beyond 24 hours', n_extreme);
        END IF;
    END IF;

    IF cardinality(reasons) > 0 THEN
        UPDATE rail.load_log SET status = 'rejected', finished_at = now(), rows_staged = n_total,
               reason = array_to_string(reasons, '; ') WHERE id = log_id;
        RETURN 'rejected: ' || array_to_string(reasons, '; ');
    END IF;

    -- Partitions for every month the planned times touch (a ride can start in the previous month).
    FOR first_day IN EXECUTE format(
        'SELECT DISTINCT date_trunc(''month'', COALESCE(departure_planned_time, arrival_planned_time)) FROM %s',
        p_stage)
    LOOP
        PERFORM rail.ensure_partition(first_day);
    END LOOP;

    -- Replace the month: the same file loaded twice gives the same table.
    DELETE FROM rail.fact_stop_event WHERE source_month = p_month;
    EXECUTE format($q$
        INSERT INTO rail.fact_stop_event (
            id, event_ts, source_month, ride_id, station_num, eva, station_name, train_type, train_number,
            line_number, final_destination, arrival_planned, arrival_actual, departure_planned,
            departure_actual, arrival_delay_min, departure_delay_min, arrival_cancelled,
            departure_cancelled, is_replacement)
        SELECT id, COALESCE(departure_planned_time, arrival_planned_time), %L, train_line_ride_id,
               train_line_station_num, eva, station_name, train_type, train_number, line_number,
               final_destination_station, arrival_planned_time, arrival_change_time,
               departure_planned_time, departure_change_time,
               EXTRACT(EPOCH FROM arrival_change_time - arrival_planned_time) / 60,
               EXTRACT(EPOCH FROM departure_change_time - departure_planned_time) / 60,
               COALESCE(arrival_is_canceled, false), COALESCE(departure_is_canceled, false),
               COALESCE(is_replacement_train, false)
        FROM %s
        WHERE NOT COALESCE(is_additional_stop, false)
        ON CONFLICT (id, event_ts) DO NOTHING
    $q$, p_month, p_stage);
    GET DIAGNOSTICS n_loaded = ROW_COUNT;

    UPDATE rail.load_log SET status = 'loaded', finished_at = now(), rows_staged = n_total,
           rows_loaded = n_loaded WHERE id = log_id;
    RETURN format('loaded: %s rows', n_loaded);
END $$;
