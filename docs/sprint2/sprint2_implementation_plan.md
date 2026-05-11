# Sprint 2: Data Wrangling & Performance Benchmarking

## Implementation Plan

**Date**: May 8, 2026  
**Status**: Planning Reference + Current Implementation Snapshot  
**Target Duration**: 4-day sprint execution  
**Input**: Sprint 1 Deliverables (Raw data, metadata baseline, dual database schemas)  
**Output**: ETL pipeline, ingested data, comparative benchmarks

---

## 1. Goals

1. ✅ Transform raw WFDB signals into structured relational/time-series format (per SG05 Architecture Document)
2. ✅ Load the same processed data into both PostgreSQL and TimescaleDB (identical batches for fair comparison)
3. ✅ Capture the 6 benchmark categories defined by the Sprint 1 protocol
4. ✅ Document all cleaning and transformation decisions with Sprint 1 architecture alignment
5. ✅ Produce a detailed Comparative Benchmark Report (write throughput, query latency, storage efficiency)

---

## 2. Key Constraints & Assumptions (Aligned with SG05 Sprint 1 Deliverables)

| Constraint               | Details & Reference                                                                 |
| ------------------------ | ----------------------------------------------------------------------------------- |
| **Data Volume**          | ~206M signal rows (70 records × ~8 hours × 100 Hz)                                  |
| **Modality Sparsity**    | 8 records: respiration (Resp C/A/N) + SpO2; 62 ECG-only → wideTable with NULLs      |
| **Frequency Mismatch**   | 100 Hz signals vs. 1-minute apnea labels → separate tables, joined via time-ranges  |
| **Batch Size**           | 100K rows per batch (per SG05 Ingestion Strategy, section C)                        |
| **FK Constraint Order**  | subjects → recordings → signals → annotations (per SG05 Ingestion Strategy)         |
| **Synthetic Timestamps** | Baseline 2000-01-01 00:00:00 + sample_index / 100 Hz (per SG05 Architecture)        |
| **Hypertable Chunks**    | **Signals: 1-hour chunks** (per SG05 Architecture 3.4); Annotations: 1-day chunks   |
| **Compression**          | TimescaleDB: compress_segmentby='recording_id', compress_orderby='recorded_at DESC' |
| **Label Mapping**        | Apnea annotations: 'A'/'N' → boolean TRUE/FALSE (per SG05 Ingestion Strategy, B)    |
| **Database Parallelism** | Identical batches to both PostgreSQL & TimescaleDB for fair comparison              |
| **4-Day Constraint**     | Prioritize minimum viable ETL + ingestion + benchmark + report delivery             |

---

## 3. Implementation Phases

### Phase 1: ETL Pipeline Development (Day 1)

**Goal**: Build reproducible pipeline to extract WFDB, clean, normalize, and prepare for dual ingestion.

#### Phase 1.1: Core ETL Module

**File**: `scripts/etl_pipeline.py`

**Responsibilities**:

1. Parse WFDB headers (`.hea`) and signal data (`.dat`)
2. Parse annotations (`.apn` for apnea, `.qrs` for heartbeat)
3. Generate synthetic timestamps (baseline + sample_index / sampling_rate)
4. Handle missing modalities (NULLs for ECG-only records)
5. Normalize signal values (if needed)
6. Output structured batches ready for bulk insert

**Key Functions**:

- `extract_signals(record_name: str) -> Iterator[SignalBatch]` (100K rows per batch per SG05)
- `extract_apnea_annotations(record_name: str) -> List[ApneaEvent]` (with label → boolean mapping)
- `extract_qrs_annotations(record_name: str) -> List[QRSEvent]` (preserve sample indices)
- `create_timestamp(sample_index: int, sampling_rate: int) -> datetime` (baseline + offset formula)

**Dependencies**: `wfdb`, `psycopg2`, `pandas`, `numpy`

**Expected Output** (per SG05 Ingestion Strategy Transform phase):

- Batches of 100K rows (not 10K–100K; fixed at 100K for consistency)
- Flattened tuples: `(recording_id, sample_index, recorded_at, ecg_value, resp_c, resp_a, resp_n, spo2)`
- Apnea events: `(recording_id, minute_index, recorded_at, label_string, is_apnea_boolean)`
- QRS events: `(recording_id, sample_index, recorded_at)`

---

#### Phase 1.2: Data Quality Checks

**File**: `scripts/data_quality.py`

**Responsibilities**:

1. Validate no NaNs in critical columns (ecg_value, recorded_at)
2. Check timestamp ordering and continuity
3. Verify apnea annotation alignment (1 label per minute)
4. Confirm QRS sample indices are within signal range
5. Log warnings for data anomalies (duplicate timestamps, gaps)

**Key Functions**:

