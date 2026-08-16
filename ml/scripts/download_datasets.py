#!/usr/bin/env python3
"""Dataset acquisition and verification for BridgeTalk.

BridgeTalk trains only on **public datasets**. Nothing in this file, or
anywhere else in the repository, records gesture data from a webcam to train a
model. See ml/README.md for why that constraint matters.

Two ways to get the data:

  1. **Manual (recommended, no credentials needed).** Download the dataset from
     Kaggle in your browser, unzip it into ml/data/raw/, then run --verify.
  2. **Kaggle API (optional convenience).** If you have ~/.kaggle/kaggle.json
     set up, --download fetches it for you.

Either way, --verify is the gate: it checks the folder layout, counts images
per class, and prints PASS or FAIL with an actionable reason.

Usage
-----
    python ml/scripts/download_datasets.py --verify
    python ml/scripts/download_datasets.py --verify --dataset static
    python ml/scripts/download_datasets.py --layout          # show what it found
    python ml/scripts/download_datasets.py --download --dataset static
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# This file lives at ml/scripts/download_datasets.py, so the repository root is
# two parents up. Deriving it this way means the script works from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "ml" / "data" / "raw"

# ANSI colours, disabled when output is piped to a file or another program.
_TTY = sys.stdout.isatty()
BOLD = "\033[1m" if _TTY else ""
GREEN = "\033[32m" if _TTY else ""
YELLOW = "\033[33m" if _TTY else ""
RED = "\033[31m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
RESET = "\033[0m" if _TTY else ""

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


# ---------------------------------------------------------------------------
# Dataset definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSpec:
    """Everything this script needs to know about one dataset."""

    key: str
    title: str
    kaggle_slug: str
    url: str
    kind: str  # "images" | "videos"
    expected_dir: Path
    citation: str
    licence: str
    # Class folder names we require. Empty for video datasets, whose classes
    # come from a metadata JSON rather than from folder names.
    classes: tuple[str, ...] = ()
    min_per_class: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


# Model A — the primary deliverable.
# 29 classes: the 26 letters, plus `space`, `del` and a neutral `nothing`.
# The neutral class matters: without it the model has no way to say "that is
# not a letter" and will confidently classify a hand scratching a nose as a C.
STATIC_CLASSES = tuple(chr(c) for c in range(ord("A"), ord("Z") + 1)) + ("del", "nothing", "space")

ASL_ALPHABET = DatasetSpec(
    key="static",
    title="ASL Alphabet (static fingerspelling)",
    kaggle_slug="grassknoted/asl-alphabet",
    url="https://www.kaggle.com/datasets/grassknoted/asl-alphabet",
    kind="images",
    expected_dir=RAW_DIR / "asl_alphabet",
    citation="Akash. ASL Alphabet. Kaggle, 2018.",
    licence="GPL 2 (per the dataset's Kaggle page) — research/education use",
    classes=STATIC_CLASSES,
    # The full dataset ships 3000 images per class. We only need a fraction of
    # that (extraction defaults to 1500/class), so the bar for "usable" is set
    # well below 3000 — a partial download is still trainable.
    min_per_class=200,
    notes=(
        "~87,000 images, 200x200 px, 29 classes, ~1.1 GB.",
        "Trains Model A: a single-frame MLP over 63 normalised landmark floats.",
    ),
)

# Model B — stretch goal. Word-level signs are genuinely harder from public
# data; see ml/README.md for the honest accuracy expectations.
WLASL = DatasetSpec(
    key="dynamic",
    title="WLASL processed (dynamic word signs)",
    kaggle_slug="risangbaskoro/wlasl-processed",
    url="https://www.kaggle.com/datasets/risangbaskoro/wlasl-processed",
    kind="videos",
    expected_dir=RAW_DIR / "wlasl",
    citation=(
        "Li, D., Rodriguez, C., Yu, X., Li, H. Word-level Deep Sign Language "
        "Recognition from Video: A New Large-scale Dataset and Methods "
        "Comparison. WACV 2020."
    ),
    licence="Research use, per the WLASL project terms",
    min_per_class=0,
    notes=(
        "~2,000 glosses as .mp4 clips plus WLASL_v0.3.json metadata, a few GB.",
        "We use only the 20 glosses with the most samples (WLASL-20).",
        "STRETCH GOAL — attempt only after Model A works.",
    ),
)

DATASETS: dict[str, DatasetSpec] = {ASL_ALPHABET.key: ASL_ALPHABET, WLASL.key: WLASL}


# ---------------------------------------------------------------------------
# Layout discovery
# ---------------------------------------------------------------------------


def find_class_root(search_root: Path, required: tuple[str, ...], max_depth: int = 4) -> Path | None:
    """Locate the directory that actually holds the class folders.

    Unzipping a Kaggle archive rarely produces the layout you expect. The ASL
    Alphabet zip in particular nests the same name twice —
    `asl_alphabet_train/asl_alphabet_train/A/` — and people also unzip it one
    level higher or lower than intended.

    Rather than demanding one exact path and failing on a technicality, this
    walks down from `search_root` looking for the first directory containing
    most of the required class folders. Being tolerant here removes the single
    most common reason this step fails for someone following the README.
    """
    if not search_root.is_dir():
        return None

    required_set = {name.lower() for name in required}
    # Accept a directory holding at least 80% of the expected classes, so a
    # partially-extracted archive is still detected and reported honestly
    # rather than silently ignored.
    threshold = max(1, int(len(required_set) * 0.8))

    frontier = [(search_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)

        try:
            children = [child for child in directory.iterdir() if child.is_dir()]
        except PermissionError:
            continue

        names = {child.name.lower() for child in children}
        if len(names & required_set) >= threshold:
            return directory

        if depth < max_depth:
            frontier.extend((child, depth + 1) for child in children)

    return None


def count_files(directory: Path, suffixes: set[str]) -> int:
    """Count files with the given extensions, one level deep."""
    if not directory.is_dir():
        return 0
    return sum(1 for item in directory.iterdir() if item.suffix.lower() in suffixes)


def find_videos_root(search_root: Path, max_depth: int = 4) -> Path | None:
    """Find the directory holding WLASL's .mp4 clips."""
    if not search_root.is_dir():
        return None

    frontier = [(search_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        if count_files(directory, VIDEO_SUFFIXES) >= 10:
            return directory
        if depth < max_depth:
            try:
                frontier.extend((c, depth + 1) for c in directory.iterdir() if c.is_dir())
            except PermissionError:
                continue
    return None


def find_metadata_json(search_root: Path) -> Path | None:
    """Find WLASL_v0.3.json (or a same-shaped file) anywhere under the root."""
    if not search_root.is_dir():
        return None
    for candidate in sorted(search_root.rglob("*.json")):
        name = candidate.name.lower()
        if "wlasl" in name or name.startswith("nslt"):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _print_manual_instructions(spec: DatasetSpec) -> None:
    """Explain exactly what to download and where to put it."""
    print(f"\n{BOLD}How to fix this{RESET}")
    print(f"  1. Open {spec.url}")
    print("  2. Sign in to Kaggle and click Download (accept the terms if prompted).")
    print(f"  3. Unzip the archive into: {DIM}{spec.expected_dir}{RESET}")
    print("  4. Re-run:  python ml/scripts/download_datasets.py --verify")
    print()
    print(f"{BOLD}Expected layout{RESET} (extra nesting is fine — this script finds it):")
    if spec.kind == "images":
        print(f"  {spec.expected_dir.relative_to(REPO_ROOT)}/")
        print("    ├── A/          A1.jpg, A2.jpg, ...")
        print("    ├── B/")
        print("    ├── ...")
        print("    ├── Z/")
        print("    ├── del/")
        print("    ├── nothing/")
        print("    └── space/")
    else:
        print(f"  {spec.expected_dir.relative_to(REPO_ROOT)}/")
        print("    ├── videos/         00335.mp4, 00336.mp4, ...")
        print("    └── WLASL_v0.3.json")


def verify_images(spec: DatasetSpec, verbose: bool = True) -> bool:
    """Verify an image-classification dataset and print a per-class table."""
    print(f"\n{BOLD}{spec.title}{RESET}")
    print(f"  {DIM}source:  {spec.url}{RESET}")
    print(f"  {DIM}licence: {spec.licence}{RESET}")
    print(f"  {DIM}looking in: {spec.expected_dir}{RESET}")

    if not spec.expected_dir.exists():
        print(f"\n{RED}  FAIL — folder does not exist.{RESET}")
        _print_manual_instructions(spec)
        return False

    class_root = find_class_root(spec.expected_dir, spec.classes)
    if class_root is None:
        print(f"\n{RED}  FAIL — folder exists but no class subfolders (A, B, C, ...) found.{RESET}")
        try:
            present = sorted(p.name for p in spec.expected_dir.iterdir())[:12]
            print(f"  {DIM}what is actually there: {present}{RESET}")
        except OSError:
            pass
        _print_manual_instructions(spec)
        return False

    if class_root != spec.expected_dir:
        relative = class_root.relative_to(spec.expected_dir)
        print(f"  {DIM}found class folders nested at: ./{relative}{RESET}")

    # --- per-class counts ---------------------------------------------------
    counts: dict[str, int] = {}
    for class_name in spec.classes:
        directory = class_root / class_name
        if not directory.is_dir():
            # Kaggle folder names are case-sensitive on Linux/macOS; try a
            # case-insensitive match before declaring the class missing.
            matches = [
                child
                for child in class_root.iterdir()
                if child.is_dir() and child.name.lower() == class_name.lower()
            ]
            directory = matches[0] if matches else directory
        counts[class_name] = count_files(directory, IMAGE_SUFFIXES)

    total = sum(counts.values())
    missing = [name for name, count in counts.items() if count == 0]
    thin = [name for name, count in counts.items() if 0 < count < spec.min_per_class]

    if verbose:
        print(f"\n  {BOLD}images per class{RESET}")
        columns = 6
        names = list(spec.classes)
        for row_start in range(0, len(names), columns):
            cells = []
            for name in names[row_start : row_start + columns]:
                count = counts[name]
                colour = RED if count == 0 else (YELLOW if count < spec.min_per_class else GREEN)
                cells.append(f"{colour}{name:>7}: {count:>5}{RESET}")
            print("   " + "  ".join(cells))

    print(f"\n  total images: {BOLD}{total:,}{RESET} across {len(spec.classes)} classes")

    # --- verdict ------------------------------------------------------------
    if missing:
        print(f"\n{RED}  FAIL — {len(missing)} class folder(s) empty or missing: {missing}{RESET}")
        print(f"  {DIM}All 29 classes are needed. 'nothing' especially: it is the neutral{RESET}")
        print(f"  {DIM}class that lets the model say \"that is not a letter\".{RESET}")
        _print_manual_instructions(spec)
        return False

    if thin:
        print(f"\n{YELLOW}  PASS WITH WARNING — thin classes (<{spec.min_per_class}): {thin}{RESET}")
        print(f"  {DIM}Training will work, but these classes will be weaker. Extraction{RESET}")
        print(f"  {DIM}balances classes down to the smallest, so accuracy will suffer.{RESET}")
        return True

    print(f"\n{GREEN}  PASS — all {len(spec.classes)} classes present and populated.{RESET}")
    return True


def verify_videos(spec: DatasetSpec) -> bool:
    """Verify the WLASL video dataset."""
    print(f"\n{BOLD}{spec.title}{RESET}")
    print(f"  {DIM}source:  {spec.url}{RESET}")
    print(f"  {DIM}licence: {spec.licence}{RESET}")
    print(f"  {DIM}looking in: {spec.expected_dir}{RESET}")

    if not spec.expected_dir.exists():
        print(f"\n{YELLOW}  SKIP — folder does not exist.{RESET}")
        print(f"  {DIM}This is the STRETCH goal. Model A does not need it.{RESET}")
        _print_manual_instructions(spec)
        return False

    videos_root = find_videos_root(spec.expected_dir)
    metadata = find_metadata_json(spec.expected_dir)

    if videos_root is None:
        print(f"\n{RED}  FAIL — no folder containing .mp4 clips found.{RESET}")
        _print_manual_instructions(spec)
        return False

    video_count = count_files(videos_root, VIDEO_SUFFIXES)
    print(f"  {DIM}videos at: ./{videos_root.relative_to(spec.expected_dir)}{RESET}")
    print(f"\n  video files: {BOLD}{video_count:,}{RESET}")

    if metadata is None:
        print(f"\n{RED}  FAIL — no WLASL metadata JSON found.{RESET}")
        print(f"  {DIM}Without it we cannot map a video file to the word it signs,{RESET}")
        print(f"  {DIM}and cannot split by signer.{RESET}")
        _print_manual_instructions(spec)
        return False

    print(f"  metadata:    {metadata.name}")
    try:
        with metadata.open(encoding="utf-8") as handle:
            entries = json.load(handle)
        if isinstance(entries, list):
            print(f"  glosses:     {BOLD}{len(entries):,}{RESET}")
    except (json.JSONDecodeError, OSError) as exc:
        print(f"\n{RED}  FAIL — metadata JSON could not be read: {exc}{RESET}")
        return False

    print(f"\n{GREEN}  PASS — videos and metadata present.{RESET}")
    return True


def verify(spec: DatasetSpec) -> bool:
    return verify_images(spec) if spec.kind == "images" else verify_videos(spec)


# ---------------------------------------------------------------------------
# Optional Kaggle API download
# ---------------------------------------------------------------------------


def download(spec: DatasetSpec) -> bool:
    """Download via the Kaggle API, if credentials are configured.

    Entirely optional. Every failure below prints a human-readable explanation
    and the manual alternative — never a raw traceback, which is useless to
    someone who has never used the Kaggle CLI.
    """
    token = Path.home() / ".kaggle" / "kaggle.json"
    if not token.is_file():
        print(f"\n{YELLOW}  No Kaggle API token at {token}.{RESET}")
        print(f"  {DIM}The API route needs one. Downloading manually is fine —{RESET}")
        print(f"  {DIM}--verify does not care how the files got there.{RESET}")
        _print_manual_instructions(spec)
        return False

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        print(f"\n{RED}  The `kaggle` package is not installed.{RESET}")
        print(f"  {DIM}Run: pip install -r backend/requirements.txt{RESET}")
        return False

    spec.expected_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{BOLD}Downloading {spec.kaggle_slug}{RESET} → {spec.expected_dir}")
    print(f"  {DIM}This is a large download and will take a while.{RESET}")

    try:
        api = KaggleApi()
        api.authenticate()
        api.dataset_download_files(spec.kaggle_slug, path=str(spec.expected_dir), unzip=True)
    except Exception as exc:  # noqa: BLE001 - surface any failure as plain English
        message = str(exc)
        print(f"\n{RED}  Download failed.{RESET}")
        if "403" in message or "Forbidden" in message:
            print("  Cause: you have not accepted this dataset's terms on Kaggle.")
            print(f"  Fix:   open {spec.url}, sign in, and accept the terms.")
        elif "401" in message or "Unauthorized" in message:
            print("  Cause: your API token is missing, stale or invalid.")
            print("  Fix:   Kaggle → Settings → API → Create New Token, then move")
            print("         kaggle.json to ~/.kaggle/ and run chmod 600 on it.")
        elif "404" in message:
            print(f"  Cause: dataset {spec.kaggle_slug} not found — it may have been renamed.")
            print(f"  Fix:   check {spec.url} in a browser.")
        else:
            print(f"  Details: {message}")
        _print_manual_instructions(spec)
        return False

    print(f"{GREEN}  Download complete.{RESET}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def show_layout() -> None:
    """Print what is currently under ml/data/raw — a debugging aid."""
    print(f"\n{BOLD}Contents of {RAW_DIR.relative_to(REPO_ROOT)}{RESET}")
    if not RAW_DIR.is_dir():
        print(f"  {RED}(does not exist){RESET}")
        return

    entries = sorted(p for p in RAW_DIR.iterdir() if p.name != ".gitkeep")
    if not entries:
        print(f"  {DIM}(empty){RESET}")
        return

    for entry in entries:
        if entry.is_dir():
            children = sorted(c for c in entry.iterdir())
            preview = ", ".join(c.name for c in children[:8])
            more = f", … (+{len(children) - 8} more)" if len(children) > 8 else ""
            print(f"  {entry.name}/  {DIM}→ {preview}{more}{RESET}")
        else:
            size_mb = entry.stat().st_size / (1024 * 1024)
            print(f"  {entry.name}  {DIM}({size_mb:.1f} MB){RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire and verify BridgeTalk's public training datasets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verify", action="store_true", help="check the datasets on disk")
    parser.add_argument("--download", action="store_true", help="fetch via the Kaggle API")
    parser.add_argument("--layout", action="store_true", help="list what is in ml/data/raw")
    parser.add_argument(
        "--dataset",
        choices=["static", "dynamic", "all"],
        default="all",
        help="static = ASL Alphabet (Model A), dynamic = WLASL (Model B, stretch)",
    )
    args = parser.parse_args()

    if not (args.verify or args.download or args.layout):
        parser.print_help()
        return 0

    if args.layout:
        show_layout()
        return 0

    selected = [DATASETS[args.dataset]] if args.dataset != "all" else list(DATASETS.values())

    if args.download:
        for spec in selected:
            download(spec)

    if args.verify:
        print(f"{BOLD}BridgeTalk dataset verification{RESET}")
        print(f"{DIM}All training data is public. No self-recorded data is used.{RESET}")

        results = {spec.key: verify(spec) for spec in selected}

        print(f"\n{BOLD}{'=' * 62}{RESET}")
        for spec in selected:
            passed = results[spec.key]
            # Model B is a stretch goal, so its absence is not a build failure.
            if passed:
                label = f"{GREEN}PASS{RESET}"
            elif spec.key == "dynamic":
                label = f"{YELLOW}SKIP (stretch goal){RESET}"
            else:
                label = f"{RED}FAIL{RESET}"
            print(f"  {label}  {spec.title}")
        print(f"{BOLD}{'=' * 62}{RESET}")

        # Only Model A's dataset is required to proceed.
        required_ok = results.get("static", True)
        if required_ok:
            print(f"\n{GREEN}Ready for Phase 3 extraction.{RESET}")
            print(f"  {DIM}Next: python ml/scripts/extract_landmarks_images.py{RESET}")
            return 0

        print(f"\n{RED}Not ready — the ASL Alphabet dataset is required for Model A.{RESET}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
