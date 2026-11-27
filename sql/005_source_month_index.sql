-- Replacing a month (rail.load_month) and cleaning up deletes by source_month; without this index every such
-- delete scans all loaded months.
CREATE INDEX IF NOT EXISTS ix_fact_source_month ON rail.fact_stop_event (source_month);
