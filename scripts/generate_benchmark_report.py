#!/usr/bin/env python3
"""Generate Sprint 2 benchmark tables and charts from raw benchmark JSON summaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{size:.2f} {units[unit]}"


def aggregate_latency(summary: dict) -> Dict[str, Dict[str, float]]:
    aggregated: Dict[str, Dict[str, List[float]]] = {}
    for record in summary["records"]:
        for result in record["results"]:
            test_name = result["test_name"]
            bucket = aggregated.setdefault(test_name, {"avg_ms": [], "samples_ms": []})
            bucket["avg_ms"].append(float(result["avg_ms"]))
            bucket["samples_ms"].extend(float(sample) for sample in result["samples_ms"])

    return {
        test_name: {
            "avg_ms": sum(values["avg_ms"]) / len(values["avg_ms"]),
            "p95_ms": sorted(values["samples_ms"])[max(int(len(values["samples_ms"]) * 0.95) - 1, 0)],
        }
        for test_name, values in aggregated.items()
    }


def throughput_total(summary: dict) -> Dict[str, Any]:
    write_throughput = summary.get("write_throughput") or {}
    tables = write_throughput.get("tables") or {}
    total = tables.get("total")
    if isinstance(total, dict):
        return total
    return {
        "rows_inserted": None,
        "duration_sec": None,
        "rows_per_sec": None,
    }


def write_latency_csv(output_path: Path, postgres: dict, timescale: dict) -> None:
    pg = aggregate_latency(postgres)
    ts = aggregate_latency(timescale)
    test_names = sorted(set(pg) | set(ts))
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["test_name", "postgres_avg_ms", "timescale_avg_ms", "postgres_p95_ms", "timescale_p95_ms"])
        for test_name in test_names:
            writer.writerow([
                test_name,
                pg.get(test_name, {}).get("avg_ms"),
                ts.get(test_name, {}).get("avg_ms"),
                pg.get(test_name, {}).get("p95_ms"),
                ts.get(test_name, {}).get("p95_ms"),
            ])


def write_storage_csv(output_path: Path, postgres: dict, timescale: dict) -> None:
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["database", "signals_bytes", "annotations_apnea_bytes", "annotations_qrs_bytes", "total_bytes"])
        writer.writerow([
            "postgresql",
            postgres["storage"]["signals_bytes"],
            postgres["storage"]["annotations_apnea_bytes"],
            postgres["storage"]["annotations_qrs_bytes"],
            postgres["storage"]["total_bytes"],
        ])
        writer.writerow([
            "timescaledb",
            timescale["storage"]["signals_bytes"],
            timescale["storage"]["annotations_apnea_bytes"],
            timescale["storage"]["annotations_qrs_bytes"],
            timescale["storage"]["total_bytes"],
        ])


def write_throughput_csv(output_path: Path, postgres: dict, timescale: dict) -> None:
    pg_total = throughput_total(postgres)
    ts_total = throughput_total(timescale)
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["database", "rows_inserted", "duration_sec", "rows_per_sec"])
        writer.writerow([
            "postgresql",
            pg_total.get("rows_inserted"),
            pg_total.get("duration_sec"),
            pg_total.get("rows_per_sec"),
        ])
        writer.writerow([
            "timescaledb",
            ts_total.get("rows_inserted"),
            ts_total.get("duration_sec"),
            ts_total.get("rows_per_sec"),
        ])


def render_latency_chart(output_path: Path, postgres: dict, timescale: dict) -> None:
    pg = aggregate_latency(postgres)
    ts = aggregate_latency(timescale)
    test_names = sorted(set(pg) | set(ts))
    pg_values = [pg.get(test_name, {}).get("avg_ms", 0.0) for test_name in test_names]
    ts_values = [ts.get(test_name, {}).get("avg_ms", 0.0) for test_name in test_names]

    positions = list(range(len(test_names)))
    width = 0.38

    plt.figure(figsize=(11, 6))
    plt.bar([position - width / 2 for position in positions], pg_values, width=width, label="PostgreSQL")
    plt.bar([position + width / 2 for position in positions], ts_values, width=width, label="TimescaleDB")
    plt.xticks(positions, test_names, rotation=25, ha="right")
    plt.ylabel("Average latency (ms)")
    plt.title("Sprint 2 Query Latency Comparison")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def render_storage_chart(output_path: Path, postgres: dict, timescale: dict) -> None:
    labels = ["PostgreSQL total", "Timescale total", "Timescale pre-compression"]
    values = [
        postgres["storage"]["total_bytes"],
        timescale["storage"]["total_bytes"],
        timescale["storage"].get("total_bytes_pre_compression", timescale["storage"]["total_bytes"]),
    ]

    plt.figure(figsize=(9, 5))
    plt.bar(labels, values, color=["#4063d8", "#d86c40", "#8aa1ff"])
    plt.ylabel("Bytes")
    plt.title("Sprint 2 Storage Footprint Comparison")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def render_compression_chart(output_path: Path, timescale: dict) -> None:
    pre_value = timescale["storage"].get("signals_bytes_pre_compression", timescale["storage"]["signals_bytes"])
    post_value = timescale["storage"].get("signals_bytes_post_compression", timescale["storage"]["signals_bytes"])
    plt.figure(figsize=(7, 5))
    plt.bar(["Signals pre-compression", "Signals post-compression"], [pre_value, post_value], color=["#d8a040", "#40a36f"])
    plt.ylabel("Bytes")
    plt.title("TimescaleDB Signal Compression")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def render_throughput_chart(output_path: Path, postgres: dict, timescale: dict) -> None:
    pg_total = throughput_total(postgres)
    ts_total = throughput_total(timescale)
    labels = ["PostgreSQL", "TimescaleDB"]
    values = [
        pg_total.get("rows_per_sec") or 0.0,
        ts_total.get("rows_per_sec") or 0.0,
    ]

    plt.figure(figsize=(7, 5))
    plt.bar(labels, values, color=["#4063d8", "#d86c40"])
    plt.ylabel("Rows per second")
    plt.title("Sprint 2 Ingestion Rate Comparison")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def build_markdown(postgres: dict, timescale: dict, latency_csv: Path, storage_csv: Path, throughput_csv: Path) -> str:
    pg = aggregate_latency(postgres)
    ts = aggregate_latency(timescale)
    pg_total = throughput_total(postgres)
    ts_total = throughput_total(timescale)
    test_names = sorted(set(pg) | set(ts))

    lines = [
        "# Sprint 2 Benchmark Report",
        "",
        "## Scope",
        "",
        f"Records benchmarked: {', '.join(postgres['record_ids'])}",
        f"Benchmark method: {postgres['benchmark_method']}",
        f"Warmup iterations per query: {postgres['warmup_iterations']}",
        "",
        "## Query Latency",
        "",
        "| Test | PostgreSQL avg (ms) | TimescaleDB avg (ms) | PostgreSQL p95 (ms) | TimescaleDB p95 (ms) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for test_name in test_names:
        lines.append(
            f"| {test_name} | {pg.get(test_name, {}).get('avg_ms', 0.0):.2f} | {ts.get(test_name, {}).get('avg_ms', 0.0):.2f} | {pg.get(test_name, {}).get('p95_ms', 0.0):.2f} | {ts.get(test_name, {}).get('p95_ms', 0.0):.2f} |"
        )

    lines.extend([
        "",
        "## Write Throughput",
        "",
        f"PostgreSQL total throughput: {pg_total.get('rows_per_sec')}",
        f"TimescaleDB total throughput: {ts_total.get('rows_per_sec')}",
        "",
        "## Storage",
        "",
        f"PostgreSQL total size: {format_bytes(postgres['storage']['total_bytes'])}",
        f"TimescaleDB total size: {format_bytes(timescale['storage']['total_bytes'])}",
        f"TimescaleDB pre-compression total size: {format_bytes(timescale['storage'].get('total_bytes_pre_compression', timescale['storage']['total_bytes']))}",
        f"TimescaleDB compression ratio: {timescale['storage'].get('total_compression_ratio')}",
        "",
        "## Generated Artifacts",
        "",
        f"- Latency CSV: {latency_csv}",
        f"- Storage CSV: {storage_csv}",
        f"- Throughput CSV: {throughput_csv}",
        "- Charts: throughput_comparison.png, latency_comparison.png, storage_comparison.png, compression_comparison.png",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate tables and charts from raw Sprint 2 benchmark summaries.")
    parser.add_argument("--input", default="benchmarks/raw/summary.json")
    parser.add_argument("--output-dir", default="benchmarks/report")
    args = parser.parse_args()

    payload = load_json(Path(args.input))
    postgres = payload["postgresql"]
    timescale = payload["timescaledb"]

    output_dir = Path(args.output_dir)
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

    print(f"Benchmark report written to {output_dir}")


if __name__ == "__main__":
    main()
