#!/usr/bin/env python3
"""Turn the ASL Alphabet image dataset into normalised hand-landmark vectors.

WHAT THIS DOES, AND WHY IT IS THE INTERESTING STEP
--------------------------------------------------
Most sign-recognition tutorials feed raw images to a CNN. BridgeTalk does not.
Instead, every image goes through MediaPipe once, offline, and we keep only the
21 hand landmarks it finds. The model then learns from 63 numbers instead of
120,000 pixels.

That choice pays off three times:

  * **Training is fast.** A 63-input MLP trains on a CPU in minutes. A CNN over
    87,000 images does not.
  * **Lighting and skin tone stop mattering.** MediaPipe has already solved
    "where is the hand"; our model only has to solve "what shape is it in".
    A CNN trained on this dataset would also learn its backgrounds and its
    lighting, and fall apart in a different room.
  * **The same features exist in the browser.** MediaPipe runs client-side at
    inference time and produces exactly these landmarks, so training inputs and
    live inputs are the same kind of thing. That is what makes the whole
    architecture hang together.

The cost is real and worth stating: if MediaPipe cannot find a hand in an
image, that image is lost to us entirely. This script reports that discard rate
per class, because it is a genuine finding rather than an inconvenience.

USAGE
-----
    python ml/scripts/extract_landmarks_images.py                  # 1500/class
    python ml/scripts/extract_landmarks_images.py --limit-per-class 300
    python ml/scripts/extract_landmarks_images.py --workers 1      # single process
    python ml/scripts/extract_landmarks_images.py --dry-run        # 20/class, no output

OUTPUT
------
    ml/data/processed/static_landmarks.csv   label, source, handedness, f0..f62
    ml/data/processed/extraction_report.json per-class counts and discard rates
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --- make backend/ importable ----------------------------------------------
# Normalisation lives in backend/app/ml/normalization.py and is imported here
# rather than reimplemented. That is deliberate: training and inference must
# produce identical numbers, and the only way to guarantee that in Python is to
# run the same code. See the module docstring there.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from tqdm import tqdm  # noqa: E402

from app.ml.normalization import (  # noqa: E402
    NORMALIZATION_VERSION,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
    normalize_hand,
    normalize_hands,
)

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
RAW_ROOT = REPO_ROOT / "ml" / "data" / "raw"
# Downloaded by scripts/setup.sh. The Python and JavaScript sides deliberately
# use the same .task file, so the landmarks seen during training are produced
# by exactly the same detector that runs in the browser.
HAND_MODEL = REPO_ROOT / "frontend" / "public" / "models" / "hand_landmarker.task"

ASL_CLASSES = tuple(chr(c) for c in range(ord("A"), ord("Z") + 1)) + ("del", "nothing", "space")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}

# --- Which alphabet are we extracting? --------------------------------------
# ASL fingerspelling is ONE-handed; ISL fingerspelling is TWO-handed. That
# single difference propagates through the whole pipeline: 63 features versus
# 126, a different MediaPipe hand limit, and a mirroring augmentation that has
# to swap hand slots rather than just negating x.
#
# It is a flag rather than a second script because everything else here — the
# discard accounting, the multiprocessing, the per-class reporting — is
# identical, and a forked copy would drift.
DATASETS = {
    "asl": {
        "dir": RAW_ROOT / "asl_alphabet",
        "classes": ASL_CLASSES,      # fixed and known
        "hands": 1,
        "features": SINGLE_HAND_FEATURES,
        "output": "static_landmarks.csv",
        "report": "extraction_report.json",
        "title": "ASL Alphabet (grassknoted/asl-alphabet)",
    },
    "isl": {
        "dir": RAW_ROOT / "isl_alphabet",
        "classes": None,             # discovered from disk — sets vary
        "hands": 2,
        "features": TWO_HAND_FEATURES,
        "output": "isl_landmarks.csv",
        "report": "isl_extraction_report.json",
        "title": "Indian Sign Language alphabet",
    },
}

# Populated by main() before any worker starts, and re-sent to each worker.
CLASSES: tuple[str, ...] = ASL_CLASSES
NUM_HANDS = 1
FEATURE_COUNT = SINGLE_HAND_FEATURES

# Each worker process builds its own HandLandmarker and keeps it in this global.
# MediaPipe task objects hold native handles and cannot be pickled, so they
# cannot be passed to workers — each process must construct its own.
_LANDMARKER = None


def count_images(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for item in directory.iterdir() if item.suffix.lower() in IMAGE_SUFFIXES)


def discover_class_root(search_root: Path, max_depth: int = 5) -> Path | None:
    """Find class folders without knowing their names, for ISL.

    ISL alphabet datasets disagree about whether digits are included, so the
    class list is read from disk rather than asserted. The best candidate is
    the directory with the most immediate subfolders that actually hold images.
    """
    if not search_root.is_dir():
        return None

    best: Path | None = None
    best_count = 0

    frontier = [(search_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        try:
            children = [child for child in directory.iterdir() if child.is_dir()]
        except (PermissionError, OSError):
            continue

        populated = sum(1 for child in children if count_images(child) > 0)
        if populated > best_count:
            best, best_count = directory, populated

        if depth < max_depth:
            frontier.extend((child, depth + 1) for child in children)

    return best if best_count >= 10 else None


def find_class_root(search_root: Path, max_depth: int = 4) -> Path | None:
    """Locate the directory holding the known class folders.

    The Kaggle archive nests the same folder name twice
    (asl_alphabet_train/asl_alphabet_train/A/), so hard-coding a path breaks
    for anyone who unzipped it even slightly differently.
    """
    if not search_root.is_dir():
        return None

    required = {name.lower() for name in CLASSES}
    threshold = max(1, int(len(required) * 0.8))

    frontier = [(search_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        try:
            children = [child for child in directory.iterdir() if child.is_dir()]
        except PermissionError:
            continue

        if len({child.name.lower() for child in children} & required) >= threshold:
            return directory

        if depth < max_depth:
            frontier.extend((child, depth + 1) for child in children)

    return None


def _init_worker(model_path: str, num_hands: int = 1) -> None:
    """Build one HandLandmarker per worker process.

    Called once by each process in the pool. Importing MediaPipe here rather
    than at module scope keeps the parent process light and avoids loading the
    native library twice in the parent.

    `num_hands` is passed explicitly rather than read from a module global,
    because the "spawn" start method gives each worker a fresh interpreter in
    which module-level mutations made by main() never happened. Relying on the
    global here would silently extract one hand from a two-handed alphabet.
    """
    global _LANDMARKER, NUM_HANDS, FEATURE_COUNT

    NUM_HANDS = num_hands
    FEATURE_COUNT = SINGLE_HAND_FEATURES if num_hands == 1 else TWO_HAND_FEATURES

    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    options = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        # IMAGE mode treats every call as an unrelated still. VIDEO mode would
        # track across calls, which is wrong here — consecutive dataset images
        # are not consecutive frames of one motion.
        running_mode=vision.RunningMode.IMAGE,
        # 1 for ASL (one-handed alphabet), 2 for ISL (two-handed).
        num_hands=num_hands,
        # Deliberately permissive. The dataset contains awkward crops and
        # motion blur; a strict threshold discards salvageable images, and we
        # would rather keep a slightly noisy landmark than lose the sample.
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
    )
    _LANDMARKER = vision.HandLandmarker.create_from_options(options)


def _process_image(task: tuple[str, str]) -> tuple[str, str, str, list[float]] | None:
    """Extract one image's normalised landmarks.

    Returns (label, filename, handedness, 63 floats), or None if MediaPipe
    found no hand — which is the outcome this script exists to measure.
    """
    path_str, label = task
    path = Path(path_str)

    import mediapipe as mp_lib

    # cv2.imread returns None for unreadable or corrupt files rather than
    # raising, so the check is not optional.
    bgr = cv2.imread(path_str)
    if bgr is None:
        return None

    # OpenCV loads BGR; MediaPipe expects RGB. Getting this backwards does not
    # error — it silently degrades detection, because skin tones come out blue.
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)

    result = _LANDMARKER.detect(mp_image)
    if not result.hand_landmarks:
        return None

    def hand_label(index: int) -> str:
        if result.handedness and len(result.handedness) > index and result.handedness[index]:
            return result.handedness[index][0].category_name
        return "Right"

    if NUM_HANDS == 1:
        landmarks = np.array(
            [[point.x, point.y, point.z] for point in result.hand_landmarks[0]],
            dtype=np.float32,
        )
        try:
            features = normalize_hand(landmarks)
        except ValueError:
            return None

        return label, path.name, hand_label(0), features.tolist()

    # --- two-handed (ISL) ---------------------------------------------------
    # normalize_hands slots each hand by handedness, so the left hand always
    # lands in the same half of the vector regardless of the order MediaPipe
    # happened to report them in. Without that, the same sign would appear in
    # two different arrangements and the model would have to learn both.
    hands = [
        {
            "handedness": hand_label(index),
            "landmarks": [[p.x, p.y, p.z] for p in result.hand_landmarks[index]],
        }
        for index in range(len(result.hand_landmarks))
    ]

    try:
        features = normalize_hands(hands)
    except ValueError:
        return None

    # A two-handed alphabet with only one hand found is kept, not discarded:
    # several ISL letters genuinely use one hand, and the missing slot is
    # zero-filled. Which hands were seen is recorded so the discard analysis
    # can separate "one hand because the letter has one" from "one hand because
    # the other was occluded".
    seen = "+".join(sorted(hand["handedness"] for hand in hands)) or "none"

    return label, path.name, seen, features.tolist()


def gather_tasks(class_root: Path, limit_per_class: int) -> tuple[list, dict[str, int]]:
    """Collect up to `limit_per_class` image paths for every class.

    Files are taken in sorted order rather than at random so that re-running
    the script produces the same dataset. Reproducibility matters more here
    than sampling diversity, since the images within a class are already very
    similar to each other.
    """
    tasks: list[tuple[str, str]] = []
    available: dict[str, int] = {}

    for label in CLASSES:
        directory = class_root / label
        if not directory.is_dir():
            matches = [
                child
                for child in class_root.iterdir()
                if child.is_dir() and child.name.lower() == label.lower()
            ]
            if not matches:
                available[label] = 0
                continue
            directory = matches[0]

        images = sorted(
            item for item in directory.iterdir() if item.suffix.lower() in IMAGE_SUFFIXES
        )
        available[label] = len(images)
        tasks.extend((str(path), label) for path in images[:limit_per_class])

    return tasks, available


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit-per-class",
        type=int,
        default=1500,
        help="Images per class (default 1500). Keeps classes balanced and "
        "extraction to minutes rather than hours.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (mp.cpu_count() or 2) - 1),
        help="Parallel processes. Use 1 if MediaPipe misbehaves.",
    )
    parser.add_argument("--dry-run", action="store_true", help="20 images/class, writes nothing")
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        default="asl",
        help="asl = one-handed ASL alphabet (Model A) · "
        "isl = two-handed Indian Sign Language alphabet",
    )
    parser.add_argument("--output", type=Path, default=None,
                        help="Override the output CSV path")
    args = parser.parse_args()

    limit = 20 if args.dry_run else args.limit_per_class

    # --- select the alphabet ------------------------------------------------
    global CLASSES, NUM_HANDS, FEATURE_COUNT

    config = DATASETS[args.dataset]
    NUM_HANDS = config["hands"]
    FEATURE_COUNT = config["features"]
    raw_dir = config["dir"]
    output_path = args.output or (PROCESSED_DIR / config["output"])

    # --- preflight ----------------------------------------------------------
    if not HAND_MODEL.is_file():
        print(f"ERROR: MediaPipe model not found at {HAND_MODEL}", file=sys.stderr)
        print("Run ./scripts/setup.sh to download it.", file=sys.stderr)
        return 1

    if config["classes"] is None:
        class_root = discover_class_root(raw_dir)
        if class_root is not None:
            # The class list IS whatever is on disk. Sorted so that the label
            # -to-index mapping is stable across runs and machines.
            CLASSES = tuple(
                sorted(
                    child.name
                    for child in class_root.iterdir()
                    if child.is_dir() and count_images(child) > 0
                )
            )
    else:
        CLASSES = tuple(config["classes"])
        class_root = find_class_root(raw_dir)

    if class_root is None or not CLASSES:
        print(f"ERROR: no class folders found under {raw_dir}", file=sys.stderr)
        print(
            f"Run: python ml/scripts/download_datasets.py "
            f"--dataset {'static' if args.dataset == 'asl' else args.dataset} --verify",
            file=sys.stderr,
        )
        return 1

    print(f"Alphabet:   {config['title']}")
    print(f"Hands:      {NUM_HANDS}  ({FEATURE_COUNT} features per sample)")
    print(f"Classes:    {len(CLASSES)}  {', '.join(CLASSES[:8])}"
          f"{', ...' if len(CLASSES) > 8 else ''}")
    print(f"Dataset:    {class_root}")
    print(f"Model:      {HAND_MODEL.name}")
    print(f"Limit:      {limit} images/class")
    print(f"Workers:    {args.workers}")
    print(f"Normalisation version: {NORMALIZATION_VERSION}")

    tasks, available = gather_tasks(class_root, limit)
    if not tasks:
        print("ERROR: no images found.", file=sys.stderr)
        return 1

    print(f"Queued:     {len(tasks):,} images across {len(CLASSES)} classes\n")

    # --- extract ------------------------------------------------------------
    started = time.time()
    rows: list[tuple[str, str, str, list[float]]] = []
    attempted: dict[str, int] = {label: 0 for label in CLASSES}
    detected: dict[str, int] = {label: 0 for label in CLASSES}

    for _, label in tasks:
        attempted[label] += 1

    if args.workers > 1:
        # "spawn" rather than the macOS default: MediaPipe holds native
        # resources that do not survive a fork, and forking it produces
        # deadlocks that look like the script simply hanging.
        context = mp.get_context("spawn")
        with context.Pool(
            processes=args.workers,
            initializer=_init_worker,
            initargs=(str(HAND_MODEL), NUM_HANDS),
        ) as pool:
            for result in tqdm(
                pool.imap_unordered(_process_image, tasks, chunksize=32),
                total=len(tasks),
                desc="Extracting",
                unit="img",
            ):
                if result is not None:
                    rows.append(result)
                    detected[result[0]] += 1
    else:
        _init_worker(str(HAND_MODEL), NUM_HANDS)
        for task in tqdm(tasks, desc="Extracting", unit="img"):
            result = _process_image(task)
            if result is not None:
                rows.append(result)
                detected[result[0]] += 1

    elapsed = time.time() - started

    # --- report -------------------------------------------------------------
    print(f"\n{'class':>8} {'attempted':>10} {'detected':>9} {'discarded':>10} {'discard %':>10}")
    print("-" * 52)

    report_classes = {}
    for label in CLASSES:
        tried = attempted[label]
        found = detected[label]
        lost = tried - found
        rate = (lost / tried * 100) if tried else 0.0
        print(f"{label:>8} {tried:>10,} {found:>9,} {lost:>10,} {rate:>9.1f}%")
        report_classes[label] = {
            "available_in_dataset": available.get(label, 0),
            "attempted": tried,
            "detected": found,
            "discarded": lost,
            "discard_rate_pct": round(rate, 2),
        }

    total_attempted = sum(attempted.values())
    total_detected = len(rows)
    overall_rate = (
        (total_attempted - total_detected) / total_attempted * 100 if total_attempted else 0.0
    )

    print("-" * 52)
    print(f"{'TOTAL':>8} {total_attempted:>10,} {total_detected:>9,} "
          f"{total_attempted - total_detected:>10,} {overall_rate:>9.1f}%")
    print(f"\nElapsed: {elapsed / 60:.1f} min "
          f"({total_attempted / elapsed:.0f} images/sec)")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    # --- write --------------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        # `source` is the original filename. preprocess.py uses it to split
        # train/val/test by source file rather than at random, so near-identical
        # frames cannot land on both sides of the split and inflate accuracy.
        writer.writerow(
            ["label", "source", "handedness"] + [f"f{i}" for i in range(FEATURE_COUNT)]
        )
        for label, source, handedness, features in rows:
            writer.writerow([label, source, handedness] + [f"{value:.6f}" for value in features])

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nWrote {total_detected:,} rows to {output_path.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")

    report = {
        "dataset": "ASL Alphabet (grassknoted/asl-alphabet)",
        "source_url": "https://www.kaggle.com/datasets/grassknoted/asl-alphabet",
        "self_recorded_data": False,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "normalization_version": NORMALIZATION_VERSION,
        "hand_landmarker_model": HAND_MODEL.name,
        "detector_settings": {
            "running_mode": "IMAGE",
            "num_hands": NUM_HANDS,
            "min_hand_detection_confidence": 0.3,
            "min_hand_presence_confidence": 0.3,
        },
        "limit_per_class": limit,
        "feature_count": FEATURE_COUNT,
        "num_hands": NUM_HANDS,
        "alphabet": config["title"],
        "totals": {
            "attempted": total_attempted,
            "detected": total_detected,
            "discarded": total_attempted - total_detected,
            "discard_rate_pct": round(overall_rate, 2),
        },
        "elapsed_seconds": round(elapsed, 1),
        "classes": report_classes,
    }

    report_path = PROCESSED_DIR / config["report"]
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
