# Sprint 2 Alignment with SG05 Sprint 1 Deliverables

**Date**: May 8, 2026  
**Status**: Plan Refinement  
**Source**: SG05 Team Deliverables (Relational Schema + Ingestion & Benchmarking, Architecture Document)

---

## Verification: Plan Alignment with Team Deliverables

This document confirms that the Sprint 2 implementation plan aligns with the official SG05 deliverables from May 6, 2026.

### ✅ Core Alignment Points

#### 1. ETL Extract Phase (per SG05 Ingestion Strategy, Section A)

| Spec                   | SG05 Requirement                           | Implementation Plan                                       |
| ---------------------- | ------------------------------------------ | --------------------------------------------------------- |
| **Parsing**            | WFDB library for .dat/.hea/.apn/.qrs files | `etl_pipeline.py` uses `wfdb.rdrecord()` + `wfdb.rdann()` |
| **Modality Detection** | Auto-detect combined headers (e.g., a01er) | `extract_signals()` checks for `{record}er.hea` file      |
| **Signal Extraction**  | Read synchronized ECG + Resp signals       | Uses rec.p_signal[] with channel indexing                 |

#### 2. ETL Transform Phase (per SG05 Ingestion Strategy, Section B)

| Spec                    | SG05 Requirement                                                                                   | Implementation Plan                                   |
| ----------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| **Flattening**          | Matrix → row tuples with recording_id/sample_index/recorded_at/ecg_value/resp_c/resp_a/resp_n/spo2 | ✅ `SignalRow` dataclass                              |
| **Missing Modalities**  | ECG-only records → NULL for resp fields                                                            | ✅ Conditional logic in `extract_signals()`           |
| **Timestamp Synthesis** | baseline_time + (sample_index / 100)                                                               | ✅ `create_timestamp()` function                      |
| **Label Mapping**       | 'A'/'N' → TRUE/FALSE                                                                               | ✅ String comparison in `extract_apnea_annotations()` |

#### 3. ETL Load Phase (per SG05 Ingestion Strategy, Section C)

| Spec                  | SG05 Requirement                              | Implementation Plan                                                |
| --------------------- | --------------------------------------------- | ------------------------------------------------------------------ |
| **Dependency Order**  | subjects → recordings → signals → annotations | ✅ `ingest_postgresql.py` / `ingest_timescaledb.py` respects order |
| **Batch Size**        | 100,000 rows per batch                        | ✅ Fixed 100K (not variable 10K-100K)                              |
| **Insert Method**     | `psycopg2.extras.execute_values()` or `COPY`  | ✅ Both methods supported                                          |
| **Identical Loading** | Same batches to PostgreSQL & TimescaleDB      | ✅ Both scripts process identical ETL output                       |

#### 4. Database Architecture (per SG05 Architecture Document)

| Spec                  | SG05 Requirement                                                       | Implementation Plan                                 |
| --------------------- | ---------------------------------------------------------------------- | --------------------------------------------------- |
| **PostgreSQL PK**     | (recording_id, sample_index)                                           | ✅ Per schema in 01_init_postgres.sql               |
| **TimescaleDB PK**    | (recording_id, recorded_at)                                            | ✅ Per schema in 01_init_timescale.sql (hypertable) |
| **Signal Chunks**     | 1-hour chunks (section 3.4)                                            | ✅ Configured in `ingest_timescaledb.py`            |
| **Annotation Chunks** | 1-day chunks (section 3.4)                                             | ✅ Configured in `ingest_timescaledb.py`            |
| **Compression**       | compress_segmentby='recording_id', compress_orderby='recorded_at DESC' | ✅ In ALTER TABLE command                           |

#### 5. Benchmarking Protocol (per SG05 Benchmarking Protocol Document)

| Test # | SG05 Name                       | Purpose                                           | Implementation                       |
| ------ | ------------------------------- | ------------------------------------------------- | ------------------------------------ |
| **1**  | Write Throughput                | Measure ingestion speed                           | ✅ Captured during ETL phase         |
| **2**  | One-Hour Range Query            | Time-window retrieval (1h ECG)                    | ✅ 100 iterations, min/avg/max/stdev |
| **3**  | Temporal Downsampling           | 1-minute aggregation (DATE_TRUNC vs. time_bucket) | ✅ 10 iterations per DB              |
| **4**  | Event-Based Aggregation         | QRS heart rate (BPM per minute)                   | ✅ 10 iterations per DB              |
| **5**  | Signal-to-Label Join            | Link high-freq signals to low-freq apnea labels   | ✅ 5 iterations (expensive)          |
| **6**  | Storage Footprint & Compression | Disk size before/after TimescaleDB compression    | ✅ Measure compression ratio         |

