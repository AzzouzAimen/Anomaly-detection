# Structured Repository Package

This directory contains the Sprint 2 export manifest and, when exports are executed, database dump artifacts for the cleaned and windowed dataset state.

## Package Contents

- `export_manifest.json`: machine-readable export metadata
- `postgresql/` and `timescaledb/`: dump output directories when `--execute` is used

## Access And Reproduction

Use the repository `.env` or `.env.example` values to match the database names, users, and container names below.

| Database | Container | DB Name | User | Mode | Output |
| --- | --- | --- | --- | --- | --- |
| postgresql | apnea_postgres | apnea_db | apnea_pg_user | full | exports/postgresql/postgresql_full.dump |
| timescaledb | apnea_timescaledb | apnea_ts_db | apnea_ts_user | full | exports/timescaledb/timescaledb_full.dump |

## Notes

- Export artifacts are intentionally generated outside Git because full dumps can be large.
- The manifest is still useful even when exports are not executed because it records the exact dump commands and target locations.
- These exports should be regenerated after the final Sprint 2 ETL, ingestion, and benchmarking cycle so they match the same cleaned/windowed dataset state.