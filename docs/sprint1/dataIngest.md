
## 4. Data Inestion & Benchmarking Strategy

To manage the scale and complexity of the PhysioNet Apnea-ECG Database, a structured Extraction, Transformation, and Loading pipeline is required. The dataset contains 70 long-duration recordings, each sampled at 100 Hz, which results in a very large number of signal rows. Depending on the exact duration of each recording, the final database is expected to contain roughly **120–200 million signal samples**.

The ingestion strategy must handle three main challenges:

1. The difference between high-frequency ECG signals and minute-level apnea annotations.
2. The fact that only 8 recordings contain additional respiratory and SpO2 signals.
3. The need to load the same processed data into both PostgreSQL and TimescaleDB for comparison.

### 4.1. ETL & Ingestion Strategy

The ingestion process follows an ETL approach: extracting raw PhysioNet files, transforming them into a consistent relational/time-series structure, and loading them into both databases.

#### 1. Extraction: WFDB File Parsing

The raw Apnea-ECG files are stored in WFDB format. The Python `wfdb` library will be used to parse these files.

The continuous signal data will be extracted using:

```python
wfdb.rdrecord(record_name)
```

This function reads the `.hea` and `.dat` files and returns the ECG signal, and when available, the additional respiratory signals.

For apnea annotations, the pipeline will use:

```python
wfdb.rdann(record_name, "apn")
```

These annotations provide one label per minute. The labels are stored only for the learning records: `a`, `b`, and `c`. Test records `x01` to `x35` do not contain apnea labels, so their signal data will be inserted normally, while their `annotations_apnea` table entries will remain empty.

For QRS annotations, the pipeline will use:

```python
wfdb.rdann(record_name, "qrs")
```

These annotations provide the sample locations of detected heartbeats. Since they are machine-generated and unaudited, they will be stored separately from the expert apnea annotations.

#### 2. Metadata Insertion

Before inserting the signal samples, the pipeline first inserts metadata into the `subjects` and `recordings` tables.

Each recording is assigned:

| Field                  | Description                                           |
| ---------------------- | ----------------------------------------------------- |
| `recording_id`         | Original record name, for example `a01`               |
| `subject_id`           | Subject identifier                                    |
| `split`                | `learning` for `a`, `b`, `c`; `test` for `x`          |
| `record_category`      | `a`, `b`, `c`, or `x`                                 |
| `has_respiration`      | `TRUE` only for records with respiration/SpO2 signals |
| `has_apnea_labels`     | `TRUE` for learning records, `FALSE` for test records |
| `sampling_rate_hz`     | Usually 100 Hz                                        |
| `length_seconds`       | Duration of the recording                             |
| `recording_start_time` | Artificial timestamp baseline                         |

Special case: records `c05` and `c06` are mapped to the same subject because the dataset documentation indicates that they originate from the same original recording.

#### 3. Transformation: Timestamp Synthesis

The Apnea-ECG dataset does not provide real calendar timestamps. Instead, time is represented through sample positions.

To make the data compatible with SQL time-series queries, each recording is assigned an artificial baseline timestamp:

```text
2000-01-01 00:00:00
```

For every signal sample, the timestamp is generated as:

```text
recorded_at = recording_start_time + sample_index / sampling_rate_hz
```

Since the sampling rate is 100 Hz, the interval between two consecutive ECG samples is:

```text
1 / 100 = 0.01 seconds = 10 milliseconds
```

Therefore, the first few samples are mapped as follows:

| sample_index | recorded_at             |
| -----------: | ----------------------- |
|            0 | 2000-01-01 00:00:00.000 |
|            1 | 2000-01-01 00:00:00.010 |
|            2 | 2000-01-01 00:00:00.020 |
|          100 | 2000-01-01 00:00:01.000 |

The `sample_index` is also stored in the database to preserve traceability to the original raw WFDB files.

#### 4. Transformation: Handling Missing Modalities

