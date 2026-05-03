from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DOWNLOAD_PATH = REPO_ROOT / "physionet.org" / "files" / "apnea-ecg" / "1.0.0"
RAW_DATA_PATH = REPO_ROOT / "data" / "raw"
METADATA_PATH = REPO_ROOT / "data" / "metadata"

EXPECTED_EXTENSIONS = {".dat", ".hea", ".apn", ".qrs", ".xws", ".txt"}


def create_directories() -> None:
    RAW_DATA_PATH.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.mkdir(parents=True, exist_ok=True)


def find_download_path() -> Path:
    if DEFAULT_DOWNLOAD_PATH.exists():
        return DEFAULT_DOWNLOAD_PATH

    candidates = list(REPO_ROOT.glob("**/apnea-ecg/1.0.0"))
    if candidates:
        return candidates[0]

    print("Could not find downloaded dataset.")
    print("Expected path:")
    print(DEFAULT_DOWNLOAD_PATH)
    sys.exit(1)


def move_dataset_files(source_path: Path) -> None:
    files = [p for p in source_path.iterdir() if p.is_file()]

    if not files:
        existing_raw_files = [p for p in RAW_DATA_PATH.iterdir() if p.is_file()]
        if existing_raw_files:
            print(f"No files found in {source_path}")
            print(f"Detected existing files in {RAW_DATA_PATH}. Skipping move step.")
            return

        print(f"No files found in {source_path}")
        sys.exit(1)

    moved = 0
    skipped = 0

    for file_path in files:
        destination = RAW_DATA_PATH / file_path.name

        if file_path.suffix not in EXPECTED_EXTENSIONS:
            skipped += 1
            continue

        if destination.exists():
            skipped += 1
            continue

        shutil.move(str(file_path), str(destination))
        moved += 1

    print(f"Moved files: {moved}")
    print(f"Skipped files: {skipped}")


def count_records() -> None:
    header_files = sorted(RAW_DATA_PATH.glob("*.hea"))
    dat_files = sorted(RAW_DATA_PATH.glob("*.dat"))
    apnea_files = sorted(RAW_DATA_PATH.glob("*.apn"))
    qrs_files = sorted(RAW_DATA_PATH.glob("*.qrs"))

    print("\nDataset summary:")
    print(f".hea files: {len(header_files)}")
    print(f".dat files: {len(dat_files)}")
    print(f".apn files: {len(apnea_files)}")
    print(f".qrs files: {len(qrs_files)}")

    if len(header_files) == 0:
        print("\nWarning: no .hea files found. Dataset may not be organized correctly.")

    records = sorted({p.stem for p in header_files})
    print(f"Detected records from .hea files: {len(records)}")


def cleanup_empty_physionet_folder() -> None:
    physionet_root = REPO_ROOT / "physionet.org"

    try:
        if physionet_root.exists():
            shutil.rmtree(physionet_root)
            print("\nRemoved temporary physionet.org folder.")
    except Exception as exc:
        print(f"\nCould not remove physionet.org folder: {exc}")


def main() -> None:
    create_directories()

    source_path = find_download_path()
    print(f"Found dataset at: {source_path}")

    move_dataset_files(source_path)
    count_records()
    cleanup_empty_physionet_folder()

    print("\nDataset organization complete.")
    print(f"Raw files are now in: {RAW_DATA_PATH}")


if __name__ == "__main__":
    main()