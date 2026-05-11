#!/usr/bin/env python3
"""Shared helpers for Sprint 2 database ingestion scripts."""

from __future__ import annotations

import csv
import io
import json
import logging
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Sequence

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
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def run_psql(container: str, database: str, user: str, sql: str) -> None:
    command = [
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    subprocess.run(command, check=True)


def copy_rows_psql(
    container: str,
    database: str,
    user: str,
    table: str,
    columns: List[str],
    rows: List[tuple],
) -> int:
    if not rows:
        return 0

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
        f"\\copy {table} ({', '.join(columns)}) "
        "FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')"
    )

    command = [
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        copy_sql,
    ]
    subprocess.run(command, input=buffer.getvalue(), text=True, check=True)
    return len(rows)


def record_exists_in_table(container: str, database: str, user: str, table: str, recording_id: str) -> bool:
    """Check if a recording_id already has rows in a specific table."""
    query = f"SELECT 1 FROM {table} WHERE recording_id = '{recording_id}' LIMIT 1;"
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
        "-c",
        query,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return bool(result.stdout.strip())


def record_exists_in_signals(container: str, database: str, user: str, recording_id: str) -> bool:
    """Check if a recording_id already has signals loaded."""
    return record_exists_in_table(container, database, user, "signals", recording_id)


def record_exists_in_apnea_annotations(container: str, database: str, user: str, recording_id: str) -> bool:
    """Check if a recording_id already has apnea annotations loaded."""
    return record_exists_in_table(container, database, user, "annotations_apnea", recording_id)


def record_exists_in_qrs_annotations(container: str, database: str, user: str, recording_id: str) -> bool:
    """Check if a recording_id already has QRS annotations loaded."""
    return record_exists_in_table(container, database, user, "annotations_qrs", recording_id)
