# Respiratory Apnea Detection Data Platform

This repository builds a reproducible medical time-series data platform for the
PhysioNet Apnea-ECG database. It prepares raw WFDB recordings, validates the
processed artifacts, loads the same data model into PostgreSQL and TimescaleDB,
then benchmarks the two storage backends for apnea-focused queries.

The current Sprint 2 workflow is centered on a low-disk staged pipeline: each
record is transformed, validated, loaded into both databases, and then its large
temporary files are removed after successful ingestion.

## What This Project Does

- Converts Apnea-ECG WFDB signals and annotations into structured JSON/JSONL
  artifacts.
- Preserves raw 100 Hz ECG samples and aligns apnea labels to one-minute
  annotation windows.
- Handles the dataset's sparse modality split: all 70 records have ECG, but only
  8 records include respiration and SpO2 channels.
- Uses synthetic UTC timestamps starting at `2000-01-01 00:00:00+00` because the
  source records provide elapsed samples rather than calendar dates.
- Loads equivalent schemas into PostgreSQL and TimescaleDB.
- Benchmarks ingestion, query latency, storage size, and Timescale compression.
- Generates comparative reports, charts, and optional database export manifests.

## Repository Layout

```text
data/
  metadata/                 Generated dataset metadata tracked in git
  raw/                      Local PhysioNet files, ignored by git
  processed/                ETL outputs, ignored by git
database/
  postgresql/init/          PostgreSQL schema
  timeseries/init/          TimescaleDB schema and hypertables
docs/
  sprint1/                  Architecture and database design notes
  sprint2/                  Current implementation notes and runbook
scripts/
  organize_dataset.py       Move downloaded PhysioNet files into data/raw
  generate_metadata.py      Rebuild dataset_baseline.json from raw headers
  preview_data.py           Inspect raw files and optionally plot signals
  etl_pipeline.py           Single-record ETL and shared ETL functions
  run_low_disk_pipeline.py  Main Sprint 2 ETL -> validate -> dual-ingest flow
  validate_etl.py           Validate processed artifacts
  ingest_postgresql.py      Direct PostgreSQL loader
  ingest_timescaledb.py     Direct TimescaleDB loader
  benchmark_suite.py        PostgreSQL vs Timescale benchmark runner
  generate_benchmark_report.py
  export_databases.py
```

## Prerequisites

- Python 3.10+
- Docker and Docker Compose
- Enough local disk for the raw Apnea-ECG download and staged ETL output

Install the runtime packages used by the current scripts:

```bash
pip install wfdb numpy tqdm psycopg2-binary matplotlib
```

## Environment

Create a local `.env` from the example file:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux:

```bash
cp .env.example .env
```

Default services:

- PostgreSQL: `127.0.0.1:5432`, database `apnea_db`
- TimescaleDB: `127.0.0.1:5433`, database `apnea_ts_db`
- Timezone: UTC

If you are not on ARM64, update `DOCKER_PLATFORM` in `.env` or unset it before
starting Docker.

## Start The Databases

```bash
docker compose up -d
```

This starts:

- `apnea_postgres` using `database/postgresql/init/01_init_postgres.sql`
- `apnea_timescaledb` using `database/timeseries/init/01_init_timescale.sql`

The ingestion and benchmark scripts connect directly with `psycopg2`; they do
not depend on `docker exec`.

## Get The Dataset

Download the PhysioNet Apnea-ECG database:

```bash
wget -r -N -c -np https://physionet.org/files/apnea-ecg/1.0.0/
```

Then move the WFDB files into the expected local directory:

```bash
python scripts/organize_dataset.py
```

Optional: regenerate metadata after organizing the raw files:

```bash
python scripts/generate_metadata.py
```

Optional: inspect a record before running ETL:

```bash
python scripts/preview_data.py --record a01 --load-signal --max-samples 1000
```

## Main Sprint 2 Workflow

For a full run, use the staged low-disk pipeline:

```bash
python scripts/run_low_disk_pipeline.py
```

For a small smoke test:

```bash
python scripts/run_low_disk_pipeline.py --record a01 --max-samples 1000 --output-root data/processed/smoke_a01
```

Useful options:

- `--record a01` can be repeated to process selected records.
- `--max-samples 1000` caps signal rows for smoke testing.
- `--keep-staging` keeps per-record staging files after successful ingestion.
- `--compress-after-load` compresses Timescale chunks immediately after load.

Expected cumulative outputs under the selected output root:

- `extraction_stats.json`
- `transformation_summary.json`
- `cleaning_transformation_log.md`
- `validation_report.json`
- `postgresql_ingestion_log.json`
- `timescaledb_ingestion_log.json`

Large per-record staging files live under `<output-root>/_staging/<record>` and
are deleted after successful validation plus dual ingestion unless
`--keep-staging` is used.

## Standalone Commands

Run single-record ETL only:

```bash
python scripts/etl_pipeline.py --record a01 --output data/processed/smoke_a01 --max-samples 1000
```

Validate processed artifacts:

```bash
python scripts/validate_etl.py --processed-dir data/processed
```

Load PostgreSQL from processed artifacts:

```bash
python scripts/ingest_postgresql.py --processed-dir data/processed
```

Load TimescaleDB from processed artifacts:

```bash
python scripts/ingest_timescaledb.py --processed-dir data/processed
```

## Benchmark And Report

Benchmark representative records from both multimodal and ECG-only groups:

```bash
python scripts/benchmark_suite.py --record a01 --record a05 --record b01 --processed-dir data/processed --output-dir benchmarks/raw
```

Generate report tables and charts:

```bash
python scripts/generate_benchmark_report.py --input benchmarks/raw/summary.json --output-dir benchmarks/report
```

Expected report outputs:

- `benchmarks/report/comparative_report.md`
- `benchmarks/report/throughput_summary.csv`
- `benchmarks/report/latency_summary.csv`
- `benchmarks/report/storage_summary.csv`
- `benchmarks/report/*.png`

## Database Exports

Prepare an export manifest without running dumps:

```bash
python scripts/export_databases.py --mode full --database both --output-dir exports
```

Execute the export commands:

```bash
python scripts/export_databases.py --mode full --database both --output-dir exports --execute
```

## Dataset Notes That Affect The Design

- ECG samples are high-frequency: 100 Hz, or 6,000 rows per minute.
- Apnea annotations are minute-level, so they are stored separately from raw
  signal samples.
- Only 8 records include respiration and SpO2 channels; the schemas keep those
  columns nullable for the remaining ECG-only records.
- QRS annotations are included for derived heartbeat counts, but they are
  machine-generated and should not be treated as manually verified labels.
- PostgreSQL uses a conventional relational schema. TimescaleDB uses matching
  tables plus hypertables for `signals`, `annotations_apnea`, and
  `annotations_qrs`.

## Generated And Local Files

The following are intentionally ignored by git:

- `data/raw/`
- `data/processed/`
- `.env`
- local database dumps
- benchmark JSON, CSV, chart, and report outputs
- `exports/`

Use `docs/sprint2/RUNBOOK.md` for the most detailed operational checklist and
`docs/sprint2/IMPLEMENTATION_STATUS.md` for the current Sprint 2 status.
