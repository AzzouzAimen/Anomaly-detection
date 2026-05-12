#!/usr/bin/env python3
"""
Sprint 2 ETL Pipeline

Core module for extracting, transforming, and preparing Apnea-ECG data for
dual ingestion into PostgreSQL and TimescaleDB.

Usage:
    python scripts/etl_pipeline.py --record a01 --output data/processed/

For bulk all-record execution, use:
    python scripts/run_low_disk_pipeline.py

The pipeline:
1. Extracts WFDB signals (.dat) and annotations (.apn, .qrs)
2. Generates synthetic timestamps (baseline + sample_index / sampling_rate)
3. Handles missing modalities (respiration signals for ECG-only records)
4. Outputs structured batches ready for database insertion
5. Logs all transformations for reproducibility
"""

import json
import logging
import math
import numpy as np
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
import argparse

try:
    import wfdb
except ImportError:
    raise ImportError("wfdb not installed. Run: pip install wfdb")

from tqdm import tqdm

# ============================================================================
# Configuration
# ============================================================================

RAW_DIR = Path("data/raw")
METADATA_FILE = Path("data/metadata/dataset_baseline.json")
BASELINE_TIMESTAMP = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)  # Per SG05 Architecture 3.1

# SG05 Ingestion Strategy, Section C: Fixed batch size of 100K rows
BATCH_SIZE = 100_000
SAMPLING_RATE_HZ = 100  # Standard for Apnea-ECG dataset
WINDOW_DURATION_SECONDS = 60
WINDOW_SAMPLE_COUNT = SAMPLING_RATE_HZ * WINDOW_DURATION_SECONDS

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SignalRow:
    """Single ECG/respiration signal sample."""
    recording_id: str
    recorded_at: datetime
    sample_index: int
    ecg_value: Optional[float]
    resp_c: Optional[float]
    resp_a: Optional[float]
    resp_n: Optional[float]
    spo2: Optional[float]

    def to_tuple(self):
        """Convert to database insert tuple."""
        return (
            self.recording_id,
            self.recorded_at,
            self.sample_index,
            self.ecg_value,
            self.resp_c,
            self.resp_a,
            self.resp_n,
            self.spo2,
        )


@dataclass
class ApneaEvent:
    """Minute-level apnea annotation."""
    recording_id: str
    minute_index: int
    recorded_at: datetime
    label: str  # Raw label from .apn file
    is_apnea: bool  # True if label indicates apnea event


@dataclass
class QRSEvent:
    """Heartbeat (QRS) annotation."""
    recording_id: str
    sample_index: int
    recorded_at: datetime


@dataclass
class ExtractionStats:
    """Summary statistics for a single record extraction."""
    record_name: str
    signal_rows: int
    apnea_events: int
    qrs_events: int
    duration_sec: float
    expected_samples: int
    has_respiration: bool
    has_apnea_annotations: bool
    has_qrs_annotations: bool
    signal_start_at: Optional[str]
    signal_end_at: Optional[str]
    apnea_start_at: Optional[str]
    apnea_end_at: Optional[str]
    qrs_start_at: Optional[str]
    qrs_end_at: Optional[str]
    window_rows: int
    annotated_window_rows: int
    non_finite_values_replaced: int
    record_level_modalities: Dict[str, Dict[str, Any]]
    errors: List[str]


# ============================================================================
# Core Extraction Functions
# ============================================================================

def load_metadata() -> dict:
    """Load dataset_baseline.json metadata."""
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


def resolve_signal_record_bases(record_name: str, metadata: dict) -> tuple[str, Optional[str]]:
    """Resolve the ECG and respiration WFDB bases used to read signal files."""
    record_meta = metadata.get(record_name, {})

    ecg_base = record_name
    resp_base = None

    if record_meta.get("has_respiration"):
        candidate = f"{record_name}r"
        if (RAW_DIR / f"{candidate}.hea").exists():
            resp_base = candidate

    if not (RAW_DIR / f"{ecg_base}.hea").exists():
        candidates: List[str] = []
        selected_header = record_meta.get("selected_header_file")
        if selected_header:
            candidates.append(Path(selected_header).stem)
        source_record = record_meta.get("source_record_name")
        if source_record:
            candidates.append(source_record)

        for base_name in candidates:
            if (RAW_DIR / f"{base_name}.hea").exists():
                ecg_base = base_name
                break
        else:
            raise FileNotFoundError(f"No ECG header file found for '{record_name}'.")

    return ecg_base, resp_base


