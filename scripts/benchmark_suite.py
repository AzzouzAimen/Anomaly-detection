#!/usr/bin/env python3
"""Run Sprint 2 comparative benchmarks on PostgreSQL and TimescaleDB."""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from ingest_common import connect_db as connect_with_retries


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    test_name: str
    iterations: int
    warmup_iterations: int
    result_rows: int
    min_ms: float
    max_ms: float
    avg_ms: float
    stdev_ms: float
    total_ms: float
    samples_ms: List[float]


@dataclass
class DbConfig:
    name: str
    host: str
    port: int
    database: str
    user: str
    password: str
    display_name: str
    auth_help: str
    is_timescale: bool


def env_default(name: str, fallback: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return fallback
    return value.strip()


def ingestion_log_path(db: DbConfig, processed_dir: Path | None) -> Path:
    if processed_dir is not None:
        return processed_dir / ("timescaledb_ingestion_log.json" if db.is_timescale else "postgresql_ingestion_log.json")
    return Path("database/timeseries/ingestion_log.json") if db.is_timescale else Path("database/postgresql/ingestion_log.json")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db: DbConfig):
    connection = connect_with_retries(
        db.host,
        db.port,
        db.database,
        db.user,
        db.password,
        database_label=db.display_name,
        auth_help=db.auth_help,
    )
    connection.autocommit = True
    return connection


def run_scalar(connection, sql: str, params: Sequence[Any] | None = None) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return row[0] if row else None


def execute_query(connection, sql: str, params: Sequence[Any] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        if cursor.description is None:
            return cursor.rowcount
        rows = cursor.fetchall()
        return len(rows)


def time_query(
    connection,
    sql: str,
    params: Sequence[Any] | None,
    iterations: int,
    warmup_iterations: int,
) -> BenchmarkResult:
    for _ in range(warmup_iterations):
        execute_query(connection, sql, params)

    samples_ms: List[float] = []
    result_rows = 0
    for _ in range(iterations):
        start = datetime.now(timezone.utc)
        result_rows = execute_query(connection, sql, params)
        elapsed_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        samples_ms.append(elapsed_ms)

    return BenchmarkResult(
        test_name="",
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        result_rows=result_rows,
        min_ms=min(samples_ms),
        max_ms=max(samples_ms),
        avg_ms=statistics.mean(samples_ms),
        stdev_ms=statistics.pstdev(samples_ms) if len(samples_ms) > 1 else 0.0,
        total_ms=sum(samples_ms),
        samples_ms=samples_ms,
    )


def minute_bucket_sql(column: str, is_timescale: bool) -> str:
    if is_timescale:
        return f"time_bucket('1 minute', {column})"
    return f"date_trunc('minute', {column})"


def build_tests(record_id: str, start_ts: str, is_timescale: bool) -> List[Tuple[str, str, Tuple[Any, ...], int]]:
    minute_bucket = minute_bucket_sql("recorded_at", is_timescale)

    tests: List[Tuple[str, str, Tuple[Any, ...], int]] = []
    tests.append((
        "range_query_latency",
        (
            "SELECT recorded_at, ecg_value "
            "FROM signals "
            "WHERE recording_id = %s "
            "AND recorded_at >= %s::timestamptz "
            "AND recorded_at < %s::timestamptz + INTERVAL '1 hour' "
            "ORDER BY recorded_at;"
        ),
        (record_id, start_ts, start_ts),
        100,
    ))
    tests.append((
        "temporal_aggregation",
        (
            f"SELECT {minute_bucket} AS minute, "
            "AVG(ecg_value), MIN(ecg_value), MAX(ecg_value) "
            "FROM signals "
            "WHERE recording_id = %s "
            "GROUP BY minute ORDER BY minute;"
        ),
        (record_id,),
        10,
    ))
    tests.append((
        "qrs_aggregation",
        (
            f"SELECT {minute_bucket} AS minute, COUNT(*) "
            "FROM annotations_qrs "
            "WHERE recording_id = %s "
            "GROUP BY minute ORDER BY minute;"
        ),
        (record_id,),
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
            "WHERE a.recording_id = %s "
            "GROUP BY a.minute_index, a.label "
            "ORDER BY a.minute_index;"
        ),
        (record_id,),
        5,
    ))
    return tests


