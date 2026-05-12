#!/usr/bin/env python3
"""Load Sprint 2 ETL outputs into PostgreSQL via direct psycopg2 connection."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from ingest_common import (
    DatabaseLoadSummary,
    IngestionStats,
    connect_db,
    copy_rows,
    env_default,
    iso_now,
    insert_values,
    load_json,
    parse_timestamp,
    record_exists_in_apnea_annotations,
    record_exists_in_qrs_annotations,
    read_json_array,
    record_exists_in_signals,
    recording_ids_from_processed_dir,
    run_sql,
    write_summary_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_HOST = env_default("POSTGRES_HOST", "127.0.0.1")
DEFAULT_PORT = int(env_default("POSTGRES_PORT", "5432"))
DEFAULT_DATABASE = env_default("POSTGRES_DB", "apnea_db")
DEFAULT_USER = env_default("POSTGRES_USER", "user")
DEFAULT_PASSWORD = env_default("POSTGRES_PASSWORD", "password")
BATCH_SIZE = 100_000
POSTGRES_AUTH_HELP = (
    "Verify POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD or pass "
    "explicit --host/--port/--database/--user/--password arguments to the loader."
)


def load_subjects(connection, metadata: dict, record_ids: List[str]) -> int:
    subject_rows = []
    seen_subjects = set()

    for record_id in record_ids:
        record_meta = metadata[record_id]
        subject_id = record_meta["subject_id"]
        if subject_id in seen_subjects:
            continue
        seen_subjects.add(subject_id)
        subject_rows.append((subject_id, f"Derived from {record_id}"))

    if not subject_rows:
        return 0

    return insert_values(
        connection,
        "INSERT INTO subjects (subject_id, notes) VALUES %s ON CONFLICT (subject_id) DO NOTHING;",
        subject_rows,
    )


def load_recordings(connection, metadata: dict, record_ids: List[str]) -> int:
    recording_rows = []
    for record_id in record_ids:
        record_meta = metadata[record_id]
        recording_rows.append(
            (
                record_meta["record_name"],
                record_meta["subject_id"],
                record_meta["split"],
                record_meta["category"],
                bool(record_meta["has_respiration"]),
                bool(record_meta["has_apnea_annotations"]),
                record_meta["source_record_name"],
                int(record_meta["sampling_rate_hz"]),
                int(record_meta["length_seconds"]),
            )
        )

    if not recording_rows:
        return 0

    return insert_values(
        connection,
        (
            "INSERT INTO recordings ("
            "recording_id, subject_id, split, record_category, "
            "has_respiration, has_apnea_labels, source_record_name, "
            "sampling_rate_hz, length_seconds"
            ") VALUES %s ON CONFLICT (recording_id) DO NOTHING;"
        ),
        recording_rows,
    )


def load_signals(connection, processed_dir: Path, record_ids: List[str]) -> int:
    total = 0
    for record_id in record_ids:
        if record_exists_in_signals(connection, record_id):
            logger.info(f"Record {record_id} already loaded, skipping signals")
            continue
        
        path = processed_dir / f"signals_{record_id}.jsonl"
        if not path.exists():
            logger.warning("Missing signals file for %s", record_id)
            continue

        batch = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                batch.append(
                    (
                        row["recording_id"],
                        int(row["sample_index"]),
                        parse_timestamp(row["recorded_at"]),
                        row.get("ecg_value"),
                        row.get("resp_c"),
                        row.get("resp_a"),
                        row.get("resp_n"),
                        row.get("spo2"),
                    )
                )
                if len(batch) >= BATCH_SIZE:
                    total += copy_rows(
                        connection,
                        "signals",
                        [
                            "recording_id",
                            "sample_index",
                            "recorded_at",
                            "ecg_value",
                            "resp_c",
                            "resp_a",
                            "resp_n",
                            "spo2",
                        ],
                        batch,
                    )
                    batch.clear()

        if batch:
            total += copy_rows(
                connection,
                "signals",
                [
                    "recording_id",
                    "sample_index",
                    "recorded_at",
                    "ecg_value",
                    "resp_c",
                    "resp_a",
                    "resp_n",
                    "spo2",
                ],
                batch,
            )

    return total


def load_annotations(connection, processed_dir: Path, record_ids: List[str], table_name: str) -> int:
    total = 0
    suffix = table_name.split('_', 1)[1]
    for record_id in record_ids:
        if table_name == "annotations_apnea":
            already_loaded = record_exists_in_apnea_annotations(connection, record_id)
        else:
            already_loaded = record_exists_in_qrs_annotations(connection, record_id)

        if already_loaded:
            logger.info(f"Record {record_id} already has data, skipping {table_name}")
            continue
        
        path = processed_dir / f"{suffix}_{record_id}.json"
        if not path.exists():
            logger.warning("Missing %s file for %s", table_name, record_id)
            continue

        rows = read_json_array(path)
        for start in range(0, len(rows), BATCH_SIZE):
            segment = rows[start:start + BATCH_SIZE]
            if table_name == "annotations_apnea":
                batch = [
                    (
                        row["recording_id"],
                        int(row["minute_index"]),
                        parse_timestamp(row["recorded_at"]),
                        row["label"],
                        bool(row["is_apnea"]),
                    )
                    for row in segment
                ]
                total += copy_rows(
                    connection,
                    "annotations_apnea",
                    ["recording_id", "minute_index", "recorded_at", "label", "is_apnea"],
                    batch,
                )
            else:
                batch = [
                    (
                        row["recording_id"],
                        int(row["sample_index"]),
                        parse_timestamp(row["recorded_at"]),
                    )
                    for row in segment
                ]
                total += copy_rows(
                    connection,
                    "annotations_qrs",
                    ["recording_id", "sample_index", "recorded_at"],
                    batch,
                )

    return total


def cleanup_existing_records(connection, metadata: dict, record_ids: List[str]) -> None:
    if not record_ids:
        return

    subject_ids = sorted({metadata[record_id]["subject_id"] for record_id in record_ids})

    run_sql(connection, "DELETE FROM signals WHERE recording_id = ANY(%s);", (record_ids,))
    run_sql(connection, "DELETE FROM annotations_apnea WHERE recording_id = ANY(%s);", (record_ids,))
    run_sql(connection, "DELETE FROM annotations_qrs WHERE recording_id = ANY(%s);", (record_ids,))
    run_sql(connection, "DELETE FROM recordings WHERE recording_id = ANY(%s);", (record_ids,))
    if subject_ids:
        run_sql(
            connection,
            (
                "DELETE FROM subjects s "
                "WHERE s.subject_id = ANY(%s) "
                "AND NOT EXISTS (SELECT 1 FROM recordings r WHERE r.subject_id = s.subject_id);"
            ),
            (subject_ids,),
        )


def run_load(
    processed_dir: Path,
    record_ids: Optional[List[str]] = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    database: str = DEFAULT_DATABASE,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    skip_cleanup: bool = False,
    summary_output_path: Path | None = None,
) -> DatabaseLoadSummary:
    processed_dir = Path(processed_dir)
    metadata = load_json(Path("data/metadata/dataset_baseline.json"))
    if record_ids is None:
        record_ids = recording_ids_from_processed_dir(processed_dir)

    connection = connect_db(
        host,
        port,
        database,
        user,
        password,
        database_label="PostgreSQL",
        auth_help=POSTGRES_AUTH_HELP,
    )

    start = iso_now()
    stats: List[IngestionStats] = []

    try:
        if not skip_cleanup:
            stage_start = time.perf_counter()
            cleanup_existing_records(connection, metadata, record_ids)
            connection.commit()
            stats.append(IngestionStats("cleanup", len(record_ids), time.perf_counter() - stage_start))
        else:
            logger.info("Skipping cleanup phase - resuming with idempotent metadata and data loads")
            stats.append(IngestionStats("cleanup", 0, 0))

        stage_start = time.perf_counter()
        subjects_rows = load_subjects(connection, metadata, record_ids)
        connection.commit()
        stats.append(IngestionStats("subjects", subjects_rows, time.perf_counter() - stage_start))

        stage_start = time.perf_counter()
        recording_rows = load_recordings(connection, metadata, record_ids)
        connection.commit()
        stats.append(IngestionStats("recordings", recording_rows, time.perf_counter() - stage_start))

        stage_start = time.perf_counter()
        signal_rows = load_signals(connection, processed_dir, record_ids)
        connection.commit()
        stats.append(IngestionStats("signals", signal_rows, time.perf_counter() - stage_start))

        stage_start = time.perf_counter()
        apnea_rows = load_annotations(connection, processed_dir, record_ids, "annotations_apnea")
        connection.commit()
        stats.append(IngestionStats("annotations_apnea", apnea_rows, time.perf_counter() - stage_start))

        stage_start = time.perf_counter()
        qrs_rows = load_annotations(connection, processed_dir, record_ids, "annotations_qrs")
        connection.commit()
        stats.append(IngestionStats("annotations_qrs", qrs_rows, time.perf_counter() - stage_start))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    end = iso_now()
    summary = DatabaseLoadSummary(
        database_name="postgresql",
        source_dir=str(processed_dir),
        start_time=start,
        end_time=end,
        stats=stats,
    )
    write_summary_json(summary_output_path or Path("database/postgresql/ingestion_log.json"), summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Load ETL outputs into PostgreSQL.")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--record", action="append", dest="records", help="Optional record filter.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup phase and resume from last checkpoint")
    args = parser.parse_args()

    try:
        summary = run_load(
            Path(args.processed_dir),
            args.records,
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            skip_cleanup=args.skip_cleanup,
        )
    except RuntimeError as error:
        logger.error(str(error))
        raise SystemExit(1) from None

    logger.info("Loaded PostgreSQL data: %s", summary.to_dict())


if __name__ == "__main__":
    main()
