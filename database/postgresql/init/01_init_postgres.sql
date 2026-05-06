-- ==============================================================================
-- PROJECT: Medical Time-Series Dataset Curation (Topic M4: Apnea-ECG)
-- SPRINT 1: Standard Relational Database Schema (PostgreSQL)
-- ==============================================================================

-- ==============================================================================
-- 1. SUBJECTS TABLE
-- ------------------------------------------------------------------------------
-- Represents the individual patient/subject.
--
-- Note:
-- Most Apnea-ECG records are treated as one subject per recording.
-- However, PhysioNet notes that c05 and c06 come from the same original recording.
-- This table allows both recordings to point to the same subject_id if needed.
-- ==============================================================================

CREATE TABLE subjects (
    subject_id VARCHAR(20) PRIMARY KEY,
    notes TEXT
);

-- ==============================================================================
-- 2. RECORDINGS TABLE
-- ------------------------------------------------------------------------------
-- Represents one recording session.
--
-- split:
--   - 'learning' for a, b, c records
--   - 'test' for x records
--
-- record_category:
--   - 'a', 'b', 'c', or 'x'
--
-- has_respiration:
--   - TRUE only for the 8 records with extra respiratory/SpO2 signals
--
-- has_apnea_labels:
--   - TRUE for learning records
--   - FALSE for test records because .apn labels are unavailable
--
-- recording_start_time:
--   - Artificial timestamp used because the dataset only provides elapsed samples.
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

    recording_start_time TIMESTAMP NOT NULL DEFAULT TIMESTAMP '2000-01-01 00:00:00',

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
-- Contains the high-frequency physiological signal values.
--
-- ECG is available for all 70 records.
-- Respiration and SpO2 columns are NULL for ECG-only records.
--
-- sample_index:
--   - Original sample position in the recording.
--   - Important for traceability to the WFDB raw files.
--
-- recorded_at:
--   - Artificial timestamp calculated from:
--       recording_start_time + sample_index / sampling_rate_hz
--
-- Primary key:
--   - (recording_id, sample_index)
--   - This reflects the raw signal structure.
--
-- Unique time constraint:
--   - (recording_id, recorded_at)
--   - Supports time-range queries and prevents duplicated timestamps.
-- ==============================================================================

CREATE TABLE signals (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    sample_index BIGINT NOT NULL,
    recorded_at TIMESTAMP NOT NULL,

    ecg_value DOUBLE PRECISION,

    resp_c DOUBLE PRECISION,   -- Chest respiratory effort
    resp_a DOUBLE PRECISION,   -- Abdominal respiratory effort
    resp_n DOUBLE PRECISION,   -- Oronasal airflow
    spo2 DOUBLE PRECISION,     -- Oxygen saturation

    PRIMARY KEY (recording_id, sample_index),

    CONSTRAINT uq_signals_recording_time
        UNIQUE (recording_id, recorded_at),

    CONSTRAINT chk_signals_sample_index
        CHECK (sample_index >= 0)
);

-- ==============================================================================
-- 4. APNEA ANNOTATIONS TABLE
-- ------------------------------------------------------------------------------
-- Contains human expert apnea labels.
--
-- Frequency:
--   - One label per minute, not 1 Hz.
--
-- label:
--   - Original annotation label from the .apn file.
--   - Usually 'A' for apnea and 'N' for normal.
--
-- is_apnea:
--   - Boolean version useful for ML queries.
--
-- minute_index:
--   - Minute number inside the recording.
-- ==============================================================================

CREATE TABLE annotations_apnea (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    minute_index INTEGER NOT NULL,
    recorded_at TIMESTAMP NOT NULL,

    label CHAR(1) NOT NULL,
    is_apnea BOOLEAN NOT NULL,

    PRIMARY KEY (recording_id, minute_index),

    CONSTRAINT uq_apnea_recording_time
        UNIQUE (recording_id, recorded_at),

    CONSTRAINT chk_apnea_minute_index
        CHECK (minute_index >= 0),

    CONSTRAINT chk_apnea_label
        CHECK (label IN ('A', 'N'))
);

-- ==============================================================================
-- 5. QRS ANNOTATIONS TABLE
-- ------------------------------------------------------------------------------
-- Contains machine-generated heartbeat/QRS locations.
--
-- Note:
-- These annotations are machine-generated and may contain errors.
-- They are still useful for benchmarking and heart-rate feature extraction.
-- ==============================================================================

CREATE TABLE annotations_qrs (
    recording_id VARCHAR(10) NOT NULL REFERENCES recordings(recording_id),

    sample_index BIGINT NOT NULL,
    recorded_at TIMESTAMP NOT NULL,

    PRIMARY KEY (recording_id, sample_index),

    CONSTRAINT uq_qrs_recording_time
        UNIQUE (recording_id, recorded_at),

    CONSTRAINT chk_qrs_sample_index
        CHECK (sample_index >= 0)
);

-- ==============================================================================
-- INDEXES
-- ------------------------------------------------------------------------------
-- PostgreSQL automatically creates B-Tree indexes for PRIMARY KEY and UNIQUE
-- constraints above.
--
-- These additional indexes support common Sprint 2 benchmark queries.
-- ==============================================================================

-- Quickly list all recordings for a subject.
CREATE INDEX idx_recordings_subject
ON recordings(subject_id);

-- Quickly filter apnea events only.
CREATE INDEX idx_apnea_events
ON annotations_apnea(recording_id, is_apnea, recorded_at);

-- Useful for global time scans or debugging.
CREATE INDEX idx_signals_time
ON signals(recorded_at);

CREATE INDEX idx_apnea_time
ON annotations_apnea(recorded_at);

CREATE INDEX idx_qrs_time
ON annotations_qrs(recorded_at);