- `validate_signal_batch(batch: List[SignalRow]) -> ValidationReport`
- `validate_annotations(apnea_events: List, qrs_events: List) -> ValidationReport`
- `check_temporal_integrity(signals: Iterator) -> List[Anomaly]`

**Expected Output**:

- CSV or JSON log of data quality checks per recording
- Summary: pass/warn/fail counts

---

### Phase 2: Database Ingestion (Day 2)

**Goal**: Load cleaned data into both PostgreSQL and TimescaleDB, measure write performance.

**4-Day Scope Note**: prioritize a working end-to-end load path over optional optimizations.

#### Phase 2.1: PostgreSQL Ingestion

**File**: `scripts/ingest_postgresql.py`

**Responsibilities**:

1. Connect to PostgreSQL (via `psycopg2`)
2. Pre-insert subject/recording metadata
3. Bulk-insert signals using COPY or `executemany()`
4. Bulk-insert annotations
5. Measure and log ingestion time per phase

**Key Functions**:

- `insert_subjects(conn: Connection, subjects: List[Subject]) -> int`
- `insert_recordings(conn: Connection, recordings: List[Recording]) -> int`
- `bulk_insert_signals(conn: Connection, signal_batches: Iterator, batch_size: int = 50000) -> (rows_inserted, duration_sec)`
- `bulk_insert_annotations(conn: Connection, ...) -> (rows_inserted, duration_sec)`

**Metrics**:

- Total insertion time (seconds)
- Rows per second (signals, apnea, QRS)
- Peak memory usage

**Expected Output**:

- PostgreSQL tables populated
- Ingestion log: `database/postgresql/ingestion_log.json`

---

#### Phase 2.2: TimescaleDB Ingestion

**File**: `scripts/ingest_timescaledb.py`

**Responsibilities**:

1. Connect to TimescaleDB (via `psycopg2`)
2. Identical subject/recording insert as PostgreSQL
3. Bulk-insert signals into hypertable
4. Enable hypertable compression (post-insert)
5. Measure ingestion time and compression impact

**Key Functions**:

- Same as PostgreSQL, but with TimescaleDB-specific optimizations
- `enable_hypertable_compression(conn, table: str, segment_by: str, order_by: str) -> compression_time_sec`

**TimescaleDB-Specific**:

- Use `time_bucket()` if available for aggregation testing
- Monitor hypertable chunk creation
- Measure storage before and after compression

**Expected Output**:

- TimescaleDB hypertables populated
- Ingestion log: `database/timeseries/ingestion_log.json`
- Compression metrics

---

### Phase 3: Benchmark Execution (Day 3)

**Goal**: Run standardized performance tests on both databases.

#### Phase 3.1: Benchmark Suite

**File**: `scripts/benchmark_suite.py`

**Current implementation note**: the repository currently times four SQL query classes directly, then adds write-throughput metrics from ingestion logs and storage/compression metrics to `benchmarks/summary.json` so the SG05 benchmark categories are still represented in one summary payload.

**Tests**:

##### Test 1: Write Throughput (Already measured during ingestion)

- Metric: Rows/second for signals, annotations, total
- Output: Two numbers (PostgreSQL vs. TimescaleDB)

##### Test 2: Range Query Latency

- Query: 1 hour of ECG for a single recording
- Runs: 100 iterations, average latency
- Current script default: `a01` (rerun with `--record` for additional representative records)
- Expected: <100ms for TimescaleDB, varies for PostgreSQL

```sql
SELECT recorded_at, ecg_value
FROM signals
WHERE recording_id = ?
  AND recorded_at >= ?
  AND recorded_at < ? + INTERVAL '1 hour'
ORDER BY recorded_at;
```

##### Test 3: Temporal Aggregation (1-minute bucketing)

- Query: Compute mean/min/max ECG per minute for full recording
- Runs: 10 iterations, average latency
- Expected: <1s for TimescaleDB (with time_bucket), <5s for PostgreSQL

```sql
SELECT time_bucket('1 minute', recorded_at) AS minute,
       AVG(ecg_value) AS avg_ecg,
       MIN(ecg_value) AS min_ecg,
       MAX(ecg_value) AS max_ecg
FROM signals
WHERE recording_id = ?
GROUP BY minute
ORDER BY minute;
```

##### Test 4: Heart Rate Aggregation (QRS-based)

- Query: Count QRS events per minute for full recording
- Runs: 10 iterations, average latency
- Expected: <500ms for both

```sql
SELECT time_bucket('1 minute', recorded_at) AS minute,
       COUNT(*) AS beats_per_minute
FROM annotations_qrs
WHERE recording_id = ?
GROUP BY minute
ORDER BY minute;
```

##### Test 5: Signal-to-Label Join

- Query: Join 100 Hz signals with 1-minute apnea labels, compute per-minute stats
- Runs: 5 iterations (expensive), average latency
- Expected: <10s for both