def resolve_annotation_record_base(record_name: str, metadata: dict, ext: str) -> Optional[str]:
    """Resolve the WFDB base name for annotation files (.apn/.qrs)."""
    record_meta = metadata.get(record_name, {})
    ext = ext.lstrip(".")

    candidates: List[str] = []

    candidates.append(record_name)

    source_record = record_meta.get("source_record_name")
    if source_record:
        candidates.append(source_record)

    selected_header = record_meta.get("selected_header_file")
    if selected_header:
        candidates.append(Path(selected_header).stem)

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)

    for base_name in unique_candidates:
        if (RAW_DIR / f"{base_name}.{ext}").exists():
            return base_name

    return None


def _parse_apnea_label(ann: "wfdb.Annotation", idx: int) -> str:
    """Extract apnea label from WFDB annotation using aux_note first, then symbol."""
    label = ""
    if getattr(ann, "aux_note", None) and idx < len(ann.aux_note):
        label = (ann.aux_note[idx] or "").strip()

    if not label and getattr(ann, "symbol", None) and idx < len(ann.symbol):
        label = (ann.symbol[idx] or "").strip()

    return label


def create_timestamp(sample_index: int, sampling_rate_hz: int) -> datetime:
    """
    Generate synthetic timestamp.
    
    Per SG05 Architecture 3.1 (Synthetic Timestamps & Time-Based Indexing):
    - timestamp = baseline_time + (sample_index / sampling_rate_hz)
    - All 70 records use fixed baseline: 2000-01-01 00:00:00
    - For 100 Hz signals: advance by 10 milliseconds per row
    
    Example:
    - sample_index=0 → 2000-01-01 00:00:00.000
    - sample_index=1 → 2000-01-01 00:00:00.010
    - sample_index=100 → 2000-01-01 00:00:01.000
    
    Args:
        sample_index: Position in signal
        sampling_rate_hz: Sampling frequency (always 100 for Apnea-ECG)
    
    Returns:
        datetime object with synthetic timestamp
    """
    offset_seconds = sample_index / sampling_rate_hz
    return BASELINE_TIMESTAMP + timedelta(seconds=offset_seconds)


