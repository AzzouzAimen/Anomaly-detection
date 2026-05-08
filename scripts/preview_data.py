from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"
TEXT_EXTENSIONS = [".hea", ".apn", ".qrs", ".xws", ".txt"]


def read_text_head(file_path: Path, max_lines: int) -> list[str]:
    lines: list[str] = []
    if not file_path.exists():
        return lines
    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        for _, line in zip(range(max_lines), handle):
            lines.append(line.rstrip("\n"))
    return lines


def print_section(title: str, lines: Iterable[str]) -> None:
    print(f"\n=== {title} ===")
    if not lines:
        print("(no content)")
        return
    for line in lines:
        print(line)


def preview_text_files(record: str, raw_dir: Path, max_lines: int) -> None:
    for ext in TEXT_EXTENSIONS:
        file_path = raw_dir / f"{record}{ext}"
        lines = read_text_head(file_path, max_lines)
        print_section(file_path.name, lines)


def preview_signals(record: str, raw_dir: Path, max_samples: int, plot: bool) -> None:
    try:
        import wfdb  # type: ignore
    except ImportError:
        print("\nwfdb is not installed. Install it with: pip install wfdb")
        return

    record_path = str(raw_dir / record)
    try:
        rec = wfdb.rdrecord(record_path)
    except Exception as exc:
        print(f"\nCould not read record {record}: {exc}")
        return

    print("\n=== Signal summary ===")
    print(f"Channels: {rec.n_sig}")
    print(f"Sample rate: {rec.fs} Hz")
    print(f"Total samples: {rec.sig_len}")
    print("Channel names:", ", ".join(rec.sig_name))

    if rec.p_signal is None:
        print("No physical signal data available.")
        return

    sample_count = min(max_samples, rec.p_signal.shape[0])
    print("\nFirst samples (per channel):")
    for idx in range(sample_count):
        row = ", ".join(f"{value:.6f}" for value in rec.p_signal[idx])
        print(f"{idx:6d}: {row}")

    if plot:
        try:
            import matplotlib.pyplot as plt  # type: ignore
        except ImportError:
            print("\nmatplotlib is not installed. Install it with: pip install matplotlib")
            return

        plt.figure(figsize=(10, 4))
        plt.plot(rec.p_signal[: min(1000, rec.sig_len), 0])
        plt.title(f"{record} - Channel 1 (first 1000 samples)")
        plt.xlabel("Sample")
        plt.ylabel("Amplitude")
        plt.tight_layout()
        plt.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview Apnea-ECG dataset files.")
    parser.add_argument("--record", default="a01", help="Record ID (e.g., a01, b01).")
    parser.add_argument(
        "--raw-dir",
        default=str(DEFAULT_RAW_DIR),
        help="Path to data/raw directory.",
    )
    parser.add_argument("--lines", type=int, default=20, help="Lines to show from text files.")
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Number of signal samples to print.",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Plot first channel (requires matplotlib).",
    )
    parser.add_argument(
        "--skip-signal",
        action="store_true",
        help="Skip reading .dat signals (text preview only).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    record = args.record

    if not raw_dir.exists():
        print(f"Raw data directory not found: {raw_dir}")
        return

    preview_text_files(record, raw_dir, args.lines)

    if not args.skip_signal:
        preview_signals(record, raw_dir, args.samples, args.plot)


if __name__ == "__main__":
    main()