```sql
SELECT a.minute_index,
       a.label,
       COUNT(*) AS signal_samples,
       AVG(s.ecg_value) AS avg_ecg
FROM annotations_apnea a
JOIN signals s
  ON s.recording_id = a.recording_id
 AND s.recorded_at >= a.recorded_at
 AND s.recorded_at <  a.recorded_at + INTERVAL '1 minute'
WHERE a.recording_id = ?
GROUP BY a.minute_index, a.label
ORDER BY a.minute_index;
```

##### Test 6: Storage Footprint (Pre & Post Compression)

- Query: Measure table sizes
- PostgreSQL: `pg_total_relation_size('signals')`
- TimescaleDB: Before compression, after compression, compression ratio

**Key Functions**:

- `run_benchmark(conn, query: str, params: tuple, iterations: int = 100) -> BenchmarkResult`
  - `BenchmarkResult`: `(min_ms, max_ms, avg_ms, stdev_ms, total_ms)`
- `measure_table_size(conn, table: str) -> bytes`
- `compare_benchmarks(pg_results, ts_results) -> ComparisonReport`

**Expected Output**:

- `benchmarks/summary_postgresql.json`
- `benchmarks/summary_timescaledb.json`
- Aggregated: `benchmarks/summary.json`

---

### Phase 4: Reporting & Analysis (Day 4)

**Goal**: Create Comparative Benchmark Report with tables and visualizations.

**4-Day Scope Note**: report generation must be automated enough to finish within the sprint window.

#### Phase 4.1: Benchmark Report Generation

**File**: `scripts/generate_benchmark_report.py` (planned, not present yet)

**Outputs**:

1. **Comparative Table** (Markdown & CSV):
   - All 6 tests × 2 databases
   - Metrics: min, avg, max latency; rows/sec; compression ratio

2. **Charts** (PNG, via matplotlib):
   - Bar chart: Average latency comparison per test
   - Line chart: Storage size trend (pre/post compression)
   - Box plot: Latency distribution for range query

3. **Summary Section**:
   - Which database wins each test
   - Overall conclusion (when is TimescaleDB worth the complexity?)
   - Recommendations for production deployment

**Key Functions**:

- `aggregate_all_benchmarks() -> DataFrame`
- `generate_markdown_table(df) -> str`
- `plot_latency_comparison() -> png`
- `plot_storage_efficiency() -> png`

**Expected Output**:

- `docs/sprint2/benchmark_report.md`
- `docs/sprint2/benchmark_*.png`
- `docs/sprint2/benchmark_data.csv`

---

#### Phase 4.2: Cleaning & Transformation Log

**File**: `docs/sprint2/data_cleaning_log.md`

**Contents**:

1. Missing value handling strategy (NULLs for respiration)
2. Timestamp synthesis approach (baseline + offset)
3. Annotation alignment (1-minute bucketing)
4. Data quality checks performed
5. Records with anomalies (if any)
6. Signal normalization decisions (if applied)

**Expected Output**:

- Markdown document suitable for publication

---

### Phase 5: Validation & Cleanup (Day 4, same pass as reporting)

**Goal**: Verify integrity and prepare for Sprint 3.

**4-Day Scope Note**: validation is lightweight and runs immediately after ingestion/benchmark completion.

#### Phase 5.1: Data Integrity Checks

**File**: `scripts/validate_ingestion.py` (planned, not present yet)

**Checks**:

1. Row counts: PostgreSQL signals == TimescaleDB signals
2. Sample values: Random spot checks (first/last/middle records)
3. Timestamp continuity: No gaps or duplicates
4. Foreign key consistency: All recordings/subjects exist
5. Annotation counts: All apnea/QRS events loaded

**Expected Output**:

- Pass/fail report: `validation_report.json`

---

## 4. File Structure (New Files)

```
scripts/
├── etl_pipeline.py              # Core ETL: extract, clean, transform
├── data_quality.py              # Data quality validation
├── ingest_postgresql.py         # PostgreSQL ingestion + timing
├── ingest_timescaledb.py        # TimescaleDB ingestion + compression
├── benchmark_suite.py           # Query timings + throughput/storage summary
├── generate_benchmark_report.py # Planned: report + charts generation
├── validate_ingestion.py        # Planned: post-ingestion integrity checks
└── requirements_sprint2.txt     # Dependencies (wfdb, psycopg2, pandas, etc.)

database/
├── postgresql/
│   └── ingestion_log.json       # Write performance metrics
└── timeseries/
    └── ingestion_log.json       # Write performance metrics

docs/sprint2/
├── SPRINT2_ALIGNMENT_WITH_SG05.md
├── SPRINT2_EXECUTIVE_SUMMARY.md
├── SPRINT2_FIXES_SUMMARY.md
├── SPRINT2_QUICKSTART.md
└── sprint2_implementation_plan.md
```