def to_json_ready(value: Any) -> Any:
    """Recursively convert dataclasses and datetimes to JSON-safe values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, list):
        return [to_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json_ready(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return to_json_ready(asdict(value))
    return value


def serialize_dataclass(instance: object) -> dict:
    return to_json_ready(asdict(instance))


def modality_enabled_map(has_respiration: bool) -> Dict[str, bool]:
    return {
        "ecg_value": True,
        "resp_c": has_respiration,
        "resp_a": has_respiration,
        "resp_n": has_respiration,
        "spo2": has_respiration,
    }


def init_modality_aggregates(enabled_map: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
    return {
        key: {
            "available": enabled_map[key],
            "count": 0,
            "missing_count": 0,
            "non_finite_replaced": 0,
            "sum": 0.0,
            "sum_squares": 0.0,
            "min": None,
            "max": None,
        }
        for key in enabled_map
    }


def update_modality_aggregate(bucket: Dict[str, Any], value: Optional[float], replaced_non_finite: bool) -> None:
    if not bucket["available"]:
        return
    if value is None:
        bucket["missing_count"] += 1
        if replaced_non_finite:
            bucket["non_finite_replaced"] += 1
        return

    bucket["count"] += 1
    bucket["sum"] += value
    bucket["sum_squares"] += value * value
    bucket["min"] = value if bucket["min"] is None else min(bucket["min"], value)
    bucket["max"] = value if bucket["max"] is None else max(bucket["max"], value)


def finalize_modality_aggregates(aggregates: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    finalized: Dict[str, Dict[str, Any]] = {}
    for key, bucket in aggregates.items():
        if not bucket["available"]:
            finalized[key] = {
                "available": False,
                "count": 0,
                "missing_count": 0,
                "non_finite_replaced": 0,
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "normalized_mean": None,
            }
            continue

        count = bucket["count"]
        mean = bucket["sum"] / count if count > 0 else None
        variance = None
        std = None
        if count > 1:
            variance = max((bucket["sum_squares"] / count) - (mean * mean), 0.0)
            std = math.sqrt(variance)

        finalized[key] = {
            "available": True,
            "count": count,
            "missing_count": bucket["missing_count"],
            "non_finite_replaced": bucket["non_finite_replaced"],
            "min": bucket["min"],
            "max": bucket["max"],
            "mean": mean,
            "std": std,
            "normalized_mean": None,
        }

    return finalized


def clean_signal_row(row: SignalRow) -> tuple[SignalRow, Dict[str, bool]]:
    replacements: Dict[str, bool] = {}
    cleaned_values: Dict[str, Optional[float]] = {}
    for key in ("ecg_value", "resp_c", "resp_a", "resp_n", "spo2"):
        value = getattr(row, key)
        replaced_non_finite = False
        if value is not None:
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                value = None
                replaced_non_finite = True
            else:
                value = numeric_value
        cleaned_values[key] = value
        replacements[key] = replaced_non_finite

    return (
        SignalRow(
            recording_id=row.recording_id,
            recorded_at=row.recorded_at,
            sample_index=row.sample_index,
            ecg_value=cleaned_values["ecg_value"],
            resp_c=cleaned_values["resp_c"],
            resp_a=cleaned_values["resp_a"],
            resp_n=cleaned_values["resp_n"],
            spo2=cleaned_values["spo2"],
        ),
        replacements,
    )


def empty_window_summary(record_name: str, minute_index: int, sampling_rate: int, enabled_map: Dict[str, bool]) -> Dict[str, Any]:
    sample_start_index = minute_index * WINDOW_DURATION_SECONDS * sampling_rate
    sample_end_index = sample_start_index + (WINDOW_DURATION_SECONDS * sampling_rate) - 1
    return {
        "recording_id": record_name,
        "minute_index": minute_index,
        "window_start_at": create_timestamp(sample_start_index, sampling_rate),
        "window_end_at": create_timestamp(sample_end_index, sampling_rate),
        "sample_start_index": sample_start_index,
        "sample_end_index": sample_end_index,
        "sample_count": 0,
        "apnea_label": None,
        "is_apnea": None,
        "qrs_count": 0,
        "modalities": init_modality_aggregates(enabled_map),
    }


def finalize_window_summaries(
    window_summaries: Dict[int, Dict[str, Any]],
    apnea_events: List[ApneaEvent],
    qrs_events: List[QRSEvent],
    sampling_rate: int,
    record_level_modalities: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    apnea_by_minute = {event.minute_index: event for event in apnea_events}
    qrs_counts: Dict[int, int] = {}
    for event in qrs_events:
        minute_index = event.sample_index // (sampling_rate * WINDOW_DURATION_SECONDS)
        qrs_counts[minute_index] = qrs_counts.get(minute_index, 0) + 1

    finalized_windows = []
    for minute_index in sorted(window_summaries.keys()):
        summary = window_summaries[minute_index]
        apnea_event = apnea_by_minute.get(minute_index)
        summary["apnea_label"] = apnea_event.label if apnea_event else None
        summary["is_apnea"] = apnea_event.is_apnea if apnea_event else None
        summary["qrs_count"] = qrs_counts.get(minute_index, 0)

        finalized_modalities = finalize_modality_aggregates(summary["modalities"])
        for key, stats in finalized_modalities.items():
            record_stats = record_level_modalities[key]
            if (
                stats["available"]
                and stats["mean"] is not None
                and record_stats["std"] not in (None, 0)
            ):
                stats["normalized_mean"] = (stats["mean"] - record_stats["mean"]) / record_stats["std"]
        summary["modalities"] = finalized_modalities
        finalized_windows.append(summary)

    return finalized_windows


def build_cleaning_log_markdown(summary: dict) -> str:
    return "\n".join([
        "# Cleaning And Transformation Log",
        "",
        "## Dataset-Specific Policies",
        "",
        "- Baseline timestamps are synthetic and fixed at `2000-01-01T00:00:00+00:00` because Apnea-ECG provides sample positions rather than real calendar timestamps.",
        "- Signals remain at the native 100 Hz sampling rate. No resampling is applied at the raw-signal level.",
        "- Segmentation is performed into fixed one-minute windows (6,000 samples at 100 Hz) so features align with minute-level apnea annotations.",
        "- ECG is always present. `Resp C`, `Resp A`, `Resp N`, and `SpO2` remain structurally null for ECG-only records.",
        "- Non-finite numeric values are replaced with null during ETL and counted in the transformation summary.",
        "- Learning records keep expert apnea labels when available. Test records intentionally keep apnea labels empty.",
        "- QRS annotations are retained for heart-rate style aggregation, but they are machine-generated and unaudited and should not be treated as ground truth labels.",
        "- c05 and c06 continue to share the same subject identifier to preserve the dataset note that they come from the same original recording.",
        "",
        "## Outputs",
        "",
        "- `signals_<record>.jsonl`: cleaned raw sample rows",
        "- `apnea_<record>.json`: minute-level apnea annotations filtered to the extracted sample span",
        "- `qrs_<record>.json`: QRS annotations filtered to the extracted sample span",
        "- `windows_<record>.json`: one-minute feature windows with per-modality summary statistics and normalized means",
        "- `transformation_summary.json`: machine-readable ETL totals and per-record wrangling summary",
        "- `extraction_stats.json`: per-record extraction statistics",
        "",
        "## Current Run Totals",
        "",
        f"- Records processed: {summary['record_count']}",
        f"- Signal rows: {summary['totals']['signal_rows']}",
        f"- Window rows: {summary['totals']['window_rows']}",
        f"- Annotated windows: {summary['totals']['annotated_window_rows']}",
        f"- Non-finite values replaced: {summary['totals']['non_finite_values_replaced']}",
        f"- Errors: {summary['totals']['error_count']}",
    ])


def first_and_last_iso(rows: List[object], attr_name: str) -> tuple[Optional[str], Optional[str]]:
    """Return first/last timestamp strings for extracted collections."""
    if not rows:
        return None, None

    first_value = getattr(rows[0], attr_name)
    last_value = getattr(rows[-1], attr_name)
    return first_value.isoformat(), last_value.isoformat()


def build_transformation_summary(
    metadata: dict,
    records: List[str],
    stats_list: List[ExtractionStats],
    max_samples: Optional[int],
) -> dict:
    """Build a repo-local transformation summary for downstream validation and reporting."""
    total_expected_samples = sum(stat.expected_samples for stat in stats_list)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_timestamp_utc": BASELINE_TIMESTAMP.isoformat(),
        "records_processed": records,
        "record_count": len(records),
        "max_samples": max_samples,
        "totals": {
            "expected_signal_rows": total_expected_samples,
            "signal_rows": sum(stat.signal_rows for stat in stats_list),
            "apnea_events": sum(stat.apnea_events for stat in stats_list),
            "qrs_events": sum(stat.qrs_events for stat in stats_list),
            "window_rows": sum(stat.window_rows for stat in stats_list),
            "annotated_window_rows": sum(stat.annotated_window_rows for stat in stats_list),
            "non_finite_values_replaced": sum(stat.non_finite_values_replaced for stat in stats_list),
            "duration_sec": sum(stat.duration_sec for stat in stats_list),
            "error_count": sum(len(stat.errors) for stat in stats_list),
        },
        "wrangling_policy": {
            "signal_sampling_rate_hz": SAMPLING_RATE_HZ,
            "window_duration_seconds": WINDOW_DURATION_SECONDS,
            "window_sample_count": WINDOW_SAMPLE_COUNT,
            "raw_resampling": "none",
            "signal_cleaning": "replace non-finite numeric values with null; preserve structural nulls for absent modalities",
            "normalization": "per-record z-score normalization applied to per-window modality means",
            "annotation_alignment": "one-minute windows align to apnea minute_index; QRS counts are aggregated into the same window size",
            "qrs_reliability_note": "QRS annotations are machine-generated and unaudited and remain feature-level support data, not ground truth.",
        },
        "records": [serialize_dataclass(stat) for stat in stats_list],
    }


def extract_signals(
    record_name: str,
    metadata: dict,
    batch_size: int = BATCH_SIZE,
    max_samples: Optional[int] = None,
) -> Iterator[List[SignalRow]]:
    """
    Extract and yield signal batches from WFDB .dat file.
    
    Per SG05 Ingestion Strategy, Section B (Transform):
    - Flatten raw data matrices into distinct rows
    - Each row: (recording_id, sample_index, recorded_at, ecg_value, resp_c, resp_a, resp_n, spo2)
    - Handle missing modalities: ECG-only records have resp/spo2 = NULL
    
    Per SG05 Ingestion Strategy, Section C (Load):
    - Batch size fixed at 100K rows for consistent performance
    
    Args:
        record_name: e.g., 'a01'
        metadata: Full dataset_baseline.json dict
        batch_size: Number of samples per batch (default 100K per SG05 spec)
    
    Yields:
        Lists of SignalRow objects (max 100K rows per batch)
    
    Raises:
        FileNotFoundError: If .dat file not found
    """
    record_meta = metadata[record_name]
    ecg_base, resp_base = resolve_signal_record_bases(record_name, metadata)
    record_path = str(RAW_DIR / ecg_base)
    sampling_rate = record_meta["sampling_rate_hz"]
    has_respiration = record_meta["has_respiration"]
    
    logger.info(
        f"Extracting signals: {record_name} (ecg_base={ecg_base}, resp_base={resp_base}, has_respiration={has_respiration})"
    )
    
    try:
        rec_ecg = wfdb.rdrecord(record_path)
        rec_resp = wfdb.rdrecord(str(RAW_DIR / resp_base)) if resp_base else None
    except Exception as e:
        logger.error(f"Failed to read record {record_name}: {e}")
        raise
    
    total_samples = rec_ecg.sig_len
    if rec_resp is not None:
        total_samples = min(total_samples, rec_resp.sig_len)
    if max_samples is not None:
        total_samples = min(total_samples, max_samples)

    batch = []
    
    for sample_idx in tqdm(range(total_samples), desc=f"Signals {record_name}"):
        recorded_at = create_timestamp(sample_idx, sampling_rate)
        
        # ECG is always channel 0
        ecg_value = float(rec_ecg.p_signal[sample_idx, 0]) if rec_ecg.p_signal is not None else None
        
        # Respiration/SpO2 (channels 1–4) only if available
        if has_respiration and rec_resp is not None and rec_resp.n_sig >= 4:
            resp_c = float(rec_resp.p_signal[sample_idx, 0])
            resp_a = float(rec_resp.p_signal[sample_idx, 1])
            resp_n = float(rec_resp.p_signal[sample_idx, 2])
            spo2 = float(rec_resp.p_signal[sample_idx, 3])
        else:
            resp_c = resp_a = resp_n = spo2 = None
        
        row = SignalRow(
            recording_id=record_name,
            recorded_at=recorded_at,
            sample_index=sample_idx,
            ecg_value=ecg_value,
            resp_c=resp_c,
            resp_a=resp_a,
            resp_n=resp_n,
            spo2=spo2,
        )
        
        batch.append(row)
        
        if len(batch) >= batch_size:
            yield batch
            batch = []
    
    if batch:
        yield batch


def extract_apnea_annotations(
    record_name: str,
    metadata: dict,
    max_samples: Optional[int] = None,
) -> List[ApneaEvent]:
    """
    Extract minute-level apnea annotations from .apn file.
    
    Per SG05 Ingestion Strategy, Section B (Transform):
    - Label mapping: Apnea string annotations ('A' or 'N') → boolean values (TRUE/FALSE)
    - This optimizes downstream SQL and ML querying
    
    Per SG05 Architecture 3.2 (Frequency Mismatch):
    - Annotations stored in separate table (1 row per minute, not 100 rows)
    - Prevents redundant storage (same label 6,000 times per minute)
    
    Args:
        record_name: e.g., 'a01'
        metadata: Full dataset_baseline.json dict
    
    Returns:
        List of ApneaEvent objects with is_apnea boolean
    """
    record_meta = metadata[record_name]
    has_annotations = record_meta["has_apnea_annotations"]
    sampling_rate = record_meta["sampling_rate_hz"]
    
    if not has_annotations:
        logger.info(f"No apnea annotations for {record_name}")
        return []
    
    ann_base = resolve_annotation_record_base(record_name, metadata, "apn")
    if ann_base is None:
        logger.warning(f"No .apn file found for {record_name}")
        return []

    try:
        ann = wfdb.rdann(str(RAW_DIR / ann_base), "apn")
    except Exception as e:
        logger.warning(f"Could not read apnea annotations for {record_name}: {e}")
        return []
    
    events = []
    for idx, sample_idx in enumerate(ann.sample):
        if max_samples is not None and sample_idx >= max_samples:
            continue
        minute_index = idx
        recorded_at = create_timestamp(sample_idx, sampling_rate)
        label = _parse_apnea_label(ann, idx)
        is_apnea = label.strip().lower() in {"a", "apnea", "1"}
        
        event = ApneaEvent(
            recording_id=record_name,
            minute_index=minute_index,
            recorded_at=recorded_at,
            label=label.strip() if label else "",
            is_apnea=is_apnea,
        )
        events.append(event)
    
    logger.info(f"Extracted {len(events)} apnea events from {record_name}")
    return events


def extract_qrs_annotations(
    record_name: str,
    metadata: dict,
    max_samples: Optional[int] = None,
) -> List[QRSEvent]:
    """
    Extract QRS (heartbeat) annotations from .qrs file.
    
    Args:
        record_name: e.g., 'a01'
        metadata: Full dataset_baseline.json dict
    
    Returns:
        List of QRSEvent objects
    """
    record_meta = metadata[record_name]
    has_qrs = record_meta["has_qrs_annotations"]
    sampling_rate = record_meta["sampling_rate_hz"]
    
    if not has_qrs:
        logger.info(f"No QRS annotations for {record_name}")
        return []
    
    ann_base = resolve_annotation_record_base(record_name, metadata, "qrs")
    if ann_base is None:
        logger.warning(f"No .qrs file found for {record_name}")
        return []

    try:
        ann = wfdb.rdann(str(RAW_DIR / ann_base), "qrs")
    except Exception as e:
        logger.warning(f"Could not read QRS annotations for {record_name}: {e}")
        return []
    
    events = []
    for sample_idx in ann.sample:
        if max_samples is not None and sample_idx >= max_samples:
            continue
        recorded_at = create_timestamp(sample_idx, sampling_rate)
        event = QRSEvent(
            recording_id=record_name,
            sample_index=sample_idx,
            recorded_at=recorded_at,
        )
        events.append(event)
    
    logger.info(f"Extracted {len(events)} QRS events from {record_name}")
    return events


# ============================================================================
# Pipeline Orchestration
# ============================================================================

def process_record(
    record_name: str,
    metadata: dict,
    output_dir: Path,
    max_samples: Optional[int] = None,
) -> ExtractionStats:
    """
    Extract, transform, and validate a single record (per SG05 ETL architecture).
    
    Per SG05 Ingestion Strategy:
    - Extract phase: Parse WFDB files (wfdb library)
    - Transform phase: Flatten to rows, generate timestamps, map labels
    - Intermediate output: JSONL files for later batch loading
    
    Outputs (ready for Phase 2 ingestion):
    - {output_dir}/signals_{record_name}.jsonl  (signal batches, 100K rows per batch)
    - {output_dir}/apnea_{record_name}.json     (apnea events with boolean labels)
    - {output_dir}/qrs_{record_name}.json       (QRS events with sample indices)
    
    Per SG05 Ingestion Strategy, Section C (FK Order):
    - Data will be loaded in order: subjects → recordings → signals → annotations
    - These intermediate files support that ordering
    
    Args:
        record_name: e.g., 'a01'
        metadata: Full dataset_baseline.json dict
        output_dir: Directory for intermediate outputs
    
    Returns:
        ExtractionStats summary
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = datetime.now()
    errors = []
    signal_count = 0
    record_meta = metadata[record_name]
    enabled_map = modality_enabled_map(bool(record_meta["has_respiration"]))
    record_level_aggregates = init_modality_aggregates(enabled_map)
    window_summaries: Dict[int, Dict[str, Any]] = {}
    non_finite_values_replaced = 0
    
    logger.info(f"Processing record: {record_name}")
    
    try:
        apnea_events = extract_apnea_annotations(record_name, metadata, max_samples=max_samples)
        qrs_events = extract_qrs_annotations(record_name, metadata, max_samples=max_samples)

        # Extract signals
        signal_output = output_dir / f"signals_{record_name}.jsonl"
        with open(signal_output, "w", encoding="utf-8") as f:
            for batch in extract_signals(record_name, metadata, max_samples=max_samples):
                for row in batch:
                    cleaned_row, replacements = clean_signal_row(row)
                    signal_count += 1
                    non_finite_values_replaced += sum(1 for replaced in replacements.values() if replaced)
                    minute_index = cleaned_row.sample_index // (record_meta["sampling_rate_hz"] * WINDOW_DURATION_SECONDS)
                    if minute_index not in window_summaries:
                        window_summaries[minute_index] = empty_window_summary(
                            record_name,
                            minute_index,
                            record_meta["sampling_rate_hz"],
                            enabled_map,
                        )
                    window_summaries[minute_index]["sample_count"] += 1

                    for key, replaced in replacements.items():
                        value = getattr(cleaned_row, key)
                        update_modality_aggregate(record_level_aggregates[key], value, replaced)
                        update_modality_aggregate(window_summaries[minute_index]["modalities"][key], value, replaced)

                    f.write(json.dumps(to_json_ready(cleaned_row)) + "\n")

        apnea_output = output_dir / f"apnea_{record_name}.json"
        with open(apnea_output, "w", encoding="utf-8") as f:
            json.dump([serialize_dataclass(event) for event in apnea_events], f, indent=2)

        qrs_output = output_dir / f"qrs_{record_name}.json"
        with open(qrs_output, "w", encoding="utf-8") as f:
            json.dump([serialize_dataclass(event) for event in qrs_events], f, indent=2)

        record_level_modalities = finalize_modality_aggregates(record_level_aggregates)
        windows = finalize_window_summaries(
            window_summaries,
            apnea_events,
            qrs_events,
            record_meta["sampling_rate_hz"],
            record_level_modalities,
        )
        windows_output = output_dir / f"windows_{record_name}.json"
        with open(windows_output, "w", encoding="utf-8") as f:
            json.dump(to_json_ready(windows), f, indent=2)
        
    except Exception as e:
        error_msg = f"Error processing {record_name}: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
    
    duration = (datetime.now() - start_time).total_seconds()
    signal_start_at, signal_end_at = first_and_last_iso(
        [type("SignalBounds", (), {"recorded_at": create_timestamp(0, record_meta["sampling_rate_hz"])})(),
         type("SignalBounds", (), {"recorded_at": create_timestamp(max(signal_count - 1, 0), record_meta["sampling_rate_hz"])})()]
        if signal_count > 0 else [],
        "recorded_at",
    )
    apnea_start_at, apnea_end_at = first_and_last_iso(apnea_events if 'apnea_events' in locals() else [], "recorded_at")
    qrs_start_at, qrs_end_at = first_and_last_iso(qrs_events if 'qrs_events' in locals() else [], "recorded_at")
    
    stats = ExtractionStats(
        record_name=record_name,
        signal_rows=signal_count,
        apnea_events=len(apnea_events) if 'apnea_events' in locals() else 0,
        qrs_events=len(qrs_events) if 'qrs_events' in locals() else 0,
        duration_sec=duration,
        expected_samples=signal_count,
        has_respiration=bool(record_meta["has_respiration"]),
        has_apnea_annotations=bool(record_meta["has_apnea_annotations"]),
        has_qrs_annotations=bool(record_meta["has_qrs_annotations"]),
        signal_start_at=signal_start_at,
        signal_end_at=signal_end_at,
        apnea_start_at=apnea_start_at,
        apnea_end_at=apnea_end_at,
        qrs_start_at=qrs_start_at,
        qrs_end_at=qrs_end_at,
        window_rows=len(windows) if 'windows' in locals() else 0,
        annotated_window_rows=sum(1 for window in windows if window["apnea_label"] is not None) if 'windows' in locals() else 0,
        non_finite_values_replaced=non_finite_values_replaced,
        record_level_modalities=record_level_modalities if 'record_level_modalities' in locals() else {},
        errors=errors,
    )
    
    logger.info(f"Completed {record_name}: {signal_count} signals, "
                f"{stats.apnea_events} apnea, {stats.qrs_events} QRS "
                f"({duration:.1f}s)")
    
    return stats


