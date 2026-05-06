#!/usr/bin/env python3
"""
Generate data/metadata/dataset_baseline.json from data/raw/*.hea files.

For each base record, such as a01, b01, c01, or x01:
  - If a combined ECG + respiration header (<record>er.hea) exists, use it.
  - Otherwise, fall back to the base <record>.hea file.

The output contains:
  - split: learning/test
  - category: a/b/c/x
  - subject_id
  - sampling rate
  - recording length
  - available signals
  - whether respiration signals exist
  - whether apnea labels exist
  - whether QRS annotations exist

Run from the repository root:

    python scripts/generate_metadata.py
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple


RAW_DIR = Path("data/raw")
METADATA_DIR = Path("data/metadata")
OUTPUT_FILE = METADATA_DIR / "dataset_baseline.json"

# Base Apnea-ECG records have names like:
# a01.hea, b05.hea, c10.hea, x35.hea
BASE_RECORD_RE = re.compile(r"^[abcx]\d{2}\.hea$", re.IGNORECASE)


def parse_hea(hea_path: Path) -> Tuple[Optional[int], Optional[int], List[str]]:
    """
    Parse a WFDB .hea header file.

    Returns:
        sampling_rate_hz, num_samples, signal_names

    Any value can be None if parsing fails.
    """

    lines = hea_path.read_text(encoding="utf-8", errors="replace").splitlines()

    sampling_rate_hz = None
    num_samples = None
    signal_names = []

    for line in lines:
        line = line.strip().rstrip("\r")

        if not line or line.startswith("#"):
            continue

        parts = line.split()

        if not parts:
            continue

        # Signal line:
        # Example structure:
        # filename.dat format gain adc_resolution adc_zero init_value checksum block_size description
        if parts[0].endswith(".dat"):
            if len(parts) >= 9:
                description = " ".join(parts[8:])
            elif len(parts) >= 2:
                description = parts[-1]
            else:
                description = "Unknown"

            signal_names.append(description)
            continue

        # Record header line:
        # record_name number_of_signals sampling_rate number_of_samples ...
        try:
            if len(parts) >= 3 and sampling_rate_hz is None:
                sampling_rate_hz = int(float(parts[2]))

            if len(parts) >= 4 and num_samples is None:
                num_samples = int(parts[3])

        except ValueError:
            continue

    return sampling_rate_hz, num_samples, signal_names


def get_record_category(record_name: str) -> str:
    """
    Return record category: a, b, c, or x.
    """
    return record_name[0].lower()


def get_split(category: str) -> str:
    """
    Apnea-ECG split:
      - a, b, c records are learning records
      - x records are test records
    """
    return "test" if category == "x" else "learning"


def get_subject_id(record_name: str) -> str:
    """
    Most records are treated as one subject per recording.

    Special case:
    PhysioNet notes that c05 and c06 come from the same original recording.
    We map them to the same subject_id to support the normalized schema.
    """
    if record_name in {"c05", "c06"}:
        return "subject_c05_c06"

    return f"subject_{record_name}"


def has_respiration_signals(signal_names: List[str]) -> bool:
    """
    Detect whether a record contains extra respiration or oxygen signals.
    """
    normalized = [signal.lower() for signal in signal_names]

    return any(
        signal.startswith("resp") or "spo2" in signal
        for signal in normalized
    )


def main() -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    base_hea_files = sorted(
        hea_file
        for hea_file in RAW_DIR.glob("*.hea")
        if BASE_RECORD_RE.match(hea_file.name)
    )

    if not base_hea_files:
        print(f"No base .hea files found in {RAW_DIR}.")
        print("Expected files like a01.hea, b01.hea, c01.hea, x01.hea.")
        return

    metadata = {}
    skipped = []

    total_signal_rows_estimate = 0

    for base_hea in base_hea_files:
        record_name = base_hea.stem.lower()

        # Prefer combined ECG + respiration header when it exists.
        combined_hea = RAW_DIR / f"{record_name}er.hea"

        if combined_hea.exists():
            hea_to_use = combined_hea
        else:
            hea_to_use = base_hea

        sampling_rate_hz, num_samples, signal_names = parse_hea(hea_to_use)

        if sampling_rate_hz is None or num_samples is None:
            print(
                f"WARNING: skipping {record_name} "
                f"because {hea_to_use.name} could not be parsed."
            )
            skipped.append(record_name)
            continue

        length_seconds = round(num_samples / sampling_rate_hz)

        category = get_record_category(record_name)
        split = get_split(category)

        apnea_file_exists = (
            (RAW_DIR / f"{record_name}.apn").exists()
            or (RAW_DIR / f"{record_name}r.apn").exists()
            or (RAW_DIR / f"{record_name}er.apn").exists()
        )

        qrs_file_exists = (
            (RAW_DIR / f"{record_name}.qrs").exists()
            or (RAW_DIR / f"{record_name}er.qrs").exists()
        )

        respiration_available = has_respiration_signals(signal_names)

        total_signal_rows_estimate += num_samples

        metadata[record_name] = {
            "record_name": record_name,
            "subject_id": get_subject_id(record_name),
            "source_record_name": record_name,

            "split": split,
            "category": category,

            "sampling_rate_hz": sampling_rate_hz,
            "num_samples": num_samples,
            "length_seconds": length_seconds,

            "signals": signal_names,
            "has_respiration": respiration_available,
            "has_apnea_annotations": apnea_file_exists,
            "has_qrs_annotations": qrs_file_exists,

            "selected_header_file": hea_to_use.name,
            "artificial_start_time": "2000-01-01 00:00:00",

            "source": "PhysioNet Apnea-ECG Database",
            "source_url": "https://physionet.org/content/apnea-ecg/1.0.0/",
            "doi": "10.13026/C23W2R",
            "license": "Open Data Commons Attribution License v1.0"
        }

        print(
            f"{record_name:4s} | "
            f"split={split:8s} | "
            f"signals={len(signal_names)} | "
            f"respiration={respiration_available} | "
            f"apnea_labels={apnea_file_exists} | "
            f"qrs={qrs_file_exists} | "
            f"{sampling_rate_hz} Hz | "
            f"{length_seconds} s"
        )

    with OUTPUT_FILE.open("w", encoding="utf-8") as output:
        json.dump(metadata, output, indent=2, ensure_ascii=False)

    print()
    print(f"Wrote metadata for {len(metadata)} records to {OUTPUT_FILE}")
    print(f"Estimated total signal rows: {total_signal_rows_estimate:,}")

    if skipped:
        print(f"Skipped records: {skipped}")


if __name__ == "__main__":
    main()