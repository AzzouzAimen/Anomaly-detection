# Cleaning And Transformation Log

## Dataset-Specific Policies

- Baseline timestamps are synthetic and fixed at `2000-01-01T00:00:00+00:00` because Apnea-ECG provides sample positions rather than real calendar timestamps.
- Signals remain at the native 100 Hz sampling rate. No resampling is applied at the raw-signal level.
- Segmentation is performed into fixed one-minute windows (6,000 samples at 100 Hz) so features align with minute-level apnea annotations.
- ECG is always present. `Resp C`, `Resp A`, `Resp N`, and `SpO2` remain structurally null for ECG-only records.
- Non-finite numeric values are replaced with null during ETL and counted in the transformation summary.
- Learning records keep expert apnea labels when available. Test records intentionally keep apnea labels empty.
- QRS annotations are retained for heart-rate style aggregation, but they are machine-generated and unaudited and should not be treated as ground truth labels.
- c05 and c06 continue to share the same subject identifier to preserve the dataset note that they come from the same original recording.

## Outputs

- `signals_<record>.jsonl`: cleaned raw sample rows
- `apnea_<record>.json`: minute-level apnea annotations filtered to the extracted sample span
- `qrs_<record>.json`: QRS annotations filtered to the extracted sample span
- `windows_<record>.json`: one-minute feature windows with per-modality summary statistics and normalized means
- `transformation_summary.json`: machine-readable ETL totals and per-record wrangling summary
- `extraction_stats.json`: per-record extraction statistics

## Current Run Totals

- Records processed: 70
- Signal rows: 206522368
- Window rows: 34452
- Annotated windows: 34313
- Non-finite values replaced: 3557
- Errors: 0