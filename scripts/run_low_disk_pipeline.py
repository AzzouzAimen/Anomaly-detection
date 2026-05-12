#!/usr/bin/env python3
"""Run a low-disk Sprint 2 pipeline by staging one record at a time."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from etl_pipeline import (
    ExtractionStats,
    build_cleaning_log_markdown,
    build_transformation_summary,
    load_metadata,
    process_record,
    serialize_dataclass,
)
from ingest_common import DatabaseLoadSummary, IngestionStats, write_summary_json
from ingest_postgresql import run_load as run_postgresql_load
from ingest_timescaledb import run_load as run_timescaledb_load
from validate_etl import (
    classify_record,
    expected_signal_rows,
    validate_annotation_file,
    validate_signals,
    validate_windows,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def build_record_validation_report(
    staging_dir: Path,
    metadata: dict,
    record_id: str,
    transformation_summary: dict,
) -> dict:
    record_meta = metadata[record_id]
    expected_rows = expected_signal_rows(record_meta, transformation_summary)
    signals_path = staging_dir / f"signals_{record_id}.jsonl"
    apnea_path = staging_dir / f"apnea_{record_id}.json"
    qrs_path = staging_dir / f"qrs_{record_id}.json"
    windows_path = staging_dir / f"windows_{record_id}.json"

    report = {
        "record_id": record_id,
        "signals": validate_signals(signals_path, record_meta, expected_rows)
        if signals_path.exists()
        else {
            "path": str(signals_path),
            "row_count": 0,
            "expected_row_count": expected_rows,
            "first_timestamp": None,
            "last_timestamp": None,
            "issues": [f"missing required file: {signals_path.name}"],
            "warnings": [],
        },
        "apnea": validate_annotation_file(apnea_path, bool(record_meta["has_apnea_annotations"]), "minute_index"),
        "qrs": validate_annotation_file(qrs_path, bool(record_meta["has_qrs_annotations"]), "sample_index"),
        "windows": validate_windows(windows_path, record_meta, expected_rows),
    }
    report["status"] = classify_record(report)
    return report


def build_validation_summary(output_root: Path, reports: List[dict]) -> dict:
    return {
        "generated_at": utc_now_iso(),
        "processed_dir": str(output_root),
        "cleaning_log_present": (output_root / "cleaning_transformation_log.md").exists(),
        "record_count": len(reports),
        "status_counts": {
            "pass": sum(1 for report in reports if report["status"] == "pass"),
            "warn": sum(1 for report in reports if report["status"] == "warn"),
            "fail": sum(1 for report in reports if report["status"] == "fail"),
        },
        "records": reports,
    }


def persistable_validation_report(report: dict, keep_staging: bool) -> dict:
    persisted = json.loads(json.dumps(report))
    if keep_staging:
        return persisted

    for section_name in ("signals", "apnea", "qrs", "windows"):
        section = persisted.get(section_name)
        if not isinstance(section, dict):
            continue

        source_path = section.get("path")
        if source_path:
            section["source_path"] = source_path
        section["path"] = None
        section["artifact_retained"] = False

    return persisted


def merge_load_summaries(
    database_name: str,
    source_dir: Path,
    summaries: List[DatabaseLoadSummary],
) -> DatabaseLoadSummary:
    aggregated: Dict[str, IngestionStats] = {}
    order: List[str] = []
    for summary in summaries:
        for stat in summary.stats:
            if stat.table not in aggregated:
                aggregated[stat.table] = IngestionStats(stat.table, 0, 0.0)
                order.append(stat.table)
            aggregated[stat.table].rows_inserted += stat.rows_inserted
            aggregated[stat.table].duration_sec += stat.duration_sec

    return DatabaseLoadSummary(
        database_name=database_name,
        source_dir=str(source_dir),
        start_time=summaries[0].start_time if summaries else utc_now_iso(),
        end_time=summaries[-1].end_time if summaries else utc_now_iso(),
        stats=[aggregated[table_name] for table_name in order],
    )


def write_cumulative_outputs(
    output_root: Path,
    metadata: dict,
    records: List[str],
    stats_list: List[ExtractionStats],
    validation_reports: List[dict],
    max_samples: int | None,
    postgres_summaries: List[DatabaseLoadSummary],
    timescale_summaries: List[DatabaseLoadSummary],
    keep_staging: bool,
) -> None:
    write_json(
        output_root / "extraction_stats.json",
        [serialize_dataclass(stat) for stat in stats_list],
    )

    transformation_summary = build_transformation_summary(metadata, records, stats_list, max_samples)
    write_json(output_root / "transformation_summary.json", transformation_summary)
    with open(output_root / "cleaning_transformation_log.md", "w", encoding="utf-8") as handle:
        handle.write(build_cleaning_log_markdown(transformation_summary))

    persisted_reports = [persistable_validation_report(report, keep_staging) for report in validation_reports]
    validation_summary = build_validation_summary(output_root, persisted_reports)
    write_json(output_root / "validation_report.json", validation_summary)

    if postgres_summaries:
        write_summary_json(
            output_root / "postgresql_ingestion_log.json",
            merge_load_summaries("postgresql", output_root, postgres_summaries),
        )

    if timescale_summaries:
        write_summary_json(
            output_root / "timescaledb_ingestion_log.json",
            merge_load_summaries("timescaledb", output_root, timescale_summaries),
        )


def write_single_record_artifacts(
    staging_dir: Path,
    metadata: dict,
    record_id: str,
    stats: ExtractionStats,
    max_samples: int | None,
) -> tuple[dict, dict]:
    transformation_summary = build_transformation_summary(metadata, [record_id], [stats], max_samples)
    write_json(staging_dir / "extraction_stats.json", [serialize_dataclass(stats)])
    write_json(staging_dir / "transformation_summary.json", transformation_summary)
    with open(staging_dir / "cleaning_transformation_log.md", "w", encoding="utf-8") as handle:
        handle.write(build_cleaning_log_markdown(transformation_summary))

    validation_report = build_record_validation_report(staging_dir, metadata, record_id, transformation_summary)
    write_json(
        staging_dir / "validation_report.json",
        {
            "generated_at": utc_now_iso(),
            "processed_dir": str(staging_dir),
            "cleaning_log_present": True,
            "record_count": 1,
            "status_counts": {
                validation_report["status"]: 1,
                **{status: 0 for status in ("pass", "warn", "fail") if status != validation_report["status"]},
            },
            "records": [validation_report],
        },
    )
    return transformation_summary, validation_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the low-disk Sprint 2 ETL -> validate -> dual-ingest pipeline.")
    parser.add_argument("--record", action="append", dest="records", help="Optional record filter. Repeat for multiple records.")
    parser.add_argument("--output-root", default="data/processed", help="Directory for cumulative outputs and transient staging.")
    parser.add_argument("--max-samples", type=int, default=None, help="Optional cap on signal samples per record.")
    parser.add_argument("--keep-staging", action="store_true", help="Keep per-record staging directories after successful dual-ingest.")
    parser.add_argument(
        "--compress-after-load",
        action="store_true",
        help="Pass through to the TimescaleDB loader for immediate compression after each record load.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = load_metadata()
    records = args.records or sorted(metadata.keys())

    invalid = [record_id for record_id in records if record_id not in metadata]
    if invalid:
        raise SystemExit(f"Unknown record(s): {invalid}")

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    staging_root = output_root / "_staging"
    staging_root.mkdir(parents=True, exist_ok=True)

    processed_records: List[str] = []
    stats_list: List[ExtractionStats] = []
    validation_reports: List[dict] = []
    postgres_summaries: List[DatabaseLoadSummary] = []
    timescale_summaries: List[DatabaseLoadSummary] = []

    for record_id in records:
        staging_dir = staging_root / record_id
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Processing low-disk stage for %s", record_id)

        try:
            stats = process_record(record_id, metadata, staging_dir, max_samples=args.max_samples)
            if stats.errors:
                raise RuntimeError(f"ETL failed for {record_id}: {'; '.join(stats.errors)}")

            _, validation_report = write_single_record_artifacts(
                staging_dir,
                metadata,
                record_id,
                stats,
                args.max_samples,
            )
            if validation_report["status"] == "fail":
                raise RuntimeError(f"Validation failed for {record_id}; preserved staging at {staging_dir}")

            postgres_summary = run_postgresql_load(
                staging_dir,
                [record_id],
                summary_output_path=staging_dir / "postgresql_ingestion_log.json",
            )
            timescale_summary = run_timescaledb_load(
                staging_dir,
                [record_id],
                compress_after_load=args.compress_after_load,
                summary_output_path=staging_dir / "timescaledb_ingestion_log.json",
            )
        except Exception as error:
            logger.error("Low-disk pipeline stopped at %s. Preserved staging in %s", record_id, staging_dir)
            raise SystemExit(str(error)) from None

        processed_records.append(record_id)
        stats_list.append(stats)
        validation_reports.append(validation_report)
        postgres_summaries.append(postgres_summary)
        timescale_summaries.append(timescale_summary)

        write_cumulative_outputs(
            output_root,
            metadata,
            processed_records,
            stats_list,
            validation_reports,
            args.max_samples,
            postgres_summaries,
            timescale_summaries,
            args.keep_staging,
        )

        if not args.keep_staging:
            shutil.rmtree(staging_dir)
            logger.info("Removed staging directory for %s", record_id)

    logger.info("Low-disk pipeline complete for %s record(s)", len(processed_records))


if __name__ == "__main__":
    main()