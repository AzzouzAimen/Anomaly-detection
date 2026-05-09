#!/usr/bin/env python3
"""Load Sprint 2 ETL outputs into PostgreSQL via docker exec + psql."""

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
    copy_rows_psql,
    iso_now,
    load_json,
    read_json_array,
    record_exists_in_signals,
    recording_ids_from_processed_dir,
    run_psql,
    sql_literal,
    write_summary_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_CONTAINER = "apnea_postgres"
DEFAULT_DATABASE = "apnea_db"
DEFAULT_USER = "user"
BATCH_SIZE = 100_000


def load_subjects(container: str, database: str, user: str, metadata: dict, record_ids: List[str]) -> int:
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

    values_sql = ", ".join(
        f"({sql_literal(subject_id)}, {sql_literal(notes)})"
        for subject_id, notes in subject_rows
    )
    run_psql(
        container,
        database,
        user,
        f"INSERT INTO subjects (subject_id, notes) VALUES {values_sql} ON CONFLICT (subject_id) DO NOTHING;",
    )
    return len(subject_rows)


def load_recordings(container: str, database: str, user: str, metadata: dict, record_ids: List[str]) -> int:
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

    values_sql = ", ".join(
        "(" + ", ".join(sql_literal(value) for value in row) + ")"
        for row in recording_rows
    )
    run_psql(
        container,
        database,
        user,
        (
            "INSERT INTO recordings ("
            "recording_id, subject_id, split, record_category, "
            "has_respiration, has_apnea_labels, source_record_name, "
            "sampling_rate_hz, length_seconds"
            ") VALUES "
            f"{values_sql} ON CONFLICT (recording_id) DO NOTHING;"
        ),
    )
    return len(recording_rows)


def load_signals(container: str, database: str, user: str, processed_dir: Path, record_ids: List[str]) -> int:
    total = 0
    for record_id in record_ids:
        # Skip if this record is already loaded
        if record_exists_in_signals(container, database, user, record_id):
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
                        row["recorded_at"],
                        row.get("ecg_value"),
                        row.get("resp_c"),
                        row.get("resp_a"),
                        row.get("resp_n"),
                        row.get("spo2"),
                    )
                )
                if len(batch) >= BATCH_SIZE:
                    total += copy_rows_psql(
                        container,
                        database,
                        user,
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
            total += copy_rows_psql(
                container,
                database,
                user,
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


def load_annotations(container: str, database: str, user: str, processed_dir: Path, record_ids: List[str], table_name: str) -> int:
    total = 0
    suffix = table_name.split('_', 1)[1]
    for record_id in record_ids:
        # Skip if this record already has annotations loaded
        if record_exists_in_signals(container, database, user, record_id):
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
                        row["recorded_at"],
                        row["label"],
                        bool(row["is_apnea"]),
                    )
                    for row in segment
                ]
                total += copy_rows_psql(
                    container,
                    database,
                    user,
                    "annotations_apnea",
                    ["recording_id", "minute_index", "recorded_at", "label", "is_apnea"],
                    batch,
                )
            else:
                batch = [
                    (
                        row["recording_id"],
                        int(row["sample_index"]),
                        row["recorded_at"],
                    )
                    for row in segment
                ]
                total += copy_rows_psql(
                    container,
                    database,
                    user,
                    "annotations_qrs",
                    ["recording_id", "sample_index", "recorded_at"],
                    batch,
                )

    return total


def cleanup_existing_records(container: str, database: str, user: str, metadata: dict, record_ids: List[str]) -> None:
    if not record_ids:
        return

    record_list = ", ".join(sql_literal(record_id) for record_id in record_ids)
    subject_ids = sorted({metadata[record_id]["subject_id"] for record_id in record_ids})
    subject_list = ", ".join(sql_literal(subject_id) for subject_id in subject_ids)

    run_psql(container, database, user, f"DELETE FROM signals WHERE recording_id IN ({record_list});")
    run_psql(container, database, user, f"DELETE FROM annotations_apnea WHERE recording_id IN ({record_list});")
    run_psql(container, database, user, f"DELETE FROM annotations_qrs WHERE recording_id IN ({record_list});")
    run_psql(container, database, user, f"DELETE FROM recordings WHERE recording_id IN ({record_list});")
    if subject_ids:
        run_psql(
            container,
            database,
            user,
            (
                "DELETE FROM subjects s "
                f"WHERE s.subject_id IN ({subject_list}) "
                "AND NOT EXISTS (SELECT 1 FROM recordings r WHERE r.subject_id = s.subject_id);"
            ),
        )


def run_load(
    processed_dir: Path,
    record_ids: Optional[List[str]] = None,
    container: str = DEFAULT_CONTAINER,
    database: str = DEFAULT_DATABASE,
    user: str = DEFAULT_USER,
    skip_cleanup: bool = False,
) -> DatabaseLoadSummary:
    processed_dir = Path(processed_dir)
    metadata = load_json(Path("data/metadata/dataset_baseline.json"))
    if record_ids is None:
        record_ids = recording_ids_from_processed_dir(processed_dir)

    start = iso_now()
    stats: List[IngestionStats] = []

    if not skip_cleanup:
        stage_start = time.perf_counter()
        cleanup_existing_records(container, database, user, metadata, record_ids)
        stats.append(IngestionStats("cleanup", len(record_ids), time.perf_counter() - stage_start))
        
        stage_start = time.perf_counter()
        subjects_rows = load_subjects(container, database, user, metadata, record_ids)
        stats.append(IngestionStats("subjects", subjects_rows, time.perf_counter() - stage_start))

        stage_start = time.perf_counter()
        recording_rows = load_recordings(container, database, user, metadata, record_ids)
        stats.append(IngestionStats("recordings", recording_rows, time.perf_counter() - stage_start))
    else:
        logger.info("Skipping cleanup and metadata phases - resuming signal/annotation loading only")
        stats.append(IngestionStats("cleanup", 0, 0))
        stats.append(IngestionStats("subjects", 0, 0))
        stats.append(IngestionStats("recordings", 0, 0))

    stage_start = time.perf_counter()
    signal_rows = load_signals(container, database, user, processed_dir, record_ids)
    stats.append(IngestionStats("signals", signal_rows, time.perf_counter() - stage_start))

    stage_start = time.perf_counter()
    apnea_rows = load_annotations(container, database, user, processed_dir, record_ids, "annotations_apnea")
    stats.append(IngestionStats("annotations_apnea", apnea_rows, time.perf_counter() - stage_start))

    stage_start = time.perf_counter()
    qrs_rows = load_annotations(container, database, user, processed_dir, record_ids, "annotations_qrs")
    stats.append(IngestionStats("annotations_qrs", qrs_rows, time.perf_counter() - stage_start))

    end = iso_now()
    summary = DatabaseLoadSummary(
        database_name="postgresql",
        source_dir=str(processed_dir),
        start_time=start,
        end_time=end,
        stats=stats,
    )
    write_summary_json(Path("database/postgresql/ingestion_log.json"), summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Load ETL outputs into PostgreSQL.")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--record", action="append", dest="records", help="Optional record filter.")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup phase and resume from last checkpoint")
    args = parser.parse_args()

    summary = run_load(
        Path(args.processed_dir),
        args.records,
        container=args.container,
        database=args.database,
        user=args.user,
        skip_cleanup=args.skip_cleanup,
    )
    logger.info("Loaded PostgreSQL data: %s", summary.to_dict())


if __name__ == "__main__":
    main()
