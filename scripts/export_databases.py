#!/usr/bin/env python3
"""Prepare or execute reproducible PostgreSQL and TimescaleDB exports for Sprint 2."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def env_default(name: str, fallback: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return fallback
    return value.strip()


def build_jobs(output_dir: Path, mode: str, target: str) -> List[Dict[str, object]]:
    jobs = []
    definitions = [
        {
            "name": "postgresql",
            "container": env_default("POSTGRES_CONTAINER", "apnea_postgres"),
            "database": env_default("POSTGRES_DB", "apnea_db"),
            "user": env_default("POSTGRES_USER", "user"),
        },
        {
            "name": "timescaledb",
            "container": env_default("TIMESCALE_CONTAINER", "apnea_timescaledb"),
            "database": env_default("TIMESCALE_DB", "apnea_ts_db"),
            "user": env_default("TIMESCALE_USER", "user"),
        },
    ]

    if target != "both":
        definitions = [definition for definition in definitions if definition["name"] == target]

    mode_flags = {
        "full": ["-Fc"],
        "schema": ["-Fc", "--schema-only"],
        "data": ["-Fc", "--data-only"],
    }[mode]

    for definition in definitions:
        export_path = output_dir / definition["name"] / f"{definition['name']}_{mode}.dump"
        command = [
            "docker",
            "exec",
            definition["container"],
            "pg_dump",
            "-U",
            definition["user"],
            "-d",
            definition["database"],
            *mode_flags,
        ]
        jobs.append(
            {
                "database": definition["name"],
                "container": definition["container"],
                "database_name": definition["database"],
                "user": definition["user"],
                "mode": mode,
                "output_path": str(export_path),
                "command": command,
            }
        )

    return jobs


def execute_job(job: Dict[str, object]) -> None:
    output_path = Path(job["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as handle:
        subprocess.run(job["command"], stdout=handle, check=True)


def build_structured_repository_note(manifest: Dict[str, object]) -> str:
    jobs = manifest["jobs"]
    lines = [
        "# Structured Repository Package",
        "",
        "This directory contains the Sprint 2 export manifest and, when exports are executed, database dump artifacts for the cleaned and windowed dataset state.",
        "",
        "## Package Contents",
        "",
        "- `export_manifest.json`: machine-readable export metadata",
        "- `postgresql/` and `timescaledb/`: dump output directories when `--execute` is used",
        "",
        "## Access And Reproduction",
        "",
        "Use the repository `.env` or `.env.example` values to match the database names, users, and container names below.",
        "",
        "| Database | Container | DB Name | User | Mode | Output |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for job in jobs:
        lines.append(
            f"| {job['database']} | {job['container']} | {job['database_name']} | {job['user']} | {job['mode']} | {job['output_path']} |"
        )

    lines.extend([
        "",
        "## Notes",
        "",
        "- Export artifacts are intentionally generated outside Git because full dumps can be large.",
        "- The manifest is still useful even when exports are not executed because it records the exact dump commands and target locations.",
        "- These exports should be regenerated after the final Sprint 2 ETL, ingestion, and benchmarking cycle so they match the same cleaned/windowed dataset state.",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or execute Sprint 2 database exports.")
    parser.add_argument("--mode", choices=["full", "schema", "data"], default="full")
    parser.add_argument("--database", choices=["postgresql", "timescaledb", "both"], default="both")
    parser.add_argument("--output-dir", default="exports")
    parser.add_argument("--execute", action="store_true", help="Run the export commands. Without this flag the script only writes a manifest.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    jobs = build_jobs(output_dir, args.mode, args.database)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": args.mode,
        "database": args.database,
        "execute": args.execute,
        "jobs": jobs,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "export_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    note_path = output_dir / "STRUCTURED_REPOSITORY.md"
    with open(note_path, "w", encoding="utf-8") as handle:
        handle.write(build_structured_repository_note(manifest))

    if args.execute:
        for job in jobs:
            execute_job(job)

    print(f"Export manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
