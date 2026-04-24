-- AgroSmart Digital Twin - TimescaleDB schema
-- Hypertables for high-resolution telemetry with automatic partitioning.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS telemetry (
    time                  TIMESTAMPTZ       NOT NULL,
    node_id               TEXT              NOT NULL,
    crop                  TEXT              NOT NULL,
    soil_moisture_pct     DOUBLE PRECISION  NOT NULL,
    soil_temp_c           DOUBLE PRECISION  NOT NULL,
    ambient_temp_c        DOUBLE PRECISION  NOT NULL,
    ambient_humidity_pct  DOUBLE PRECISION  NOT NULL,
    battery_v             DOUBLE PRECISION  NOT NULL
);

SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_telemetry_node_time
    ON telemetry (node_id, time DESC);


CREATE TABLE IF NOT EXISTS irrigation_events (
    time               TIMESTAMPTZ       NOT NULL,
    node_id            TEXT              NOT NULL,
    action             TEXT              NOT NULL,
    duration_s         INTEGER,
    volume_l           DOUBLE PRECISION,
    reason             TEXT,
    moisture_before    DOUBLE PRECISION,
    moisture_target    DOUBLE PRECISION
);

SELECT create_hypertable('irrigation_events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_irrigation_node_time
    ON irrigation_events (node_id, time DESC);


CREATE TABLE IF NOT EXISTS coordinator_decisions (
    time             TIMESTAMPTZ       NOT NULL,
    node_id          TEXT              NOT NULL,
    decision         TEXT              NOT NULL,
    rationale        TEXT,
    weather_forecast JSONB
);

SELECT create_hypertable('coordinator_decisions', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_decisions_node_time
    ON coordinator_decisions (node_id, time DESC);


-- Read-only role for Grafana.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        CREATE ROLE grafana_reader LOGIN PASSWORD 'grafana_reader';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE agrosmart TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO grafana_reader;