#### 6. Synthetic Timestamps (per SG05 Architecture 3.1)

| Aspect             | SG05 Spec                                        | Implementation                         |
| ------------------ | ------------------------------------------------ | -------------------------------------- |
| **Baseline**       | 2000-01-01 00:00:00                              | ✅ BASELINE_TIMESTAMP constant         |
| **Offset Formula** | recorded_at = baseline + (sample_index / 100 Hz) | ✅ `create_timestamp()` uses timedelta |
| **Precision**      | 10ms intervals (100 Hz)                          | ✅ Seconds + microseconds precision    |
| **All Records**    | Same baseline for all 70 records                 | ✅ Hardcoded in constant               |

#### 7. Handling Frequency Mismatch (per SG05 Architecture 3.2)

| Aspect            | SG05 Spec                                                                                                                   | Implementation                                           |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| **Separation**    | signals table (100 Hz) separate from annotations (1/min)                                                                    | ✅ 3 tables: signals, annotations_apnea, annotations_qrs |
| **Join Strategy** | Dynamic JOIN with time-range (e.g., s.recorded_at >= a.recorded_at AND s.recorded_at < a.recorded_at + INTERVAL '1 minute') | ✅ Test 5 includes this exact join                       |
| **No Redundancy** | Avoid storing same label 6,000 times per minute                                                                             | ✅ Separate annotation table (1 row per minute, not 100) |

#### 8. Wide-Table Approach (per SG05 Architecture 3.3)

| Aspect               | SG05 Spec                                                                            | Implementation                                      |
| -------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------- |
| **Schema**           | Single signals table with nullable columns (ecg_value, resp_c, resp_a, resp_n, spo2) | ✅ Per 01_init_postgres.sql / 01_init_timescale.sql |
| **ECG-Only Records** | resp/spo2 = NULL (not missing)                                                       | ✅ Explicit NULLs for 62/70 records                 |
| **Minimizes JOINs**  | Avoid EAV or heavily normalized channel model                                        | ✅ Single flat row per sample                       |

---

## Key Differences Noted & Resolved

| Original Plan                   | SG05 Spec                                                              | Update                               |
| ------------------------------- | ---------------------------------------------------------------------- | ------------------------------------ |
| Batch size: 10K–100K (variable) | Batch size: 100K (fixed)                                               | ✅ Locked to 100K                    |
| Chunks: TBD                     | Signals: 1-hour; Annotations: 1-day                                    | ✅ Specified in code                 |
| Compression: TBD                | compress_segmentby='recording_id', compress_orderby='recorded_at DESC' | ✅ Exact config documented           |
| Label mapping: TBD              | 'A'/'N' → TRUE/FALSE                                                   | ✅ String comparison rule documented |
| Benchmark queries: Generic      | 6 specific tests with exact SQL                                        | ✅ SQL hardcoded per SG05 spec       |

---

## Conclusion

**Status**: ✅ **PLAN FULLY ALIGNED WITH SG05 SPRINT 1 DELIVERABLES**

The Sprint 2 implementation plan is compatible with and fully leverages:

1. PostgreSQL relational schema (5 tables, normalized)
2. TimescaleDB hypertable schema (same 5 tables, 3 as hypertables)
3. ETL architecture (Extract → Transform → Load with batch logic)
4. Benchmarking protocol (6 standardized tests with specific SQL queries)
5. Time-series design decisions (synthetic timestamps, chunking, compression)

No substantial changes to the implementation plan are required. Proceed with:

- **Phase 1**: ETL pipeline coding (etl_pipeline.py skeleton already created ✅)
- **Phase 2**: Ingestion scripts (ingest_postgresql.py, ingest_timescaledb.py)
- **Phase 3**: Benchmark suite (benchmark_suite.py with 6 tests)
- **Phase 4**: Reporting & analysis (generate_benchmark_report.py)
- **Phase 5**: Validation (validate_ingestion.py)
