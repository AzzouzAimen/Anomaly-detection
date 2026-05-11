# Sprint 2 Quick Start Guide
## Current Snapshot

```
SPRINT 2 REPOSITORY SNAPSHOT
├─ Phase 1: ETL Pipeline
│  ├─ ✅ etl_pipeline.py
│  └─ ☐ data_quality.py (planned)
│
├─ Phase 2: Dual Ingestion
│  ├─ ✅ ingest_postgresql.py
│  ├─ ✅ ingest_timescaledb.py
│  └─ ✅ partial-resume logic hardened per table
│
├─ Phase 3: Benchmarking
│  ├─ ✅ benchmark_suite.py
│  ├─ ✅ 4 timed SQL benchmarks
│  └─ ✅ ingestion throughput + storage/compression metrics in summary JSON
│
└─ Phase 4: Reporting & Validation
   ├─ ☐ generate_benchmark_report.py (planned)
   ├─ ☐ validate_ingestion.py (planned)
   └─ ☐ data_cleaning_log.md (planned)
```

---
## Execution Order

### ETL

1. **Install dependencies**

   ```bash
   pip install -r requirements_sprint2.txt
   ```

2. **Run ETL on a sample record**

   ```bash
   python scripts/etl_pipeline.py --record a01 --output data/processed
   ```

   Expected: JSONL/JSON files for signals, apnea annotations, and QRS annotations.

3. **Run ETL for all target records**

   ```bash
   python scripts/etl_pipeline.py --output data/processed
   ```

   Expected: one `signals_*.jsonl`, `apnea_*.json`, and `qrs_*.json` set per processed record.

### Ingestion

4. **Load PostgreSQL**

   ```bash
   python scripts/ingest_postgresql.py --processed-dir data/processed
   ```

   Output: `database/postgresql/ingestion_log.json`

5. **Load TimescaleDB**

   ```bash
   python scripts/ingest_timescaledb.py --processed-dir data/processed
   ```

   Output: `database/timeseries/ingestion_log.json`

   Notes:

   - the loader keeps metadata inserts idempotent when `--skip-cleanup` is used
   - existing Timescale signal chunks are explicitly compressed after load

### Benchmarking

6. **Run benchmark summary generation**

   ```bash
   python scripts/benchmark_suite.py
   ```

   Output:

   - `benchmarks/summary_postgresql.json`
   - `benchmarks/summary_timescaledb.json`
   - `benchmarks/summary.json`

   The benchmark summary currently includes:

   - 4 timed SQL benchmark results
   - ingestion throughput derived from ingestion logs
   - storage and compression metrics, including Timescale pre/post compression sizes

### Planned Follow-Up

The following helpers are still planned and are not present in the repository yet:

- `scripts/data_quality.py`
- `scripts/validate_ingestion.py`
- `scripts/generate_benchmark_report.py`
- `docs/sprint2/data_cleaning_log.md`

---
## File Organization

```
data/
├── raw/
├── metadata/
│   └── dataset_baseline.json
└── processed/
   ├── smoke_a01/
   ├── smoke_a05/
   └── ...additional ETL output directories...

scripts/
├── etl_pipeline.py
├── ingest_postgresql.py
├── ingest_timescaledb.py
├── benchmark_suite.py
├── data_quality.py                # planned
├── generate_benchmark_report.py   # planned
└── validate_ingestion.py          # planned

database/
├── postgresql/
│   ├── init/
│   └── ingestion_log.json
└── timeseries/
   ├── init/
   └── ingestion_log.json

docs/sprint2/
├── SPRINT2_ALIGNMENT_WITH_SG05.md
├── SPRINT2_EXECUTIVE_SUMMARY.md
├── SPRINT2_FIXES_SUMMARY.md
├── SPRINT2_QUICKSTART.md
└── sprint2_implementation_plan.md

benchmarks/
├── summary_postgresql.json
├── summary_timescaledb.json
└── summary.json

```

---
## Key Metrics To Track

| Metric                              | Expected Range    | Notes                                           |
| ----------------------------------- | ----------------- | ----------------------------------------------- |
| ETL time (all 70 records)           | 2-4 hours         | Depends on I/O speed                            |
| PostgreSQL ingestion rate           | 50K-200K rows/sec | Derived from `ingestion_log.json`               |
| TimescaleDB ingestion rate          | 50K-200K rows/sec | Derived from `ingestion_log.json`               |
| 1-hour range query latency          | 50-500ms          | Depends on DB engine and cache state            |
| Compression ratio (TimescaleDB)     | 2-5x              | Now measured with explicit chunk compression    |
| Storage size (pre-compression)      | ~20-40 GB         | Depends on signal precision and loaded coverage |

---
## Common Issues & Solutions

| Issue                                  | Solution                                                                 |
| -------------------------------------- | ------------------------------------------------------------------------ |
| WFDB files not found                   | Verify `data/raw/` contains the organized Apnea-ECG files                |
| Wrong ingestion CLI flag               | Use `--processed-dir`, not `--source`                                    |
| Partial rerun skips annotations        | Resume is now table-aware; reruns no longer infer completeness from `signals` alone |
| Memory pressure during ETL             | Reduce the ETL batch size from its default 100K rows if needed           |
| Benchmark results vary widely          | Rerun with `--record` for another recording; default benchmark target is `a01` |
| Compression metrics look inconsistent  | Use the updated scripts; Timescale chunks are explicitly compressed before post-compression reporting |

---
## Success Checklist

- [ ] ETL pipeline extracts all required records successfully
- [ ] PostgreSQL and TimescaleDB receive matching logical datasets
- [ ] Ingestion logs exist for both databases
- [ ] Benchmark summary JSON exists in `benchmarks/summary.json`
- [ ] Throughput and storage/compression metrics are present in the benchmark summary
- [ ] Remaining reporting and validation helpers are either implemented or replaced by documented manual steps

---
## Next Steps

1. Finish `data_quality.py`, `validate_ingestion.py`, and `generate_benchmark_report.py`.
2. Add `docs/sprint2/data_cleaning_log.md` once ETL and ingestion decisions are frozen.
3. If you benchmark multiple representative recordings, rerun `benchmark_suite.py --record <id>` and merge the JSON summaries manually or in a follow-up script.

---
## Support

- Architecture: `docs/sprint1/full_architecture.md`
- Schema: `database/postgresql/init/01_init_postgres.sql`
- Benchmark protocol: `docs/sprint1/dataIngest.md`
- Dataset structure: `data/metadata/dataset_baseline.json`