def process_all_records(
    metadata: dict,
    output_dir: Path,
    records: Optional[List[str]] = None,
    max_samples: Optional[int] = None,
) -> List[ExtractionStats]:
    """
    Extract all records (or subset).
    
    Args:
        metadata: Full dataset_baseline.json dict
        output_dir: Directory for intermediate outputs
        records: List of record names to process. If None, process all.
    
    Returns:
        List of ExtractionStats
    """
    if records is None:
        records = sorted(metadata.keys())
    
    stats_list = []
    
    for record_name in tqdm(records, desc="Processing records"):
        stats = process_record(record_name, metadata, output_dir, max_samples=max_samples)
        stats_list.append(stats)
    
    # Summarize
    total_signals = sum(s.signal_rows for s in stats_list)
    total_apnea = sum(s.apnea_events for s in stats_list)
    total_qrs = sum(s.qrs_events for s in stats_list)
    total_time = sum(s.duration_sec for s in stats_list)
    total_errors = sum(len(s.errors) for s in stats_list)
    
    logger.info(f"\n=== EXTRACTION SUMMARY ===")
    logger.info(f"Records processed: {len(stats_list)}")
    logger.info(f"Total signal rows: {total_signals:,}")
    logger.info(f"Total apnea events: {total_apnea:,}")
    logger.info(f"Total QRS events: {total_qrs:,}")
    logger.info(f"Total time: {total_time:.1f}s")
    logger.info(f"Errors: {total_errors}")
    
    summary = build_transformation_summary(metadata, records, stats_list, max_samples)
    summary_output = Path(output_dir) / "transformation_summary.json"
    with open(summary_output, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    logger.info(f"Transformation summary saved to {summary_output}")

    cleaning_log_output = Path(output_dir) / "cleaning_transformation_log.md"
    with open(cleaning_log_output, "w", encoding="utf-8") as handle:
        handle.write(build_cleaning_log_markdown(summary))
    logger.info(f"Cleaning log saved to {cleaning_log_output}")

    return stats_list


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract and transform a single Apnea-ECG record for inspection or smoke testing."
    )
    parser.add_argument(
        "--record",
        default=None,
        help="Single record to process (e.g., 'a01'). Bulk all-record runs must use scripts/run_low_disk_pipeline.py.",
    )
    parser.add_argument(
        "--output",
        default="data/processed",
        help="Output directory for intermediate files.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Optional cap on signal samples per record (useful for smoke tests).",
    )
    
    args = parser.parse_args()

    if not args.record:
        raise SystemExit(
            "Full materialization is no longer supported from scripts/etl_pipeline.py. "
            "Use scripts/run_low_disk_pipeline.py for staged all-record execution, "
            "or pass --record for a single-record smoke/debug run."
        )
    
    metadata = load_metadata()
    
    records = [args.record]
    
    invalid = [r for r in records if r not in metadata]
    if invalid:
        raise ValueError(f"Unknown record(s): {invalid}")

    stats_list = process_all_records(
        metadata,
        Path(args.output),
        records,
        max_samples=args.max_samples,
    )
    
    # Save statistics
    stats_output = Path(args.output) / "extraction_stats.json"
    with open(stats_output, "w", encoding="utf-8") as f:
        json.dump(
            [serialize_dataclass(stat) for stat in stats_list],
            f,
            indent=2,
        )
    logger.info(f"Extraction statistics saved to {stats_output}")


if __name__ == "__main__":
    main()
