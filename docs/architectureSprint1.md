# Architecture Sprint 1 — Dual-Database Design

**Project:** Medical Time-Series Dataset Curation
**Topic:** M4 — Respiratory Apnea Detection
**Dataset:** PhysioNet Apnea-ECG Database
**Sprint:** Sprint 1 — Data Ingestion & Architectural Modeling
**Databases:** PostgreSQL and TimescaleDB

---

## 1. Purpose of the Architecture

The goal of Sprint 1 is to design a database architecture capable of storing and later benchmarking a medical time-series dataset for respiratory apnea detection.

The project uses the **PhysioNet Apnea-ECG Database**, which contains 70 long ECG recordings sampled at **100 Hz**. Each recording contains high-frequency ECG samples, minute-level apnea annotations, and machine-generated QRS heartbeat annotations. Only 8 records also contain respiration and oxygen saturation signals.

Because the project requires comparing a traditional relational database with a time-series optimized database, the architecture uses:

1. **PostgreSQL** as the standard relational baseline.
2. **TimescaleDB** as the secondary time-series database.

Both systems store the same logical data so that Sprint 2 benchmarks can fairly compare ingestion speed, query latency, aggregation performance, and storage efficiency.

---

## 2. Why TimescaleDB Was Chosen

TimescaleDB was selected as the secondary time-series database because it extends PostgreSQL with features designed specifically for large time-indexed datasets.

This is suitable for the Apnea-ECG dataset because each recording contains hundreds of thousands to millions of signal samples. Across all 70 records, the signal table is expected to contain roughly **120–200 million rows**, depending on the exact duration of each recording.

TimescaleDB is appropriate for this project for four main reasons.

### 2.1 PostgreSQL Compatibility

TimescaleDB is built on PostgreSQL. This allows the project to keep a familiar relational schema while adding time-series optimizations.

This is important because the comparison remains fair:

* PostgreSQL and TimescaleDB use similar tables.
* The same transformed data is inserted into both systems.
* SQL queries remain mostly identical.
* Differences in performance are mainly due to storage architecture, not different data models.

### 2.2 Hypertables and Time-Based Chunking

TimescaleDB stores large time-series tables as **hypertables**. A hypertable is logically one table, but internally it is split into smaller time-based chunks.

This is useful for the `signals` table because most benchmark queries will request a specific time interval, such as one hour of ECG for one recording.

Instead of scanning one very large table, TimescaleDB can skip irrelevant chunks and scan only the chunks that match the requested time range.

### 2.3 Time-Series Aggregation Functions

Medical signal preprocessing often requires downsampling. For example, the system may need to calculate one-minute ECG statistics or heartbeats per minute.

TimescaleDB provides time-series functions such as `time_bucket()`, which simplify time-window aggregation.

Example Sprint 2 use cases:

* Average ECG value per minute.
* Minimum and maximum ECG value per minute.
* Number of QRS heartbeats per minute.
* Joining one-minute apnea labels with the corresponding ECG signal window.

### 2.4 Compression Support

The high-frequency `signals` table is expected to consume significant disk space. TimescaleDB supports native compression for hypertables.

Compression is especially relevant here because the data is naturally ordered by time and usually queried by recording. The project configures compression using:

* `recording_id` as the segment key.
* `recorded_at` as the ordering key.

This allows Sprint 2 to measure whether TimescaleDB reduces storage size compared with standard PostgreSQL.

---

## 3. Main Time-Series Challenges in the Dataset

The schema was designed around four important challenges in the Apnea-ECG dataset.

### 3.1 High-Frequency Signals

The ECG signal is sampled at **100 Hz**, meaning:

```text
100 samples/second × 60 seconds = 6,000 samples/minute
```

This produces a very large number of rows. Therefore, the schema must support efficient insertion, indexing, and time-range querying.

### 3.2 Frequency Mismatch Between Signals and Labels

ECG samples are available 100 times per second, but apnea annotations are available only once per minute.

For this reason, apnea labels are not stored inside every signal row. Doing so would duplicate the same label 6,000 times per minute.

Instead, the schema separates:

* High-frequency signal samples in `signals`.
* Minute-level apnea labels in `annotations_apnea`.
* Event-based QRS heartbeat annotations in `annotations_qrs`.

This keeps the design cleaner and avoids unnecessary duplication.

### 3.3 Missing Respiratory Modalities

All records contain ECG, but only 8 records contain the additional signals:

```text
a01, a02, a03, a04, b01, c01, c02, c03
```

These extra signals are:

* `Resp C`
* `Resp A`
* `Resp N`
* `SpO2`

The schema uses one wide `signals` table with nullable columns:

```text
ecg_value, resp_c, resp_a, resp_n, spo2
```

For ECG-only records, the respiration and SpO2 columns are set to `NULL`.

This is a controlled denormalization. The metadata and annotation tables remain normalized, while the signal table is intentionally wide to make ingestion and benchmarking simpler.

### 3.4 No Real Calendar Timestamps

The dataset does not provide real recording dates. It provides sample positions instead.

To support SQL time-range queries and TimescaleDB hypertables, the project creates artificial timestamps using a fixed baseline:

```text
2000-01-01 00:00:00
```

For each signal sample:

```text
recorded_at = recording_start_time + sample_index / sampling_rate_hz
```

At 100 Hz, the interval between two samples is 10 milliseconds.

The original `sample_index` is still stored to preserve traceability to the raw WFDB files.

---

## 4. PostgreSQL Relational Schema

PostgreSQL is used as the baseline relational database.

The main tables are:

