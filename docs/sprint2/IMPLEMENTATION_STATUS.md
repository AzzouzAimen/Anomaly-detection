# Sprint 2 Implementation Status

## Implemented In This Change Set

### 1. UTC and reproducibility fixes

Updated files:

- `scripts/etl_pipeline.py`
- `scripts/ingest_common.py`
- `scripts/ingest_postgresql.py`
- `scripts/ingest_timescaledb.py`
- `database/postgresql/init/01_init_postgres.sql`
- `docker-compose.yml`
- `.env.example`

What changed:

- ETL now emits explicit UTC timestamps instead of naive datetime strings.
- A shared timestamp parser normalizes processed timestamps before database load.
- PostgreSQL time columns now use `TIMESTAMPTZ` for alignment with the benchmark flow.
- Docker services now declare `TZ=UTC`.
- The PostgreSQL image is pinned more tightly for reproducibility.
- Timescale default username drift in `docker-compose.yml` was removed.

### 2. Transformation logging and ETL validation

Updated or added files:

- `scripts/etl_pipeline.py`
- `scripts/validate_etl.py`

What changed:

- ETL now writes `transformation_summary.json` with per-record metadata and totals.
- Extraction stats now include expected sample counts and timestamp ranges.
- ETL now writes one-minute `windows_<record>.json` outputs aligned to apnea-label granularity.
- ETL now writes `cleaning_transformation_log.md` documenting dataset-specific wrangling policy.
- `validate_etl.py` now checks row counts, monotonic timestamps, contiguous signal indices, annotation ordering, modality consistency, and window-level label/modality expectations.

### 3. Benchmark methodology upgrade

Updated file:

- `scripts/benchmark_suite.py`

What changed:

- benchmark execution now uses persistent `psycopg2` connections instead of measuring `docker exec` and `psql` process startup
- multiple records can be benchmarked in one run
- warmup iterations are supported
- raw timing samples are written into the benchmark JSON outputs so reports can compute additional statistics later
- report generation now includes an ingestion-rate chart in addition to latency, storage, and compression outputs

### 4. Storage analysis cleanup

Updated file:

- `scripts/ingest_timescaledb.py`

What changed:

- Timescale compression is no longer forced during ingestion by default
- immediate post-load compression is still available via `--compress-after-load`
- this keeps storage analysis compatible with a proper pre-compression and post-compression benchmark flow

### 5. Direct ingestion connectors

Updated files:

- `scripts/ingest_common.py`
- `scripts/ingest_postgresql.py`
- `scripts/ingest_timescaledb.py`

What changed:

- the ingestion path no longer depends on `docker exec` or `psql`
- PostgreSQL and TimescaleDB loaders now connect directly with `psycopg2`
- bulk signal and annotation loads now use `COPY FROM STDIN` over the live connection
- cleanup, existence checks, metadata inserts, and optional compression all run through the same Python connector path

### 6. Reporting and export tooling

Added files:

- `scripts/generate_benchmark_report.py`
- `scripts/export_databases.py`

What changed:

- benchmark JSON can now be turned into a Markdown comparative report, CSV summaries, and PNG charts
- export preparation is now scripted through an export manifest, a structured repository package note, and optional execution mode

### 7. Low-disk staged execution mode

Added file:

- `scripts/run_low_disk_pipeline.py`

What changed:

- Sprint 2 now has a staged execution mode that ETLs, validates, and ingests one record at a time
- the new mode writes cumulative small outputs while keeping large per-record staging files short-lived
- after PostgreSQL and TimescaleDB both succeed for a record, the staging directory is removed by default
- if ETL, validation, or either database load fails, the current staging directory is preserved for inspection and retry
- the staged low-disk path is now the default and only supported full-run workflow

## Not Done Automatically In This Change Set

The following were intentionally not executed here because they can take too long on the full dataset:

- full ETL regeneration
- full PostgreSQL and TimescaleDB reloads
- full benchmark runs
- full database exports

## Manual Follow-Up Required

1. Regenerate processed ETL and ingestion outputs with `scripts/run_low_disk_pipeline.py` so existing artifacts use the staged workflow and current UTC timestamp format.
2. Regenerate benchmark outputs with the new runner.
3. Generate the comparative report and export manifest from those fresh artifacts.

## Practical Exit Criteria For Sprint 2

Sprint 2 is in a good state when all of the following exist and come from one consistent run sequence:

- `data/processed/transformation_summary.json`
- `data/processed/cleaning_transformation_log.md`
- `data/processed/validation_report.json`
- `database/postgresql/ingestion_log.json`
- `database/timeseries/ingestion_log.json`
- `benchmarks/raw/summary.json`
- `benchmarks/report/comparative_report.md`
- `exports/export_manifest.json`
- `exports/STRUCTURED_REPOSITORY.md`

## Remaining Engineering Risk

- Existing artifacts committed before this change are stale until regenerated.
- The report generator assumes matplotlib is available from `requirements_sprint2.txt`.
- Full-dataset runtime and disk usage still need to be measured empirically after regeneration.
