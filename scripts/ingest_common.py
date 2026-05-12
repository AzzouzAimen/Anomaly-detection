#!/usr/bin/env python3
"""Shared helpers for Sprint 2 database ingestion scripts."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Sequence

import psycopg2
from psycopg2 import sql
from psycopg2 import OperationalError
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


@dataclass
class IngestionStats:
    table: str
    rows_inserted: int
    duration_sec: float


@dataclass
class DatabaseLoadSummary:
    database_name: str
    source_dir: str
    start_time: str
    end_time: str
    stats: List[IngestionStats]

    def to_dict(self) -> dict:
        return {
            "database_name": self.database_name,
            "source_dir": self.source_dir,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "stats": [asdict(stat) for stat in self.stats],
        }


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_jsonl_rows(path: Path) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def read_json_array(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def recording_ids_from_processed_dir(processed_dir: Path) -> List[str]:
    ids = set()
    for path in processed_dir.glob("signals_*.jsonl"):
        ids.add(path.stem.replace("signals_", ""))
    for path in processed_dir.glob("apnea_*.json"):
        ids.add(path.stem.replace("apnea_", ""))
    for path in processed_dir.glob("qrs_*.json"):
        ids.add(path.stem.replace("qrs_", ""))
    return sorted(ids)


def chunked(sequence: Sequence[tuple], chunk_size: int) -> Iterator[Sequence[tuple]]:
    for index in range(0, len(sequence), chunk_size):
        yield sequence[index:index + chunk_size]


def write_summary_json(output_path: Path, summary: DatabaseLoadSummary) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(summary.to_dict(), handle, indent=2)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def env_default(name: str, fallback: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return fallback
    return value.strip()


def parse_timestamp(value: object) -> str:
    """Normalize processed timestamps to explicit UTC ISO-8601 strings."""
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
    else:
        raise TypeError(f"Unsupported timestamp value: {value!r}")

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    return timestamp.isoformat()


def _is_retryable_connection_error(message: str) -> bool:
    lowered = message.lower()
    retryable_markers = (
        "connection refused",
        "server closed the connection unexpectedly",
        "the database system is starting up",
        "timeout expired",
        "could not connect to server",
        "temporary failure",
        "connection reset by peer",
    )
    return any(marker in lowered for marker in retryable_markers)


def _is_authentication_error(message: str) -> bool:
    lowered = message.lower()
    auth_markers = (
        "password authentication failed",
        "role",
        "does not exist",
        "no pg_hba.conf entry",
        "authentication failed",
    )
    return any(marker in lowered for marker in auth_markers)


def _format_connection_error(
    database_label: str,
    host: str,
    port: int,
    database: str,
    user: str,
    original_error: Exception,
    auth_help: str | None,
    attempts: int,
) -> RuntimeError:
    message = str(original_error).strip()
    detail_lines = [
        f"Could not connect to {database_label} at {host}:{port}/{database} as user {user!r} after {attempts} attempt(s).",
    ]

    if _is_authentication_error(message):
        detail_lines.append("The live database credentials do not match the loader credentials.")
        if auth_help:
            detail_lines.append(auth_help)
    else:
        detail_lines.append("The database may still be starting, unavailable on the configured host/port, or using different connection settings.")

    detail_lines.append(f"Driver error: {message}")
    return RuntimeError(" ".join(detail_lines))


def connect_db(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    database_label: str = "database",
    auth_help: str | None = None,
    max_attempts: int = 3,
    retry_delay_sec: float = 1.0,
):
    last_error: Exception | None = None
    attempts_used = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        try:
            connection = psycopg2.connect(
                host=host,
                port=port,
                dbname=database,
                user=user,
                password=password,
                connect_timeout=10,
            )
            connection.autocommit = False
            with connection.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'UTC';")
            connection.commit()
            return connection
        except OperationalError as error:
            last_error = error
            message = str(error)
            if attempt < max_attempts and _is_retryable_connection_error(message) and not _is_authentication_error(message):
                logger.warning(
                    "Connection attempt %s/%s to %s failed: %s Retrying in %.1fs.",
                    attempt,
                    max_attempts,
                    database_label,
                    message.strip(),
                    retry_delay_sec,
                )
                time.sleep(retry_delay_sec)
                continue
            break

    raise _format_connection_error(
        database_label=database_label,
        host=host,
        port=port,
        database=database,
        user=user,
        original_error=last_error or RuntimeError("Unknown connection failure"),
        auth_help=auth_help,
        attempts=attempts_used,
    )


def run_sql(connection, query: str, params: Sequence[object] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(query, params)


def insert_values(connection, query: str, rows: List[tuple]) -> int:
    if not rows:
        return 0
    with connection.cursor() as cursor:
        execute_values(cursor, query, rows)
    return len(rows)


def copy_rows(
    connection,
    table: str,
    columns: List[str],
    rows: List[tuple],
) -> int:
    if not rows:
        return 0

    expected_columns = len(columns)
    for row in rows:
        if len(row) != expected_columns:
            raise ValueError(
                f"Column/value mismatch for {table}: expected {expected_columns}, got {len(row)}"
            )

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    for row in rows:
        formatted = []
        for value in row:
            if value is None:
                formatted.append("\\N")
            elif isinstance(value, bool):
                formatted.append("t" if value else "f")
            else:
                formatted.append(str(value))
        writer.writerow(formatted)

    copy_sql = (
        f"COPY {table} ({', '.join(columns)}) "
        "FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
    )
    buffer.seek(0)
    with connection.cursor() as cursor:
        cursor.copy_expert(copy_sql, buffer)
    return len(rows)


def record_exists_in_table(connection, table: str, recording_id: str) -> bool:
    """Check if a recording_id already has rows in a specific table."""
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT 1 FROM {} WHERE recording_id = %s LIMIT 1;").format(sql.Identifier(table)),
            (recording_id,),
        )
        return cursor.fetchone() is not None


def record_exists_in_signals(connection, recording_id: str) -> bool:
    """Check if a recording_id already has signals loaded."""
    return record_exists_in_table(connection, "signals", recording_id)


def record_exists_in_apnea_annotations(connection, recording_id: str) -> bool:
    """Check if a recording_id already has apnea annotations loaded."""
    return record_exists_in_table(connection, "annotations_apnea", recording_id)


def record_exists_in_qrs_annotations(connection, recording_id: str) -> bool:
    """Check if a recording_id already has QRS annotations loaded."""
    return record_exists_in_table(connection, "annotations_qrs", recording_id)
