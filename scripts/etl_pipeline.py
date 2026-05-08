#!/usr/bin/env python3
"""
Sprint 2 ETL Pipeline

Core module for extracting, transforming, and preparing Apnea-ECG data for
dual ingestion into PostgreSQL and TimescaleDB.

Usage:
    python scripts/etl_pipeline.py --record a01 --output data/processed/

The pipeline:
1. Extracts WFDB signals (.dat) and annotations (.apn, .qrs)
2. Generates synthetic timestamps (baseline + sample_index / sampling_rate)
3. Handles missing modalities (respiration signals for ECG-only records)
4. Outputs structured batches ready for database insertion
5. Logs all transformations for reproducibility
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
import argparse

try:
    import wfdb
except ImportError:
    raise ImportError("wfdb not installed. Run: pip install wfdb")

import pandas as pd
import numpy as np
from tqdm import tqdm

# ============================================================================
# Configuration
# ============================================================================

RAW_DIR = Path("data/raw")
METADATA_FILE = Path("data/metadata/dataset_baseline.json")
BASELINE_TIMESTAMP = datetime(2000, 1, 1, 0, 0, 0)  # Per SG05 Architecture 3.1

# SG05 Ingestion Strategy, Section C: Fixed batch size of 100K rows
BATCH_SIZE = 100_000
SAMPLING_RATE_HZ = 100  # Standard for Apnea-ECG dataset

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
    errors: List[str]


# ============================================================================
# Core Extraction Functions
# ============================================================================

def load_metadata() -> dict:
    """Load dataset_baseline.json metadata."""
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


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


def extract_signals(
    record_name: str,
    metadata: dict,
    batch_size: int = BATCH_SIZE,
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
    record_path = str(RAW_DIR / record_name)
    sampling_rate = record_meta["sampling_rate_hz"]
    has_respiration = record_meta["has_respiration"]
    
    logger.info(f"Extracting signals: {record_name} (has_respiration={has_respiration})")
    
    try:
        rec = wfdb.rdrecord(record_path)
    except Exception as e:
        logger.error(f"Failed to read record {record_name}: {e}")
        raise
    
    total_samples = rec.sig_len
    batch = []
    
    for sample_idx in tqdm(range(total_samples), desc=f"Signals {record_name}"):
        recorded_at = create_timestamp(sample_idx, sampling_rate)
        
        # ECG is always channel 0
        ecg_value = float(rec.p_signal[sample_idx, 0]) if rec.p_signal is not None else None
        
        # Respiration/SpO2 (channels 1–4) only if available
        if has_respiration and rec.n_sig >= 5:
            resp_c = float(rec.p_signal[sample_idx, 1])
            resp_a = float(rec.p_signal[sample_idx, 2])
            resp_n = float(rec.p_signal[sample_idx, 3])
            spo2 = float(rec.p_signal[sample_idx, 4])
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
    
    try:
        ann = wfdb.rdann(str(RAW_DIR / record_name), "apn")
    except Exception as e:
        logger.warning(f"Could not read apnea annotations for {record_name}: {e}")
        return []
    
    events = []
    for idx, (sample_idx, label) in enumerate(zip(ann.sample, ann.aux_note)):
        minute_index = idx
        recorded_at = create_timestamp(sample_idx, sampling_rate)
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
    
    try:
        ann = wfdb.rdann(str(RAW_DIR / record_name), "qrs")
    except Exception as e:
        logger.warning(f"Could not read QRS annotations for {record_name}: {e}")
        return []
    
    events = []
    for sample_idx in ann.sample:
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
    
    logger.info(f"Processing record: {record_name}")
    
    try:
        # Extract signals
        signal_output = output_dir / f"signals_{record_name}.jsonl"
        with open(signal_output, "w") as f:
            for batch in extract_signals(record_name, metadata):
                signal_count += len(batch)
                for row in batch:
                    f.write(json.dumps(asdict(row), default=str) + "\n")
        
        # Extract annotations
        apnea_events = extract_apnea_annotations(record_name, metadata)
        apnea_output = output_dir / f"apnea_{record_name}.json"
        with open(apnea_output, "w") as f:
            json.dump([asdict(e) for e in apnea_events], f, indent=2, default=str)
        
        qrs_events = extract_qrs_annotations(record_name, metadata)
        qrs_output = output_dir / f"qrs_{record_name}.json"
        with open(qrs_output, "w") as f:
            json.dump([asdict(e) for e in qrs_events], f, indent=2, default=str)
        
    except Exception as e:
        error_msg = f"Error processing {record_name}: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
    
    duration = (datetime.now() - start_time).total_seconds()
    
    stats = ExtractionStats(
        record_name=record_name,
        signal_rows=signal_count,
        apnea_events=len(apnea_events) if 'apnea_events' in locals() else 0,
        qrs_events=len(qrs_events) if 'qrs_events' in locals() else 0,
        duration_sec=duration,
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
        stats = process_record(record_name, metadata, output_dir)
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
    
    return stats_list


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract and transform Apnea-ECG dataset for database ingestion."
    )
    parser.add_argument(
        "--record",
        default=None,
        help="Single record to process (e.g., 'a01'). If None, process all.",
    )
    parser.add_argument(
        "--output",
        default="data/processed",
        help="Output directory for intermediate files.",
    )
    
    args = parser.parse_args()
    
    metadata = load_metadata()
    
    records = [args.record] if args.record else None
    
    stats_list = process_all_records(metadata, Path(args.output), records)
    
    # Save statistics
    stats_output = Path(args.output) / "extraction_stats.json"
    with open(stats_output, "w") as f:
        json.dump(
            [asdict(s) for s in stats_list],
            f,
            indent=2,
        )
    logger.info(f"Extraction statistics saved to {stats_output}")


if __name__ == "__main__":
    main()
