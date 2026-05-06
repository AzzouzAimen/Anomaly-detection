-- ==============================================================================
-- PROJECT: Medical Time-Series Dataset Curation (Topic M4: Apnea-ECG)
-- SPRINT 1: Time-Series Optimized Schema (TimescaleDB)
-- ==============================================================================

-- ==============================================================================
-- ENABLE TIMESCALEDB EXTENSION
-- ------------------------------------------------------------------------------
-- Required before creating hypertables.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ==============================================================================
-- 1. SUBJECTS TABLE
-- ------------------------------------------------------------------------------
-- Same logical entity as in PostgreSQL.
-- Kept relational because subject metadata is not high-frequency time-series data.
-- ==============================================================================

CREATE TABLE subjects (
    subject_id VARCHAR(20) PRIMARY KEY,
    notes TEXT
);

-- ==============================================================================
-- 2. RECORDINGS TABLE
-- ------------------------------------------------------------------------------
-- Same logical entity as in PostgreSQL.
-- Stores metadata for each recording.
--
-- Difference:
--   - Uses TIMESTAMPTZ instead of TIMESTAMP for better time-series compatibility.
-- ==============================================================================

CREATE TABLE recordings (
    recording_id VARCHAR(10) PRIMARY KEY,
    subject_id VARCHAR(20) NOT NULL REFERENCES subjects(subject_id),

    split VARCHAR(10) NOT NULL,
    record_category CHAR(1) NOT NULL,

    has_respiration BOOLEAN NOT NULL DEFAULT FALSE,
    has_apnea_labels BOOLEAN NOT NULL DEFAULT FALSE,

    source_record_name VARCHAR(10) NOT NULL,

    sampling_rate_hz INTEGER NOT NULL DEFAULT 100,
    length_seconds INTEGER NOT NULL,

    recording_start_time TIMESTAMPTZ NOT NULL DEFAULT TIMESTAMPTZ '2000-01-01 00:00:00+00',

    CONSTRAINT chk_recordings_split
        CHECK (split IN ('learning', 'test')),

    CONSTRAINT chk_recordings_category
        CHECK (record_category IN ('a', 'b', 'c', 'x')),

    CONSTRAINT chk_recordings_sampling_rate
        CHECK (sampling_rate_hz > 0),

    CONSTRAINT chk_recordings_length
        CHECK (length_seconds > 0)
);

-- ==============================================================================
-- 3. SIGNALS TABLE
-- ------------------------------------------------------------------------------
-- Main high-frequency hypertable.
--
-- Important TimescaleDB rule:
--   Any PRIMARY KEY or UNIQUE constraint on a hypertable must include the
--   time partition column, which is recorded_at.
--
-- Therefore, the primary key is:
--   (recording_id, recorded_at)
--
-- sample_index is still stored for raw-file traceability.
-- ==============================================================================

CREATE TABLE signals (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    recorded_at TIMESTAMPTZ NOT NULL,
    sample_index BIGINT NOT NULL,

    ecg_value DOUBLE PRECISION,

    resp_c DOUBLE PRECISION,
    resp_a DOUBLE PRECISION,
    resp_n DOUBLE PRECISION,
    spo2 DOUBLE PRECISION,

    PRIMARY KEY (recording_id, recorded_at),

    CONSTRAINT chk_signals_sample_index
        CHECK (sample_index >= 0)
);

-- ==============================================================================
-- 4. APNEA ANNOTATIONS TABLE
-- ------------------------------------------------------------------------------
-- Minute-level labels.
-- Converted to a hypertable for consistent time-series querying.
-- ==============================================================================

CREATE TABLE annotations_apnea (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    recorded_at TIMESTAMPTZ NOT NULL,
    minute_index INTEGER NOT NULL,

    label CHAR(1) NOT NULL,
    is_apnea BOOLEAN NOT NULL,

    PRIMARY KEY (recording_id, recorded_at),

    CONSTRAINT chk_apnea_minute_index
        CHECK (minute_index >= 0),

    CONSTRAINT chk_apnea_label
        CHECK (label IN ('A', 'N'))
);

-- ==============================================================================
-- 5. QRS ANNOTATIONS TABLE
-- ------------------------------------------------------------------------------
-- Event-based heartbeat annotations.
-- Converted to a hypertable to support heart-rate aggregation queries.
-- ==============================================================================

CREATE TABLE annotations_qrs (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    recorded_at TIMESTAMPTZ NOT NULL,
    sample_index BIGINT NOT NULL,

    PRIMARY KEY (recording_id, recorded_at),

    CONSTRAINT chk_qrs_sample_index
        CHECK (sample_index >= 0)
);

-- ==============================================================================
-- 6. HYPERTABLE CREATION
-- ------------------------------------------------------------------------------
-- signals:
--   Uses a 1-hour chunk interval because all artificial timestamps start near
--   the same baseline date. A 1-day chunk would place most data into one chunk,
--   making the benchmark less meaningful.
--
-- annotations_apnea and annotations_qrs:
--   Smaller tables, so 1-day chunks are acceptable.
-- ==============================================================================

SELECT create_hypertable(
    'signals',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT create_hypertable(
    'annotations_apnea',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

SELECT create_hypertable(
    'annotations_qrs',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- ==============================================================================
-- 7. INDEXES
-- ------------------------------------------------------------------------------
-- TimescaleDB automatically creates indexes for PRIMARY KEY constraints.
-- These extra indexes support benchmark queries and filtering.
-- ==============================================================================

CREATE INDEX idx_recordings_subject
ON recordings(subject_id);

CREATE INDEX idx_apnea_events
ON annotations_apnea(recording_id, is_apnea, recorded_at DESC);

CREATE INDEX idx_signals_time
ON signals(recorded_at DESC);

CREATE INDEX idx_apnea_time
ON annotations_apnea(recorded_at DESC);

CREATE INDEX idx_qrs_time
ON annotations_qrs(recorded_at DESC);

-- ==============================================================================
-- 8. COMPRESSION CONFIGURATION
-- ------------------------------------------------------------------------------
-- Compression is enabled on the high-frequency signals hypertable.
--
-- segmentby:
--   recording_id
--   because most queries filter by recording_id.
--
-- orderby:
--   recorded_at DESC
--   because time-range queries are the main benchmark workload.
--
-- Note:
--   The compression policy itself should be applied after data loading in Sprint 2.
-- ==============================================================================

ALTER TABLE signals SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'recording_id',
    timescaledb.compress_orderby = 'recorded_at DESC'
);

-- Apply this after ingestion in Sprint 2, not necessarily during Sprint 1:
-- SELECT add_compression_policy('signals', INTERVAL '1 day');