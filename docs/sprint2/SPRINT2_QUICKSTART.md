# Sprint 2 Quick Start Guide

## What Needs to Be Built

```
SPRINT 2 WORK BREAKDOWN
├─ Phase 1: ETL Pipeline (30% effort)
│  ├─ ✅ etl_pipeline.py (skeleton provided)
│  ├─ ☐ data_quality.py (validate after extraction)
│  └─ ☐ Unit tests for ETL functions
│
├─ Phase 2: Dual Ingestion (35% effort)
│  ├─ ☐ ingest_postgresql.py (COPY + timing)
│  ├─ ☐ ingest_timescaledb.py (hypertable + compression)
│  └─ ☐ Connection pooling + retry logic
│
├─ Phase 3: Benchmarking (25% effort)
│  ├─ ☐ benchmark_suite.py (6 tests)
│  ├─ ☐ Query templates (hardcoded or from file)
│  └─ ☐ Result aggregation
│
└─ Phase 4: Reporting (10% effort)
   ├─ ☐ generate_benchmark_report.py
   ├─ ☐ Plot generation (matplotlib)
   └─ ☐ data_cleaning_log.md
```

---

## Execution Order

### Week 1: Setup & ETL

1. **Install dependencies**

   ```bash
   pip install -r requirements_sprint2.txt
   ```

2. **Run ETL on sample record**

   ```bash
   python scripts/etl_pipeline.py --record a01 --output data/processed
   ```

   Expected: 2.96M signal rows extracted in ~30 seconds

3. **Validate extraction quality**

   ```bash
   python scripts/data_quality.py --record a01
   ```

   Expected: Pass/fail report

4. **Complete ETL for all 70 records**
   ```bash
   python scripts/etl_pipeline.py --output data/processed
   ```
   Expected: ~206M rows, ~2–3 hours total

### Week 1–2: Ingestion

5. **Ingest into PostgreSQL**

   ```bash
   python scripts/ingest_postgresql.py --source data/processed
   ```

   Expected: ~200M rows ingested, timing logged

6. **Ingest into TimescaleDB**

   ```bash
   python scripts/ingest_timescaledb.py --source data/processed
   ```

   Expected: ~200M rows ingested, compression applied

7. **Validate ingestion**
   ```bash
   python scripts/validate_ingestion.py
   ```
   Expected: Row counts match, no integrity errors

### Week 2: Benchmarking

8. **Run benchmark suite**

   ```bash
   python scripts/benchmark_suite.py
   ```

   Expected: 6 tests × 2 databases, ~30 minutes total

9. **Generate report**

   ```bash
   python scripts/generate_benchmark_report.py
   ```

   Expected: Markdown + CSV + PNG charts in `docs/sprint2/`

10. **Write cleaning log**
    ```bash
    # Manual: Summarize transformation decisions
    cat docs/sprint2/data_cleaning_log.md
    ```

---

## File Organization

```
After Sprint 2 completion:

data/
├── raw/                    # Original WFDB files (from Sprint 1)
├── metadata/
│   └── dataset_baseline.json
└── processed/              # NEW: Intermediate ETL outputs
    ├── signals_a01.jsonl
    ├── signals_a02.jsonl
    ├── ...
    ├── apnea_a01.json
    ├── qrs_a01.json
    └── extraction_stats.json

scripts/
├── etl_pipeline.py         # NEW: Extract & transform
├── data_quality.py         # NEW: Validate
├── ingest_postgresql.py    # NEW: Load to PostgreSQL
├── ingest_timescaledb.py   # NEW: Load to TimescaleDB
├── benchmark_suite.py      # NEW: 6 performance tests
├── generate_benchmark_report.py  # NEW: Report generation
├── validate_ingestion.py   # NEW: Post-load checks
└── requirements_sprint2.txt # NEW: Dependencies

database/
├── postgresql/
│   ├── init/
│   │   └── 01_init_postgres.sql
│   └── ingestion_log.json  # NEW: Write metrics
└── timeseries/
    ├── init/
    │   └── 01_init_timescale.sql
    └── ingestion_log.json  # NEW: Write metrics

docs/sprint2/               # NEW: Reports
├── benchmark_report.md     # Main deliverable
├── benchmark_report.pdf    # PDF version
├── benchmark_data.csv      # Raw results
├── benchmark_latency_compare.png
├── benchmark_storage_efficiency.png
└── data_cleaning_log.md    # Transformation decisions
```

---

## Key Metrics to Track

| Metric                           | Expected Range    | Notes                       |
| -------------------------------- | ----------------- | --------------------------- |
| ETL time (all 70 records)        | 2–4 hours         | Depends on I/O speed        |
| PostgreSQL ingestion rate        | 50K–200K rows/sec | Batch size dependent        |
| TimescaleDB ingestion rate       | 50K–200K rows/sec | Should be similar           |
| 1-hour range query (PostgreSQL)  | 100–500ms         | On cold cache               |
| 1-hour range query (TimescaleDB) | 50–200ms          | With chunk exclusion        |
| Compression ratio (TimescaleDB)  | 2–5x              | Typical for medical signals |
| Storage size (uncompressed)      | ~20–40 GB         | Depends on signal precision |

---

## Dependencies

**Core**:

- `wfdb`: WFDB format parsing
- `psycopg2`: PostgreSQL driver
- `pandas`: Data manipulation
- `numpy`: Numerical operations

**Optional**:

- `matplotlib`: Chart generation
- `tqdm`: Progress bars
- `python-dotenv`: Environment config

Install all:

```bash
pip install -r requirements_sprint2.txt
```

---

## Common Issues & Solutions

| Issue                                  | Solution                                                              |
| -------------------------------------- | --------------------------------------------------------------------- |
| WFDB files not found                   | Check `data/raw/` directory, ensure dataset was organized in Sprint 1 |
| PostgreSQL connection refused          | Check Docker: `docker-compose ps`, ensure containers running          |
| Memory overflow during ETL             | Reduce batch size in `etl_pipeline.py` (default 50K)                  |
| Timestamps not matching between DBs    | Verify BASELINE_TIMESTAMP constant, check timezone handling           |
| Benchmark results vary widely          | Increase iterations, account for system load, run during off-peak     |
| Compression not applied in TimescaleDB | Ensure `ALTER TABLE` command executed after ingestion                 |

---

## Success Checklist

- [ ] ETL pipeline extracts all 70 records successfully
- [ ] Data quality checks pass (no NaNs, no gaps)
- [ ] PostgreSQL and TimescaleDB have identical row counts
- [ ] All 6 benchmarks execute and log results
- [ ] Benchmark report generated (Markdown + charts)
- [ ] Cleaning log documents all transformation decisions
- [ ] Code is reproducible: `scripts/` folder can be run end-to-end
- [ ] Both databases ready for Sprint 3 (model integration)

---

## Next Steps

1. Review this plan with team
2. Create skeleton files (`data_quality.py`, `ingest_postgresql.py`, etc.)
3. Install dependencies: `pip install -r requirements_sprint2.txt`
4. Run `etl_pipeline.py` on single record to test
5. Begin Phase 1 implementation

---

## Support

For questions on:

- **Architecture**: See `docs/sprint1/full_architecture.md`
- **Schema**: See `database/postgresql/init/01_init_postgres.sql`
- **Benchmark specs**: See `docs/sprint1/dataIngest.md#42-benchmarking-protocol`
- **Dataset structure**: See `data/metadata/dataset_baseline.json` (first few records)
