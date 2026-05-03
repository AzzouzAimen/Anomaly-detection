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

### Move the Dataset into `data/raw`

```bash
mv physionet.org/files/apnea-ecg/1.0.0/* data/raw/
rm -rf physionet.org
```

### Organize the Dataset

After moving the files, run the organize script to structure the data:

```bash
python scripts/organize_dataset.py
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