All 70 records contain ECG signals, but only 8 records contain the additional respiratory and SpO2 signals:

```text
a01, a02, a03, a04, b01, c01, c02, c03
```

For these records, the columns `resp_c`, `resp_a`, `resp_n`, and `spo2` are filled with actual values.

For the remaining ECG-only records, these columns are filled with `NULL`.

This design keeps a consistent table structure while avoiding false or imputed respiratory data.

#### 5. Transformation: Apnea Annotation Alignment

Apnea annotations are minute-level labels, not 100 Hz labels. Each annotation corresponds to a 60-second interval.

For example:

| minute_index | recorded_at         | Meaning            |
| -----------: | ------------------- | ------------------ |
|            0 | 2000-01-01 00:00:00 | Label for minute 0 |
|            1 | 2000-01-01 00:01:00 | Label for minute 1 |
|            2 | 2000-01-01 00:02:00 | Label for minute 2 |

The original label is stored in the `label` column:

```text
A = apnea
N = normal
```

A boolean version is also stored in `is_apnea` to simplify machine learning and SQL queries.

#### 6. Loading: Optimized Batch Insertion

Inserting millions of samples row by row using individual `INSERT` statements would be too slow. Therefore, the pipeline will use batch insertion.

The signal data will be processed recording by recording and inserted in batches, for example:

```text
100,000 rows per batch
```

The Python pipeline can use either:

```python
psycopg2.extras.execute_values()
```

or PostgreSQL `COPY` for higher performance.

The same transformed batches will be inserted into both databases:

1. PostgreSQL database.
2. TimescaleDB database.

This guarantees that both systems contain equivalent data and that Sprint 2 benchmarking is fair.

#### 7. Loading Order

To preserve foreign key integrity, data will be inserted in the following order:

```text
1. subjects
2. recordings
3. signals
4. annotations_apnea
5. annotations_qrs
```

This order ensures that every signal and annotation row references an existing recording.

---

## 4.2. Benchmarking Protocol

To compare the standard relational architecture with the time-series optimized architecture, the project will run the same benchmark tests on both PostgreSQL and TimescaleDB during Sprint 2.

The goal is to measure whether TimescaleDB provides practical advantages for medical time-series workloads such as range retrieval, temporal aggregation, and storage compression.

### Test 1: Write Throughput

This test measures how long it takes to insert the full dataset into each database.

The main metric is:

```text
Rows inserted per second
```

The total insertion time will be measured for:

1. Signal samples.
2. Apnea annotations.
3. QRS annotations.

Expected result: TimescaleDB may perform differently due to hypertable chunking, while PostgreSQL provides a standard relational baseline. The result will be measured empirically rather than assumed.

### Test 2: Range Query Latency

This test simulates a clinical dashboard or application retrieving one hour of ECG data for a specific recording.

The query will be executed multiple times, for example 100 runs, and the average latency will be recorded.

#### PostgreSQL Query

```sql
SELECT recorded_at, ecg_value
FROM signals
WHERE recording_id = 'a01'
  AND recorded_at >= '2000-01-01 01:00:00'
  AND recorded_at <  '2000-01-01 02:00:00'
ORDER BY recorded_at;
```

#### TimescaleDB Query

```sql
SELECT recorded_at, ecg_value
FROM signals
WHERE recording_id = 'a01'
  AND recorded_at >= '2000-01-01 01:00:00+00'
  AND recorded_at <  '2000-01-01 02:00:00+00'
ORDER BY recorded_at;
```

The SQL logic is almost identical. The difference is that TimescaleDB can use hypertable chunk exclusion to avoid scanning irrelevant time chunks.

### Test 3: Temporal Aggregation

This test simulates feature extraction for the anomaly detection model.

The objective is to calculate the average ECG value per minute for a full recording.

#### PostgreSQL Query

