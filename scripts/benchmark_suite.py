#!/usr/bin/env python3
"""Run Sprint 2 comparative benchmarks on PostgreSQL and TimescaleDB."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class BenchmarkResult:
    test_name: str
    iterations: int
    min_ms: float
    max_ms: float
    avg_ms: float
    stdev_ms: float
    total_ms: float


@dataclass
class DbConfig:
    name: str
    container: str
    database: str
    user: str
    is_timescale: bool


def run_psql_scalar(container: str, database: str, user: str, sql: str) -> str:
    command = [
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-t",
        "-A",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def time_query(container: str, database: str, user: str, sql: str, iterations: int) -> BenchmarkResult:
    samples_ms: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        run_psql_scalar(container, database, user, sql)
        samples_ms.append((time.perf_counter() - start) * 1000)

    return BenchmarkResult(
        test_name="",
        iterations=iterations,
        min_ms=min(samples_ms),
        max_ms=max(samples_ms),
        avg_ms=statistics.mean(samples_ms),
        stdev_ms=statistics.pstdev(samples_ms),
        total_ms=sum(samples_ms),
    )


def minute_bucket_sql(column: str, is_timescale: bool) -> str:
    if is_timescale:
        return f"time_bucket('1 minute', {column})"
    return f"date_trunc('minute', {column})"


def build_tests(db: DbConfig, record_id: str, start_ts: str) -> List[Tuple[str, str, int]]:
    minute_bucket = minute_bucket_sql("recorded_at", db.is_timescale)
    one_hour_end = f"{start_ts}'::timestamp + INTERVAL '1 hour"

    tests: List[Tuple[str, str, int]] = []

    tests.append((
        "range_query_latency",
        (
            "SELECT recorded_at, ecg_value "
            "FROM signals "
            f"WHERE recording_id = '{record_id}' "
            f"AND recorded_at >= '{start_ts}'::timestamp "
            f"AND recorded_at < '{start_ts}'::timestamp + INTERVAL '1 hour' "
            "ORDER BY recorded_at;"
        ),
        100,
    ))

    tests.append((
        "temporal_aggregation",
        (
            f"SELECT {minute_bucket} AS minute, "
            "AVG(ecg_value), MIN(ecg_value), MAX(ecg_value) "
            "FROM signals "
            f"WHERE recording_id = '{record_id}' "
            "GROUP BY minute ORDER BY minute;"
        ),
        10,
    ))

    tests.append((
        "qrs_aggregation",
        (
            f"SELECT {minute_bucket} AS minute, COUNT(*) "
            "FROM annotations_qrs "
            f"WHERE recording_id = '{record_id}' "
            "GROUP BY minute ORDER BY minute;"
        ),
        10,
    ))

    tests.append((
        "signal_label_join",
        (
            "SELECT a.minute_index, a.label, COUNT(*), AVG(s.ecg_value) "
            "FROM annotations_apnea a "
            "JOIN signals s "
            "ON s.recording_id = a.recording_id "
            "AND s.recorded_at >= a.recorded_at "
            "AND s.recorded_at < a.recorded_at + INTERVAL '1 minute' "
            f"WHERE a.recording_id = '{record_id}' "
            "GROUP BY a.minute_index, a.label "
            "ORDER BY a.minute_index;"
        ),
        5,
    ))

    return tests


def get_storage_metrics(db: DbConfig) -> Dict[str, Any]:
    signals_bytes = int(run_psql_scalar(db.container, db.database, db.user, "SELECT pg_total_relation_size('signals');"))
    apnea_bytes = int(run_psql_scalar(db.container, db.database, db.user, "SELECT pg_total_relation_size('annotations_apnea');"))
    qrs_bytes = int(run_psql_scalar(db.container, db.database, db.user, "SELECT pg_total_relation_size('annotations_qrs');"))
    return {
        "signals_bytes": signals_bytes,
        "annotations_apnea_bytes": apnea_bytes,
        "annotations_qrs_bytes": qrs_bytes,
        "total_bytes": signals_bytes + apnea_bytes + qrs_bytes,
    }


def benchmark_database(db: DbConfig, record_id: str, output_dir: Path) -> Dict[str, Any]:
    start_ts = run_psql_scalar(
        db.container,
        db.database,
        db.user,
        f"SELECT MIN(recorded_at) FROM signals WHERE recording_id = '{record_id}';",
    )

    results: List[BenchmarkResult] = []
    for test_name, sql, iterations in build_tests(db, record_id, start_ts):
        result = time_query(db.container, db.database, db.user, sql, iterations)
        result.test_name = test_name
        results.append(result)

    storage = get_storage_metrics(db)

    payload = {
        "database": db.name,
        "record_id": record_id,
        "results": [asdict(result) for result in results],
        "storage": storage,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / f"summary_{db.name}.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run comparative benchmarks on PostgreSQL and TimescaleDB.")
    parser.add_argument("--record", default="a01", help="Recording ID to benchmark.")
    parser.add_argument("--output-dir", default="benchmarks")
    args = parser.parse_args()

    postgres = DbConfig("postgresql", "apnea_postgres", "apnea_db", "user", False)
    timescale = DbConfig("timescaledb", "apnea_timescaledb", "apnea_ts_db", "user", True)

    out_dir = Path(args.output_dir)
    payload = {
        "postgresql": benchmark_database(postgres, args.record, out_dir),
        "timescaledb": benchmark_database(timescale, args.record, out_dir),
    }

    with open(out_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"Benchmark summary written to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
