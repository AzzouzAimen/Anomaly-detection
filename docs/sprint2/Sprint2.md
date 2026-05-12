# Sprint 2

Sprint 2 implements the ETL, dual ingestion, benchmarking, storage analysis, and delivery tooling defined by the verified Sprint 1 architecture.

## Source Of Truth

Use the verified Sprint 1 documents as the design reference:

- `docs/sprint1/dataIngest.md`
- `docs/sprint1/Postgres.md`
- `docs/sprint1/Timescale.md`
- `docs/sprint1/full_architecture.md`

The removed Sprint 2 AI-generated notes are no longer authoritative and were replaced by this smaller, code-aligned documentation set.

## Current Sprint 2 Components

### ETL and validation

- `scripts/etl_pipeline.py`
- `scripts/validate_etl.py`
- `scripts/run_low_disk_pipeline.py`

Sprint 2 full runs now use the staged low-disk pipeline as the only supported workflow. `scripts/etl_pipeline.py` remains available for single-record smoke tests and local debugging only.

When per-record staging is removed after a successful low-disk run, `scripts/validate_etl.py` reuses the persisted per-record entries already stored in `<output-root>/validation_report.json` for standalone validation refreshes.

Primary outputs:

- `<output-root>/extraction_stats.json`
- `<output-root>/transformation_summary.json`
- `<output-root>/cleaning_transformation_log.md`
- `<output-root>/validation_report.json`
- `<output-root>/postgresql_ingestion_log.json`
- `<output-root>/timescaledb_ingestion_log.json`
- transient per-record staging directories under `<output-root>/_staging/`

### Dual ingestion

- `scripts/ingest_postgresql.py`
- `scripts/ingest_timescaledb.py`
- `scripts/ingest_common.py`

The ingestion scripts now connect directly over `host`/`port`/`user`/`password` with `psycopg2`; they no longer depend on `docker exec` plus `psql` for data loading.

Primary outputs:

- `database/postgresql/ingestion_log.json`
- `database/timeseries/ingestion_log.json`

### Benchmarking and reporting

- `scripts/benchmark_suite.py`
- `scripts/generate_benchmark_report.py`

`scripts/benchmark_suite.py` reads throughput metadata from the staged pipeline output root via `--processed-dir` so the reported ingestion-rate tables match the same processed artifact set that was loaded.

Primary outputs:

- `benchmarks/raw/summary_postgresql.json`
- `benchmarks/raw/summary_timescaledb.json`
- `benchmarks/raw/summary.json`
- `benchmarks/report/comparative_report.md`
- `benchmarks/report/throughput_summary.csv`
- `benchmarks/report/latency_summary.csv`
- `benchmarks/report/storage_summary.csv`
- `benchmarks/report/throughput_comparison.png`
- `benchmarks/report/latency_comparison.png`
- `benchmarks/report/storage_comparison.png`
- `benchmarks/report/compression_comparison.png`

### Structured repository exports

- `scripts/export_databases.py`
- `.env.example`

Primary outputs:

- `exports/export_manifest.json`
- `exports/STRUCTURED_REPOSITORY.md`
- optional dump files under `exports/<database>/`

## Important Implementation Notes

- ETL timestamps are now emitted as explicit UTC ISO-8601 strings.
- PostgreSQL and TimescaleDB are both treated as UTC systems for Sprint 2 reproducibility.
- ETL now produces one-minute feature windows aligned to the minute-level apnea annotation granularity of the Apnea-ECG dataset.
- The cleaning log explicitly documents non-finite replacement, structural null handling for missing modalities, no raw-signal resampling, and the caution that QRS annotations are machine-generated and unaudited.
- Timescale compression is no longer coupled to ingestion by default. Storage analysis should observe pre-compression and post-compression states during the benchmark/report flow.
- Benchmark query timing now uses persistent Python database connections instead of timing `docker exec` and `psql` startup overhead.
- PostgreSQL and TimescaleDB ingestion now use direct Python connectors and `COPY FROM STDIN`, so loader behavior matches the same connection model used by the benchmark suite.
- Sprint 2 full execution now runs record-by-record through the low-disk staged pipeline and removes large per-record staging files after successful dual-ingest.

