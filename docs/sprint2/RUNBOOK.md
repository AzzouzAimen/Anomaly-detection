# Sprint 2 Runbook

This runbook matches the current repository state.

## 1. Install dependencies

```bash
pip install -r requirements_sprint2.txt
```

## 2. Configure environment

Start from `.env.example` and create a local `.env` if needed.

Key settings:

- PostgreSQL host, port, database, user, password
- TimescaleDB host, port, database, user, password
- `TZ=UTC`

The ingestion scripts use these network credentials directly through `psycopg2`; they do not shell out through `docker exec`.

## 3. Start databases

```bash
docker compose up -d
```

## 4. Run ETL

Sprint 2 now uses one execution mode for full runs: the staged low-disk pipeline.

Single-record ETL is still available only for smoke tests or local debugging:

```bash
python scripts/etl_pipeline.py --record a01 --output data/processed/smoke_a01 --max-samples 1000
```

Main full-run command:

```bash
python scripts/run_low_disk_pipeline.py
```

Outputs to expect:

- cumulative ETL and ingestion outputs in `data/processed`
- transient per-record staging under `data/processed/_staging/<record>`

Smoke-sized staged run:

```bash
TIMESCALE_USER=timescale_user TIMESCALE_PASSWORD=timescale_password \
python scripts/run_low_disk_pipeline.py --record a01 --max-samples 1000 --output-root data/processed/smoke_a01_low_disk
```

Behavior:

- a per-record staging directory is created under `<output-root>/_staging/<record>`
- ETL, validation, PostgreSQL load, and TimescaleDB load run for that record before moving to the next one
- cumulative small outputs are kept in `<output-root>/`
- the per-record staging directory is deleted after successful dual-ingest unless `--keep-staging` is used
- if ETL, validation, or either database load fails, the current staging directory is preserved for inspection and rerun

Persistent outputs from the staged pipeline:

- `data/processed/extraction_stats.json`
- `data/processed/transformation_summary.json`
- `data/processed/cleaning_transformation_log.md`
- `data/processed/validation_report.json`
- `data/processed/postgresql_ingestion_log.json`
- `data/processed/timescaledb_ingestion_log.json`

## 5. Validate ETL outputs

```bash
python scripts/validate_etl.py --processed-dir data/processed
```

Output:

- `data/processed/validation_report.json`

Notes:

- if the staged pipeline already removed per-record files under `_staging/`, `validate_etl.py` reuses the persisted per-record validation entries from the existing `validation_report.json` instead of turning the staged run into a false failure
- if you want the validator to read live per-record files directly, rerun the staged pipeline with `--keep-staging`

## 6. Load PostgreSQL

```bash
python scripts/ingest_postgresql.py --processed-dir data/processed
```

Output:

- `database/postgresql/ingestion_log.json`

## 7. Load TimescaleDB

The default connection settings come from `.env` or the fallback values in `.env.example`.

Recommended for fair storage analysis:

```bash
python scripts/ingest_timescaledb.py --processed-dir data/processed
```

Optional if you explicitly want chunks compressed immediately after load:

```bash
python scripts/ingest_timescaledb.py --processed-dir data/processed --compress-after-load
```

Output:

- `database/timeseries/ingestion_log.json`

## 8. Run benchmarks

Benchmark one or more representative records:

```bash
python scripts/benchmark_suite.py --record a01 --record a05 --processed-dir data/processed --output-dir benchmarks/raw
```

Output:

- `benchmarks/raw/summary_postgresql.json`
- `benchmarks/raw/summary_timescaledb.json`
- `benchmarks/raw/summary.json`

Notes:

- benchmark timing uses persistent `psycopg2` connections
- warmup iterations default to `2`
- throughput metadata is read from `<processed-dir>/postgresql_ingestion_log.json` and `<processed-dir>/timescaledb_ingestion_log.json`, so use the same `--processed-dir` as the staged pipeline output root when benchmarking smoke or alternate runs
- the benchmark runner performs Timescale compression during storage analysis so pre-compression and post-compression sizes are measurable

## 9. Generate the comparative report

```bash
python scripts/generate_benchmark_report.py --input benchmarks/raw/summary.json --output-dir benchmarks/report
```

Output:

- `benchmarks/report/comparative_report.md`
- `benchmarks/report/throughput_summary.csv`
- `benchmarks/report/latency_summary.csv`
- `benchmarks/report/storage_summary.csv`
- `benchmarks/report/throughput_comparison.png`
- `benchmarks/report/latency_comparison.png`
- `benchmarks/report/storage_comparison.png`
- `benchmarks/report/compression_comparison.png`

## 10. Prepare or execute exports

Prepare the export manifest only:

```bash
python scripts/export_databases.py --mode full --database both --output-dir exports
```

Execute exports:

```bash
python scripts/export_databases.py --mode full --database both --output-dir exports --execute
```

Output:

- `exports/export_manifest.json`
- `exports/STRUCTURED_REPOSITORY.md`
- optional dump files under `exports/postgresql/` and `exports/timescaledb/`

## Recommended Record Set For Benchmarking

To avoid benchmarking only `a01`, use at least:

- one multimodal learning record such as `a01`
- one ECG-only learning record such as `a05`
- one additional record from another category such as `b01` or `c01`

## Regeneration Rule

If processed files, ingestion logs, or benchmark results were generated before the UTC and benchmark-flow changes, regenerate them in this order:

1. Staged ETL + validation + PostgreSQL ingestion + TimescaleDB ingestion via `scripts/run_low_disk_pipeline.py`
2. ETL validation re-check if you want a standalone verification artifact refresh
3. Benchmarking
4. Report generation
5. Exports

The older all-record full-materialization ETL flow is no longer part of the supported Sprint 2 runbook.

## Dataset-Specific Wrangling Notes

- Windowing is fixed to one-minute slices because Apnea-ECG apnea annotations are minute-level.
- Raw signals remain at 100 Hz; the ETL does not resample sample-level data.
- The eight multimodal records keep respiration and SpO2 statistics in window outputs; ECG-only records keep those modalities structurally unavailable.
- QRS annotations are included for derived counts, but they remain machine-generated and unaudited.