---

## 5. Execution Workflow

```
1. Sprint 1 outputs ready (raw data, metadata, schemas)
   ↓
2. Run `etl_pipeline.py`
   → Extracts WFDB, generates batches
   ↓
3. Run `data_quality.py` (planned)
   → Validates signal/annotation integrity once implemented
   ↓
4. Run `ingest_postgresql.py`
   → Loads data, measures write throughput
   ↓
5. Run `ingest_timescaledb.py`
   → Loads data, enables compression, measures impact
   ↓
6. Run `benchmark_suite.py`
   → Executes 4 timed SQL query benchmarks on the selected record
   → Adds ingestion throughput and storage/compression metrics to the JSON summary
   ↓
7. Run `validate_ingestion.py` (planned)
   → Cross-database consistency checks
   ↓
8. Run `generate_benchmark_report.py` (planned)
   → Produces markdown, CSV, PNG charts
   ↓
9. Write `data_cleaning_log.md`
   → Manual documentation of decisions
   ↓
10. Final Sprint 2 deliverable package
    ├── Both databases with data
   ├── benchmark summaries (JSON)
   ├── final report artifacts (planned)
   └── data_cleaning_log.md (planned)
```

---

## 6. Success Criteria

| Criterion                      | Target                                            |
| ------------------------------ | ------------------------------------------------- |
| **All 70 records ingested**    | 100% success rate into both DBs                   |
| **Data consistency**           | Row counts match between PostgreSQL & TimescaleDB |
| **Benchmarks complete**        | Summary JSON produced with query, throughput, and storage metrics |
| **Benchmark report published** | Markdown + CSV + charts (planned follow-up)       |
| **Cleaning log documented**    | Complete explanation of transformations           |
| **Code reproducible**          | Scripts run end-to-end with single command        |
| **Validation passing**         | Zero integrity errors                             |

---

## 7. Estimated Timeline

| Phase                         | Sprint Day | Notes                                            |
| ----------------------------- | ---------- | ------------------------------------------------ |
| ETL Pipeline + Quality Checks | Day 1      | ETL script present; quality helper still planned |
| PostgreSQL Ingestion          | Day 2      | Implemented                                      |
| TimescaleDB Ingestion         | Day 2      | Implemented with deterministic compression       |
| Benchmark Suite Execution     | Day 3      | Implemented summary workflow                     |
| Reporting & Analysis          | Day 4      | Planned follow-up                                |
| Validation & Cleanup          | Day 4      | Planned follow-up                                |

---

## 8. Deliverables Summary

### Primary Outputs

1. **ETL Pipeline**
   - Reproducible, tested, documented
   - Handles all 70 records
   - Stores transformation decisions in logs

2. **Structured Repositories**
   - PostgreSQL: `apnea_db` with ~206M signal rows
   - TimescaleDB: `apnea_ts_db` with same data, compressed

3. **Comparative Benchmark Summary**
   - Write throughput (rows/sec)
   - Query latencies (4 timed SQL tests in the current script)
   - Storage efficiency (pre/post compression metrics)
   - Recommendations for production

4. **Cleaning & Transformation Log**
   - Missing value handling
   - Timestamp synthesis
   - Annotation alignment
   - Anomalies encountered

5. **Code & Scripts**
   - Fully reproducible pipeline
   - Modular, reusable components
   - Requirements file for dependencies

---

## 9. Risk Mitigation

| Risk                      | Mitigation                                                                        |
| ------------------------- | --------------------------------------------------------------------------------- |
| **Long ingestion times**  | Batch-based processing, progress tracking, parallel record processing if possible |
| **Memory overflow**       | Stream-based iterator, configurable batch size, disk-based intermediate storage   |
| **Data inconsistency**    | Post-ingestion validation checks, row count comparison, spot-check sampling       |
| **Benchmark variability** | Multiple iterations (10–100), measure min/avg/max, account for system load        |
| **Schema mismatch**       | Verify schema creation before ingestion, automated schema tests                   |

---

## 10. Next Steps

1. **Approve this plan**
2. **Finish the remaining planned utilities** (`data_quality.py`, `validate_ingestion.py`, `generate_benchmark_report.py`)
3. **Install dependencies** (`pip install -r requirements_sprint2.txt`)
4. **Use the fixed ingestion CLI** (`--processed-dir`)
5. **Track progress** in this document

---

## 11. References

- [Sprint 1 Architecture Document](../architectureSprint1.md)
- [Data Ingest Strategy](../sprint1/dataIngest.md)
- [Benchmark Protocol](../sprint1/dataIngest.md#42-benchmarking-protocol)
- [Dataset Baseline](../../data/metadata/dataset_baseline.json)