```sql
SELECT DATE_TRUNC('minute', recorded_at) AS minute_bucket,
       AVG(ecg_value) AS avg_ecg,
       MIN(ecg_value) AS min_ecg,
       MAX(ecg_value) AS max_ecg
FROM signals
WHERE recording_id = 'a01'
GROUP BY DATE_TRUNC('minute', recorded_at)
ORDER BY minute_bucket;
```

#### TimescaleDB Query

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

This benchmark is important because downsampling and aggregation are common operations in medical signal preprocessing.

### Test 4: QRS-Based Heart Rate Aggregation

This test uses the QRS annotation table to compute the number of detected heartbeats per minute.

This is useful because heart-rate-derived features can later be used for apnea detection.

#### PostgreSQL Query

```sql
SELECT DATE_TRUNC('minute', recorded_at) AS minute_bucket,
       COUNT(*) AS beats_per_minute
FROM annotations_qrs
WHERE recording_id = 'a01'
GROUP BY DATE_TRUNC('minute', recorded_at)
ORDER BY minute_bucket;
```

#### TimescaleDB Query

```sql
SELECT time_bucket('1 minute', recorded_at) AS minute_bucket,
       COUNT(*) AS beats_per_minute
FROM annotations_qrs
WHERE recording_id = 'a01'
GROUP BY minute_bucket
ORDER BY minute_bucket;
```

### Test 5: Signal-to-Label Join

This test checks how efficiently each database can join high-frequency signal windows with minute-level apnea annotations.

This is important for preparing training windows for the anomaly detection model.

```sql
SELECT s.recording_id,
       a.minute_index,
       a.label,
       a.is_apnea,
       COUNT(*) AS signal_samples,
       AVG(s.ecg_value) AS avg_ecg
FROM annotations_apnea a
JOIN signals s
  ON s.recording_id = a.recording_id
 AND s.recorded_at >= a.recorded_at
 AND s.recorded_at <  a.recorded_at + INTERVAL '1 minute'
WHERE a.recording_id = 'a01'
GROUP BY s.recording_id, a.minute_index, a.label, a.is_apnea
ORDER BY a.minute_index;
```

This query groups the 100 Hz signal samples into the corresponding apnea-labeled minute.

### Test 6: Storage Footprint and Compression Efficiency

After data ingestion, the physical storage size of the `signals` table will be measured in both databases.

#### PostgreSQL / TimescaleDB Size Query

```sql
SELECT pg_size_pretty(pg_total_relation_size('signals')) AS total_size;
```

For TimescaleDB, compression will then be applied to the `signals` hypertable.

```sql
ALTER TABLE signals SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'recording_id',
    timescaledb.compress_orderby = 'recorded_at DESC'
);
```

After compression, the same size query will be executed again.

The compression ratio will be calculated as:

```text
compression_ratio = size_before_compression / size_after_compression
```

---

## 4.3. Expected Benchmark Metrics

The results will be summarized in a comparison table.

| Metric                             |     PostgreSQL |    TimescaleDB |
| ---------------------------------- | -------------: | -------------: |
| Signal ingestion time              | To be measured | To be measured |
| Rows inserted per second           | To be measured | To be measured |
| 1-hour range query latency         | To be measured | To be measured |
| 1-minute ECG aggregation latency   | To be measured | To be measured |
| QRS heart-rate aggregation latency | To be measured | To be measured |
| Signal-label join latency          | To be measured | To be measured |
| Storage size before compression    | To be measured | To be measured |
| Storage size after compression     | Not applicable | To be measured |
| Compression ratio                  | Not applicable | To be measured |

---

## 4.4. Summary

The ingestion pipeline transforms the raw WFDB files into a structured format suitable for both relational storage and time-series optimized storage. PostgreSQL provides the normalized baseline architecture, while TimescaleDB provides hypertables, time-based chunking, and compression.

The benchmarking protocol will allow the project to compare both systems using realistic medical time-series workloads: bulk ingestion, range retrieval, downsampling, QRS-based aggregation, signal-label joining, and storage analysis.