| Table               | Purpose                                          |
| ------------------- | ------------------------------------------------ |
| `subjects`          | Stores subject-level information                 |
| `recordings`        | Stores metadata for each recording               |
| `signals`           | Stores ECG and optional respiratory/SpO2 samples |
| `annotations_apnea` | Stores expert apnea labels, one per minute       |
| `annotations_qrs`   | Stores machine-generated heartbeat locations     |

The relationships are:

```text
subjects
   └── recordings
          ├── signals
          ├── annotations_apnea
          └── annotations_qrs
```

### 4.1 Signal Table Key Design

In PostgreSQL, the natural identity of a signal sample is its recording and sample position. Therefore, the `signals` table uses:

```sql
PRIMARY KEY (recording_id, sample_index)
```

A unique constraint is also added on:

```sql
UNIQUE (recording_id, recorded_at)
```

This prevents duplicate timestamps inside the same recording and supports time-based queries.

### 4.2 PostgreSQL Indexing

Indexes are added to support Sprint 2 benchmark queries:

```sql
CREATE INDEX idx_recordings_subject
ON recordings(subject_id);

CREATE INDEX idx_apnea_events
ON annotations_apnea(recording_id, is_apnea, recorded_at);

CREATE INDEX idx_signals_time
ON signals(recorded_at);

CREATE INDEX idx_apnea_time
ON annotations_apnea(recorded_at);

CREATE INDEX idx_qrs_time
ON annotations_qrs(recorded_at);
```

These indexes support:

* Searching signals by time range.
* Filtering apnea events.
* Aggregating QRS annotations by time.
* Retrieving all recordings for a subject.

---

## 5. TimescaleDB Time-Series Schema

The TimescaleDB schema keeps the same logical structure as PostgreSQL, but the time-dependent tables are converted into hypertables.

The hypertables are:

| Table               | Reason                                                    |
| ------------------- | --------------------------------------------------------- |
| `signals`           | Main high-frequency ECG and respiration time-series table |
| `annotations_apnea` | Minute-level time-indexed labels                          |
| `annotations_qrs`   | Event-based heartbeat annotations                         |

The metadata tables `subjects` and `recordings` remain normal relational tables because they are not high-frequency time-series data.

### 5.1 Time Column and Primary Key

TimescaleDB uses `recorded_at` as the time partition column.

Because TimescaleDB hypertable primary keys must include the time partition column, the `signals` table uses:

```sql
PRIMARY KEY (recording_id, recorded_at)
```

The `sample_index` is still stored, but it is not the main TimescaleDB primary key.

### 5.2 Hypertable Creation

The `signals` table is converted into a hypertable:

```sql
SELECT create_hypertable(
    'signals',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
```

The annotation tables are also converted:

```sql
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
```

### 5.3 Chunk Interval Justification

The `signals` table uses a **1-hour chunk interval**.

This is chosen because all records use artificial timestamps starting from the same baseline. If the chunk interval were too large, such as 1 day, too many samples could be placed in the same chunk. A 1-hour interval creates smaller chunks and makes range-query benchmarking more meaningful.

The apnea and QRS annotation tables use 1-day chunks because they contain far fewer rows than the signal table.

### 5.4 Compression Configuration

Compression is enabled on the `signals` hypertable:

```sql
ALTER TABLE signals SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'recording_id',
    timescaledb.compress_orderby = 'recorded_at DESC'
);
```

This matches the expected query pattern because most queries filter by `recording_id` and scan a time interval.

The actual compression policy and compression ratio will be evaluated in Sprint 2 after data loading.

---

## 6. Planned Benchmark Queries

Sprint 2 will compare both databases using the same transformed data and equivalent SQL queries.

The planned benchmark tests are:

| Test                     | Purpose                                                      |
| ------------------------ | ------------------------------------------------------------ |
| Write throughput         | Measure ingestion speed in rows/second                       |
| One-hour ECG range query | Retrieve ECG data for a selected recording and time interval |
| ECG aggregation          | Calculate average/min/max ECG per minute                     |
| QRS aggregation          | Count heartbeats per minute                                  |
| Signal-label join        | Join 100 Hz ECG samples with one-minute apnea labels         |
| Storage footprint        | Compare table size and TimescaleDB compression ratio         |

Example range query:

```sql
SELECT recorded_at, ecg_value
FROM signals
WHERE recording_id = 'a01'
  AND recorded_at >= '2000-01-01 01:00:00'
  AND recorded_at <  '2000-01-01 02:00:00'
ORDER BY recorded_at;
```

Example aggregation query in TimescaleDB:

```sql
SELECT time_bucket('1 minute', recorded_at) AS minute_bucket,
       AVG(ecg_value) AS avg_ecg,
       MIN(ecg_value) AS min_ecg,
       MAX(ecg_value) AS max_ecg
FROM signals
WHERE recording_id = 'a01'
GROUP BY minute_bucket
ORDER BY minute_bucket;
```

These queries directly test the time-series features that motivated the choice of TimescaleDB.

---

## 7. Conclusion

This architecture uses PostgreSQL as a relational baseline and TimescaleDB as a time-series optimized alternative.

TimescaleDB was selected because it keeps PostgreSQL compatibility while adding hypertables, time-based chunking, time-window aggregation, and compression. These features match the main challenges of the Apnea-ECG dataset: high-frequency signals, large row volume, time-range queries, downsampling, and storage efficiency.

The schema addresses time-series-specific issues by:

* Creating artificial timestamps from sample indices.
* Preserving `sample_index` for traceability.
* Separating high-frequency signals from minute-level labels.
* Indexing time columns for range queries.
* Using hypertables for time-based chunking in TimescaleDB.
* Configuring compression on the largest table.
* Keeping the logical schema similar across PostgreSQL and TimescaleDB for a fair Sprint 2 benchmark.

The result is a reproducible architecture ready for data ingestion, performance testing, and later integration with an apnea anomaly detection model.