def read_ingestion_metrics(db: DbConfig, processed_dir: Path | None = None) -> Dict[str, Any]:
    log_path = ingestion_log_path(db, processed_dir)
    if not log_path.exists():
        return {"available": False, "source": str(log_path)}

    with open(log_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    tracked_tables = {"signals", "annotations_apnea", "annotations_qrs"}
    per_table: Dict[str, Any] = {}
    total_rows = 0
    total_duration = 0.0
    compression = None

    for stat in payload.get("stats", []):
        table = stat.get("table")
        if table == "compression":
            compression = {
                "rows_inserted": int(stat.get("rows_inserted", 0)),
                "duration_sec": float(stat.get("duration_sec", 0.0)),
            }
            continue

        if table not in tracked_tables:
            continue

        rows_inserted = int(stat.get("rows_inserted", 0))
        duration_sec = float(stat.get("duration_sec", 0.0))
        total_rows += rows_inserted
        total_duration += duration_sec
        per_table[table] = {
            "rows_inserted": rows_inserted,
            "duration_sec": duration_sec,
            "rows_per_sec": (rows_inserted / duration_sec) if duration_sec > 0 else None,
        }

    per_table["total"] = {
        "rows_inserted": total_rows,
        "duration_sec": total_duration,
        "rows_per_sec": (total_rows / total_duration) if total_duration > 0 else None,
    }

    return {
        "available": True,
        "source": str(log_path),
        "compression": compression,
        "tables": per_table,
    }


def ensure_timescale_signal_compression(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE signals SET ("
            "timescaledb.compress, "
            "timescaledb.compress_segmentby = 'recording_id', "
            "timescaledb.compress_orderby = 'recorded_at DESC'"
            ");"
        )
        cursor.execute("SELECT add_compression_policy('signals', INTERVAL '1 day', if_not_exists => TRUE);")
        cursor.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT compress_chunk(chunk, if_not_compressed => TRUE) "
            "FROM show_chunks('signals') AS chunk"
            ") AS compressed;"
        )
        return int(cursor.fetchone()[0] or 0)


def get_storage_metrics(db: DbConfig, connection, ingestion_metrics: Dict[str, Any]) -> Dict[str, Any]:
    apnea_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('annotations_apnea');") or 0)
    qrs_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('annotations_qrs');") or 0)

    if db.is_timescale:
        signals_bytes = int(run_scalar(connection, "SELECT total_bytes FROM hypertable_detailed_size('signals');") or 0)
    else:
        signals_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('signals');") or 0)
    total_bytes = signals_bytes + apnea_bytes + qrs_bytes

    storage = {
        "signals_bytes": signals_bytes,
        "annotations_apnea_bytes": apnea_bytes,
        "annotations_qrs_bytes": qrs_bytes,
        "total_bytes": total_bytes,
    }

    if db.is_timescale:
        compression_during_ingestion = bool((ingestion_metrics.get("compression") or {}).get("rows_inserted"))
        pre_compression_signals_bytes = signals_bytes
        pre_compression_total_bytes = total_bytes
        compressed_chunks = ensure_timescale_signal_compression(connection)
        post_compression_signals_bytes = int(run_scalar(connection, "SELECT pg_total_relation_size('signals');") or 0)
        post_compression_total_bytes = post_compression_signals_bytes + apnea_bytes + qrs_bytes
        storage.update(
            {
                "compression_was_applied_during_ingestion": compression_during_ingestion,
                "signals_bytes_pre_compression": pre_compression_signals_bytes,
                "signals_bytes_post_compression": post_compression_signals_bytes,
                "total_bytes_pre_compression": pre_compression_total_bytes,
                "total_bytes_post_compression": post_compression_total_bytes,
                "signals_compression_ratio": (
                    pre_compression_signals_bytes / post_compression_signals_bytes
                    if post_compression_signals_bytes > 0
                    else None
                ),
                "total_compression_ratio": (
                    pre_compression_total_bytes / post_compression_total_bytes
                    if post_compression_total_bytes > 0
                    else None
                ),
                "chunks_processed_for_compression": compressed_chunks,
                "signals_bytes": post_compression_signals_bytes,
                "total_bytes": post_compression_total_bytes,
            }
        )

    return storage


def benchmark_record(connection, db: DbConfig, record_id: str, warmup_iterations: int) -> Dict[str, Any]:
    start_ts = run_scalar(
        connection,
        "SELECT MIN(recorded_at)::text FROM signals WHERE recording_id = %s;",
        (record_id,),
    )
    if start_ts is None:
        raise ValueError(f"No signal rows found for record {record_id!r} in {db.name}")

    results: List[BenchmarkResult] = []
    for test_name, sql, params, iterations in build_tests(record_id, start_ts, db.is_timescale):
        result = time_query(connection, sql, params, iterations, warmup_iterations)
        result.test_name = test_name
        results.append(result)

    return {
        "record_id": record_id,
        "start_ts": start_ts,
        "results": [asdict(result) for result in results],
    }


def benchmark_database(
    db: DbConfig,
    record_ids: List[str],
    output_dir: Path,
    warmup_iterations: int,
    processed_dir: Path | None,
) -> Dict[str, Any]:
    ingestion_metrics = read_ingestion_metrics(db, processed_dir)
    connection = connect_db(db)
    try:
        record_payloads = [benchmark_record(connection, db, record_id, warmup_iterations) for record_id in record_ids]
        storage = get_storage_metrics(db, connection, ingestion_metrics)
    finally:
        connection.close()

    payload = {
        "database": db.name,
        "generated_at": now_utc_iso(),
        "benchmark_method": "persistent_psycopg2_connection",
        "warmup_iterations": warmup_iterations,
        "record_ids": record_ids,
        "records": record_payloads,
        "write_throughput": ingestion_metrics,
        "storage": storage,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / f"summary_{db.name}.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return payload


def build_db_configs() -> Tuple[DbConfig, DbConfig]:
    postgres = DbConfig(
        name="postgresql",
        host=env_default("POSTGRES_HOST", "127.0.0.1"),
        port=int(env_default("POSTGRES_PORT", "5432")),
        database=env_default("POSTGRES_DB", "apnea_db"),
        user=env_default("POSTGRES_USER", "user"),
        password=env_default("POSTGRES_PASSWORD", "password"),
        display_name="PostgreSQL",
        auth_help=(
            "Verify POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD or rerun the benchmark "
            "with corrected environment variables."
        ),
        is_timescale=False,
    )
    timescale = DbConfig(
        name="timescaledb",
        host=env_default("TIMESCALE_HOST", "127.0.0.1"),
        port=int(env_default("TIMESCALE_PORT", "5433")),
        database=env_default("TIMESCALE_DB", "apnea_ts_db"),
        user=env_default("TIMESCALE_USER", "user"),
        password=env_default("TIMESCALE_PASSWORD", "timescale_password"),
        display_name="TimescaleDB",
        auth_help=(
            "Verify TIMESCALE_HOST/TIMESCALE_PORT/TIMESCALE_DB/TIMESCALE_USER/TIMESCALE_PASSWORD or rerun the benchmark "
            "with corrected environment variables. If the container was created before the compose default-user change, "
            "recreate the Timescale service or set TIMESCALE_USER=timescale_user and TIMESCALE_PASSWORD=timescale_password."
        ),
        is_timescale=True,
    )
    return postgres, timescale


def main() -> None:
    parser = argparse.ArgumentParser(description="Run comparative benchmarks on PostgreSQL and TimescaleDB.")
    parser.add_argument(
        "--record",
        action="append",
        dest="records",
        help="Recording ID to benchmark. Repeat the flag to benchmark multiple records.",
    )
    parser.add_argument("--warmup-iterations", type=int, default=2)
    parser.add_argument("--output-dir", default="benchmarks/raw")
    parser.add_argument(
        "--processed-dir",
        default="data/processed",
        help="Processed output directory whose ingestion logs should be used for throughput metadata.",
    )
    args = parser.parse_args()

    records = args.records or ["a01"]
    postgres, timescale = build_db_configs()

    out_dir = Path(args.output_dir)
    processed_dir = Path(args.processed_dir) if args.processed_dir else None
    try:
        payload = {
            "generated_at": now_utc_iso(),
            "records": records,
            "postgresql": benchmark_database(postgres, records, out_dir, args.warmup_iterations, processed_dir),
            "timescaledb": benchmark_database(timescale, records, out_dir, args.warmup_iterations, processed_dir),
        }
    except RuntimeError as error:
        logger.error(str(error))
        raise SystemExit(1) from None

    with open(out_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"Benchmark summary written to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
