#!/usr/bin/env python3
"""Validate processed Sprint 2 ETL outputs against metadata and transformation logs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


WINDOW_DURATION_SECONDS = 60


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def infer_records(processed_dir: Path, transformation_summary: Optional[dict] = None) -> List[str]:
    record_ids = set()
    for path in processed_dir.glob("signals_*.jsonl"):
        record_ids.add(path.stem.replace("signals_", ""))
    for path in processed_dir.glob("apnea_*.json"):
        record_ids.add(path.stem.replace("apnea_", ""))
    for path in processed_dir.glob("qrs_*.json"):
        record_ids.add(path.stem.replace("qrs_", ""))

    if record_ids:
        return sorted(record_ids)

    if transformation_summary:
        for item in transformation_summary.get("records", []):
            record_name = item.get("record_name")
            if record_name:
                record_ids.add(record_name)

    return sorted(record_ids)


def load_existing_record_reports(processed_dir: Path) -> Dict[str, Dict[str, Any]]:
    validation_report_path = processed_dir / "validation_report.json"
    if not validation_report_path.exists():
        return {}

    payload = load_json(validation_report_path)
    return {
        record_report["record_id"]: record_report
        for record_report in payload.get("records", [])
        if record_report.get("record_id")
    }


def record_artifacts_exist(processed_dir: Path, record_id: str) -> bool:
    return any(
        (processed_dir / file_name).exists()
        for file_name in (
            f"signals_{record_id}.jsonl",
            f"apnea_{record_id}.json",
            f"qrs_{record_id}.json",
            f"windows_{record_id}.json",
        )
    )


def expected_signal_rows(record_meta: dict, transformation_summary: Optional[dict]) -> int:
    if transformation_summary:
        for item in transformation_summary.get("records", []):
            if item.get("record_name") == record_meta["record_name"]:
                return int(item.get("expected_samples", record_meta["num_samples"]))
    return int(record_meta["num_samples"])


def validate_signals(path: Path, record_meta: dict, expected_rows: int) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    total_rows = 0
    last_sample_index = None
    last_timestamp = None
    first_timestamp = None
    respiration_seen = False
    non_respiration_null_violation = False

    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            total_rows += 1
            sample_index = int(payload["sample_index"])
            timestamp = parse_timestamp(payload["recorded_at"])
            if first_timestamp is None:
                first_timestamp = payload["recorded_at"]

            if last_sample_index is not None and sample_index != last_sample_index + 1:
                issues.append(f"sample_index gap at row {total_rows}: {last_sample_index} -> {sample_index}")
            if last_timestamp is not None and timestamp <= last_timestamp:
                issues.append(f"non-increasing timestamp at row {total_rows}")

            resp_values = [payload.get("resp_c"), payload.get("resp_a"), payload.get("resp_n"), payload.get("spo2")]
            if any(value is not None for value in resp_values):
                respiration_seen = True
            if not record_meta["has_respiration"] and any(value is not None for value in resp_values):
                non_respiration_null_violation = True

            last_sample_index = sample_index
            last_timestamp = timestamp

    if total_rows != expected_rows:
        issues.append(f"signal row count mismatch: expected {expected_rows}, found {total_rows}")
    if record_meta["has_respiration"] and not respiration_seen:
        warnings.append("record metadata says respiration exists but all respiration values are NULL")
    if non_respiration_null_violation:
        issues.append("ECG-only record contains non-NULL respiration values")

    return {
        "path": str(path),
        "row_count": total_rows,
        "expected_row_count": expected_rows,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp.isoformat() if last_timestamp else None,
        "issues": issues,
        "warnings": warnings,
    }


def validate_annotation_file(path: Path, expected_present: bool, key_name: str) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    if not path.exists():
        if expected_present:
            issues.append(f"missing required file: {path.name}")
        return {
            "path": str(path),
            "row_count": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "issues": issues,
            "warnings": warnings,
        }

    rows = load_json(path)
    last_timestamp = None
    last_index = None
    for row_number, row in enumerate(rows, start=1):
        timestamp = parse_timestamp(row["recorded_at"])
        index_value = int(row[key_name])
        if last_timestamp is not None and timestamp < last_timestamp:
            issues.append(f"non-monotonic timestamp in {path.name} at row {row_number}")
        if last_index is not None and index_value < last_index:
            issues.append(f"non-monotonic {key_name} in {path.name} at row {row_number}")
        last_timestamp = timestamp
        last_index = index_value

    if expected_present and not rows:
        warnings.append(f"expected annotations in {path.name} but file is empty")

    return {
        "path": str(path),
        "row_count": len(rows),
        "first_timestamp": rows[0]["recorded_at"] if rows else None,
        "last_timestamp": rows[-1]["recorded_at"] if rows else None,
        "issues": issues,
        "warnings": warnings,
    }


def validate_windows(path: Path, record_meta: dict, expected_signal_rows: int) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    if not path.exists():
        return {
            "path": str(path),
            "row_count": 0,
            "expected_row_count": 0,
            "issues": [f"missing required file: {path.name}"],
            "warnings": warnings,
        }

    rows = load_json(path)
    last_minute_index = None
    labeled_windows = 0
    respiration_available = False
    expected_rows = (expected_signal_rows + (record_meta["sampling_rate_hz"] * WINDOW_DURATION_SECONDS) - 1) // (
        record_meta["sampling_rate_hz"] * WINDOW_DURATION_SECONDS
    )

    for row_number, row in enumerate(rows, start=1):
        minute_index = int(row["minute_index"])
        if last_minute_index is not None and minute_index <= last_minute_index:
            issues.append(f"non-increasing minute_index in {path.name} at row {row_number}")
        last_minute_index = minute_index

        if row.get("apnea_label") is not None:
            labeled_windows += 1

        modalities = row.get("modalities", {})
        if any(bool(modalities.get(key, {}).get("available")) for key in ("resp_c", "resp_a", "resp_n", "spo2")):
            respiration_available = True

    if len(rows) != expected_rows:
        issues.append(f"window row count mismatch: expected {expected_rows}, found {len(rows)}")
    if record_meta["has_apnea_annotations"] and labeled_windows == 0 and len(rows) > 0:
        warnings.append("learning record has no labeled windows")
    if not record_meta["has_apnea_annotations"] and labeled_windows > 0:
        issues.append("test record contains apnea labels in window output")
    if record_meta["has_respiration"] and not respiration_available:
        warnings.append("multimodal record windows do not advertise respiration availability")
    if not record_meta["has_respiration"] and respiration_available:
        issues.append("ECG-only record windows advertise respiration availability")

    return {
        "path": str(path),
        "row_count": len(rows),
        "expected_row_count": expected_rows,
        "labeled_windows": labeled_windows,
        "issues": issues,
        "warnings": warnings,
    }


def classify_record(report: Dict[str, Any]) -> str:
    has_issues = any(report[section]["issues"] for section in ("signals", "apnea", "qrs", "windows"))
    has_warnings = any(report[section]["warnings"] for section in ("signals", "apnea", "qrs", "windows"))
    if has_issues:
        return "fail"
    if has_warnings:
        return "warn"
    return "pass"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate processed ETL outputs for Sprint 2.")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--metadata", default="data/metadata/dataset_baseline.json")
    parser.add_argument("--record", action="append", dest="records")
    parser.add_argument("--output", default=None, help="Defaults to <processed-dir>/validation_report.json")
    args = parser.parse_args()

    processed_dir = Path(args.processed_dir)
    metadata = load_json(Path(args.metadata))
    transformation_summary_path = processed_dir / "transformation_summary.json"
    transformation_summary = load_json(transformation_summary_path) if transformation_summary_path.exists() else None
    cleaning_log_path = processed_dir / "cleaning_transformation_log.md"
    existing_record_reports = load_existing_record_reports(processed_dir)
    records = args.records or infer_records(processed_dir, transformation_summary)

    results = []
    for record_id in records:
        if not record_artifacts_exist(processed_dir, record_id):
            existing_record_report = existing_record_reports.get(record_id)
            if existing_record_report is not None:
                results.append(existing_record_report)
                continue

        record_meta = metadata[record_id]
        signals_path = processed_dir / f"signals_{record_id}.jsonl"
        apnea_path = processed_dir / f"apnea_{record_id}.json"
        qrs_path = processed_dir / f"qrs_{record_id}.json"
        windows_path = processed_dir / f"windows_{record_id}.json"
        expected_rows = expected_signal_rows(record_meta, transformation_summary)
        record_report = {
            "record_id": record_id,
            "signals": validate_signals(
                signals_path,
                record_meta,
                expected_rows,
            ) if signals_path.exists() else {
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
        record_report["status"] = classify_record(record_report)
        results.append(record_report)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "processed_dir": str(processed_dir),
        "cleaning_log_present": cleaning_log_path.exists(),
        "record_count": len(results),
        "status_counts": {
            "pass": sum(1 for result in results if result["status"] == "pass"),
            "warn": sum(1 for result in results if result["status"] == "warn"),
            "fail": sum(1 for result in results if result["status"] == "fail"),
        },
        "records": results,
    }

    output_path = Path(args.output) if args.output else processed_dir / "validation_report.json"
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(f"Validation report written to {output_path}")


if __name__ == "__main__":
    main()
