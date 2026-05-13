#!/usr/bin/env python3
"""Refresh benchmark storage metrics without rerunning latency benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from benchmark_suite import build_db_configs, connect_db, now_utc_iso, run_scalar
from generate_benchmark_report import (
    build_markdown,
    format_bytes,
    render_compression_chart,
    render_latency_chart,
    render_storage_chart,
    render_throughput_chart,
    write_latency_csv,
    write_storage_csv,
    write_throughput_csv,
)


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def read_current_storage(db) -> Dict[str, int]:
    connection = connect_db(db)
    try:
        if db.is_timescale:
            signals_bytes = int(run_scalar(connection, "SELECT hypertable_size('signals');") or 0)
        else:
            signals_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('signals');") or 0)

        apnea_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('annotations_apnea');") or 0)
        qrs_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('annotations_qrs');") or 0)
    finally:
        connection.close()

    return {
        "signals_bytes": signals_bytes,
        "annotations_apnea_bytes": apnea_bytes,
        "annotations_qrs_bytes": qrs_bytes,
        "total_bytes": signals_bytes + apnea_bytes + qrs_bytes,
    }


def merge_timescale_storage(existing: Dict[str, Any], current: Dict[str, int]) -> Dict[str, Any]:
    pre_signals_bytes = int(existing.get("signals_bytes_pre_compression") or current["signals_bytes"])
    pre_total_bytes = int(existing.get("total_bytes_pre_compression") or current["total_bytes"])

    merged = dict(existing)
    merged.update(current)
    merged["signals_bytes_post_compression"] = current["signals_bytes"]
    merged["total_bytes_post_compression"] = current["total_bytes"]
    merged["signals_bytes_pre_compression"] = pre_signals_bytes
    merged["total_bytes_pre_compression"] = pre_total_bytes
    merged["signals_compression_ratio"] = (
        pre_signals_bytes / current["signals_bytes"] if current["signals_bytes"] > 0 else None
    )
    merged["total_compression_ratio"] = pre_total_bytes / current["total_bytes"] if current["total_bytes"] > 0 else None
    return merged


def refresh_database_summary(summary_path: Path, db) -> Dict[str, Any]:
    summary = load_json(summary_path)
    current_storage = read_current_storage(db)
    if db.is_timescale:
        summary["storage"] = merge_timescale_storage(summary.get("storage") or {}, current_storage)
    else:
        summary["storage"] = current_storage

    summary["storage_refreshed_at"] = now_utc_iso()
    write_json(summary_path, summary)
    return summary


def regenerate_report(summary: Dict[str, Any], output_dir: Path) -> None:
    postgres = summary["postgresql"]
    timescale = summary["timescaledb"]

    output_dir.mkdir(parents=True, exist_ok=True)
    latency_csv = output_dir / "latency_summary.csv"
    storage_csv = output_dir / "storage_summary.csv"
    throughput_csv = output_dir / "throughput_summary.csv"

    write_latency_csv(latency_csv, postgres, timescale)
    write_storage_csv(storage_csv, postgres, timescale)
    write_throughput_csv(throughput_csv, postgres, timescale)

    render_throughput_chart(output_dir / "throughput_comparison.png", postgres, timescale)
    render_latency_chart(output_dir / "latency_comparison.png", postgres, timescale)
    render_storage_chart(output_dir / "storage_comparison.png", postgres, timescale)
    render_compression_chart(output_dir / "compression_comparison.png", timescale)

    markdown = build_markdown(postgres, timescale, latency_csv, storage_csv, throughput_csv)
    with open(output_dir / "comparative_report.md", "w", encoding="utf-8") as handle:
        handle.write(markdown)


def summary_paths(input_dir: Path) -> Tuple[Path, Path, Path]:
    return (
        input_dir / "summary_postgresql.json",
        input_dir / "summary_timescaledb.json",
        input_dir / "summary.json",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh benchmark storage metrics and report artifacts without rerunning latency benchmarks."
    )
    parser.add_argument("--input-dir", default="benchmarks/raw")
    parser.add_argument("--report-output-dir", default="benchmarks/report")
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    postgres_path, timescale_path, combined_path = summary_paths(input_dir)

    postgres_config, timescale_config = build_db_configs()
    postgres_summary = refresh_database_summary(postgres_path, postgres_config)
    timescale_summary = refresh_database_summary(timescale_path, timescale_config)

    combined_summary = load_json(combined_path)
    combined_summary["postgresql"] = postgres_summary
    combined_summary["timescaledb"] = timescale_summary
    combined_summary["storage_refreshed_at"] = now_utc_iso()
    write_json(combined_path, combined_summary)

    if not args.skip_report:
        regenerate_report(combined_summary, Path(args.report_output_dir))

    print(f"Refreshed storage metrics in {input_dir}")
    print(
        "PostgreSQL total size: "
        f"{format_bytes(postgres_summary['storage']['total_bytes'])}"
    )
    print(
        "TimescaleDB total size: "
        f"{format_bytes(timescale_summary['storage']['total_bytes'])}"
    )
    print(
        "TimescaleDB pre-compression total size: "
        f"{format_bytes(timescale_summary['storage'].get('total_bytes_pre_compression', timescale_summary['storage']['total_bytes']))}"
    )
    print(
        "TimescaleDB compression ratio: "
        f"{timescale_summary['storage'].get('total_compression_ratio')}"
    )
    if not args.skip_report:
        print(f"Regenerated report artifacts in {args.report_output_dir}")


if __name__ == "__main__":
    main()
