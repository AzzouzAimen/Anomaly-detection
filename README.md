# Respiratory Apnea Detection (Apnea-ECG)

## Project Overview

This project builds a medical time-series benchmark dataset for respiratory apnea detection using the PhysioNet Apnea-ECG database.

## Dataset

- Source: PhysioNet Apnea-ECG
- 70 recordings (~8 hours each)
- ECG signals + apnea annotations

## Structure

```
data/
├── raw/       # original PhysioNet data (not tracked)
└── metadata/  # generated metadata
scripts/       # ETL + processing scripts
database/      # DB schemas
docs/          # reports
```

## Setup

### Start Database

```bash
docker compose up -d
```

### Team Workflow

1. Pull repo
2. Download dataset locally or in Codespaces
3. Run scripts from `/scripts`

### Download Dataset

```bash
wget -r -N -c -np https://physionet.org/files/apnea-ecg/1.0.0/
```

This will create a nested folder like:

```
physionet.org/files/apnea-ecg/1.0.0/
```

### Organize the Dataset

run the organize script to structure the data:

```bash
python scripts/organize_dataset.py
```

### Preview Data Files

Use the preview helper to inspect headers/annotations and optionally load signals:

```bash
python scripts/preview_data.py --record a01
```

Optional dependencies for signal loading and plotting:

```bash
pip install wfdb matplotlib
```

### Create a `.env` File

```env
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=apnea_db
POSTGRES_PORT=5432
TIMESCALE_USER=user
TIMESCALE_PASSWORD=password
TIMESCALE_DB=apnea_ts_db
TIMESCALE_PORT=5433
```

### 📌 Summary: Apnea-ECG Dataset Quirks & Strategy

Keep these 4 points pinned; they dictate your entire database design:

1. **The Frequency Mismatch (100Hz vs 1-Minute):** Your ECG data has 100 rows per second (6,000 rows per minute). Your Apnea annotations (`.apn`) only have **1 label per minute**. You cannot just put them in the same table row. You will need separate tables for `Signals` and `Annotations`.
2. **Missing Modalities (The 8 vs 62 split):** 62 records _only_ have ECG data. Only 8 records (`a01` to `a04`, `b01`, `c01` to `c03`) have the extra respiration signals (`Resp C`, `Resp A`, `Resp N`, `SpO2`). **Strategy:** Your database schema should include columns for these respiratory signals, but you will insert `NULL` for the 62 records that don't have them. This proves you know how to handle real-world sparse medical data.
3. **Massive Data Volume:** 70 records × ~8 hours × 60 mins × 60 secs × 100 Hz = **~120 Million rows**. This is why you need TimescaleDB. Standard PostgreSQL will choke on queries over 120M rows; TimescaleDB will handle it easily using "Hypertables".
4. **No "Real" Dates:** The records don't have real calendar dates (like `2023-10-25 14:00`). To use Time-Series databases effectively, you should assign a "fake" baseline start date to all records (e.g., `2000-01-01 00:00:00.000`) and add the elapsed milliseconds to it for your timestamp columns.
