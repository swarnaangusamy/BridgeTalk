#!/usr/bin/env python3
"""Turn WLASL sign-language videos into fixed-length landmark sequences.

This is the Model B counterpart of `extract_landmarks_images.py`, and the
difference between them is the whole reason Model B exists.

A letter is a *shape*: one frame contains the entire answer, which is why
Model A is a single-frame MLP. A word sign is a *movement* — "again", "help"
and "want" all involve hands travelling through space, and a single frame of
any of them is close to meaningless. So each clip becomes a **sequence** of
landmark frames, and the model that consumes it has to be recurrent.

WHAT THIS PRODUCES
------------------
For every usable clip: one array of shape **(30, 126)** — thirty timesteps of
two-handed normalised landmarks (63 floats per hand, left slot then right).

Two-handed rather than the single hand Model A uses, because word-level signs
genuinely are two-handed. `normalize_hands` slots each hand by MediaPipe's
handedness label, so the left hand always lands in the same half of the vector.

THE THREE DECISIONS WORTH DEFENDING
-----------------------------------
1. **Uniform temporal resampling to exactly 30 frames.** Clips run from well
   under a second to several seconds. Padding everything to the longest clip
   would leave short signs as mostly padding; truncating to the shortest would
   cut the end off long ones. Resampling with `np.linspace` keeps the whole
   gesture and makes speed irrelevant — the same sign performed quickly or
   slowly produces the same 30 timesteps. Sign speed varies between people and
   is not what distinguishes one word from another.

2. **Frames with no detected hand are kept as zeros, not dropped.** A masked
   timestep is information: it says "the hands were not visible here", which
   is a real part of how a sign begins and ends. The LSTM's Masking layer skips
   them, so they cost nothing but stay in the timeline. Dropping them instead
   would silently compress the gesture's timing.

3. **The clip is trimmed to WLASL's `frame_start`/`frame_end` first.** Many
   source videos contain an introduction, a title card, or several signs in
   sequence. The metadata says which frames are the sign; ignoring it would
   train the model on whatever else is in the file.

USAGE
-----
    python ml/scripts/extract_landmarks_video.py                 # top 20 glosses
    python ml/scripts/extract_landmarks_video.py --num-glosses 10
    python ml/scripts/extract_landmarks_video.py --workers 4
    python ml/scripts/extract_landmarks_video.py --dry-run       # 3 clips/gloss

OUTPUT
------
    ml/data/processed/dynamic_sequences.npz    sequences + per-clip metadata
    ml/data/processed/video_extraction_report.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from tqdm import tqdm  # noqa: E402

# Imported, never reimplemented — the same rule as the image extractor. The
# browser sends landmarks through the JavaScript twin of this function at
# inference time, and the parity test guards the two against drifting apart.
from app.ml.normalization import (  # noqa: E402
    NORMALIZATION_VERSION,
    TWO_HAND_FEATURES,
    normalize_hands,
)

RAW_ROOT = REPO_ROOT / "ml" / "data" / "raw"

# --- Which word-sign dataset? -----------------------------------------------
# WLASL ships a metadata JSON describing every clip: which gloss, which signer,
# and which frames of the source video actually contain the sign. INCLUDE ships
# folders — one per word — holding clips that are already trimmed.
#
# Those are genuinely different discovery problems, so each gets its own
# function, but everything after discovery (landmark extraction, resampling,
# reporting, output format) is shared.
DATASETS = {
    "wlasl": {
        "dir": RAW_ROOT / "wlasl",
        "title": "WLASL processed (American Sign Language)",
        "language": "ASL",
        "layout": "metadata-json",
        "citation": (
            "Li, D., Rodriguez, C., Yu, X., Li, H. Word-level Deep Sign Language "
            "Recognition from Video. WACV 2020."
        ),
    },
    "include": {
        "dir": RAW_ROOT / "include",
        "title": "INCLUDE (Indian Sign Language, word level)",
        "language": "ISL",
        "layout": "folders",
        "citation": (
            "Sridhar, A., Ganesan, R.G., Kumar, P., Khapra, M. INCLUDE: A Large "
            "Scale Dataset for Indian Sign Language Recognition. ACM MM 2020."
        ),
    },
}

RAW_DIR = DATASETS["wlasl"]["dir"]  # rebound in main() once --dataset is known
PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
HAND_MODEL = REPO_ROOT / "frontend" / "public" / "models" / "hand_landmarker.task"

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# Thirty timesteps is about one second at typical signing speed, and comfortably
# spans a WLASL clip after trimming. It is also small enough that a two-layer
# LSTM trains on a CPU in minutes rather than hours.
SEQUENCE_LENGTH = 30

# A clip in which MediaPipe finds hands in fewer than this fraction of frames is
# discarded. Below roughly a third, what survives is too sparse to describe a
# trajectory — the model would be learning from a handful of scattered points.
MIN_DETECTION_RATE = 0.30

_LANDMARKER_PATH: str | None = None


# ---------------------------------------------------------------------------
# Dataset layout discovery
# ---------------------------------------------------------------------------


def find_videos_root(search_root: Path, max_depth: int = 4) -> Path | None:
    """Find the directory holding the .mp4 clips.

    Same tolerance as the image extractor, for the same reason: Kaggle archives
    unzip into varying amounts of nesting, and failing on a technicality after a
    multi-gigabyte download is a miserable experience.
    """
    if not search_root.is_dir():
        return None

    frontier = [(search_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        count = sum(
            1 for item in directory.iterdir() if item.suffix.lower() in VIDEO_SUFFIXES
        )
        if count >= 10:
            return directory
        if depth < max_depth:
            try:
                frontier.extend(
                    (child, depth + 1) for child in directory.iterdir() if child.is_dir()
                )
            except PermissionError:
                continue
    return None


def find_metadata_json(search_root: Path) -> Path | None:
    """Locate WLASL_v0.3.json, whatever it has been renamed to."""
    if not search_root.is_dir():
        return None

    for candidate in sorted(search_root.rglob("*.json")):
        if "wlasl" in candidate.name.lower():
            return candidate

    # Fall back to any JSON whose top level looks like the WLASL schema, so a
    # renamed file still works rather than sending someone hunting.
    for candidate in sorted(search_root.rglob("*.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if isinstance(data, list) and data and "gloss" in data[0]:
            return candidate

    return None


def build_video_index(videos_root: Path) -> dict[str, Path]:
    """Map WLASL video_id -> file on disk.

    The metadata lists far more instances than the Kaggle mirror actually
    ships, because many source URLs have rotted since WLASL was published.
    Indexing what exists and intersecting with the metadata is the only
    reliable way to know what we really have.
    """
    index: dict[str, Path] = {}
    for item in videos_root.iterdir():
        if item.suffix.lower() in VIDEO_SUFFIXES:
            index[item.stem.lstrip("0") or "0"] = item
            index[item.stem] = item
    return index


def clean_class_name(name: str) -> str:
    """Turn a folder name into a label.

    INCLUDE numbers its word folders ("1. loud", "23. quiet"), and those
    numbers are an artefact of the directory listing rather than part of the
    word. Stripping them means the same word discovered under two categories
    collapses to one class instead of two near-duplicates.
    """
    cleaned = name.strip()

    # Leading "12." or "12 -" or "12_" numbering.
    parts = re.split(r"^\s*\d+\s*[.\-_)]\s*", cleaned, maxsplit=1)
    if len(parts) == 2 and parts[1]:
        cleaned = parts[1]

    return cleaned.strip().lower().replace("_", " ")


def discover_folder_classes(
    root: Path, num_glosses: int, limit_per_gloss: int
) -> tuple[list[str], dict[str, list[dict]]]:
    """Find word classes from directory structure, for INCLUDE.

    Any directory holding video files is a class, and its (cleaned) name is the
    label. INCLUDE nests words under category folders — Adjectives/, Animals/,
    Greetings/ — and this walks through that without needing to know the
    categories exist.

    No signer metadata is available this way. That is recorded honestly as
    signer_id -1 rather than invented, and preprocess_dynamic.py refuses to
    claim a signer-disjoint split when it sees that.
    """
    by_class: dict[str, list[dict]] = defaultdict(list)

    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        videos = sorted(
            item for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() in VIDEO_SUFFIXES
        )
        if not videos:
            continue

        label = clean_class_name(directory.name)
        if not label:
            continue

        for video in videos:
            by_class[label].append(
                {
                    "video_id": video.stem,
                    "path": str(video),
                    # -1 means "not recorded by this dataset", NOT "signer 1".
                    "signer_id": -1,
                    # INCLUDE clips are already trimmed to a single sign, so
                    # there is no sub-range to select: take the whole file.
                    "frame_start": 1,
                    "frame_end": -1,
                    "official_split": "unknown",
                }
            )

    ranked = sorted(by_class.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    chosen = [label for label, _ in ranked[:num_glosses]]

    selected = {}
    for label in chosen:
        clips = by_class[label]
        selected[label] = clips[:limit_per_gloss] if limit_per_gloss else clips

    return chosen, selected


def select_glosses(
    metadata: list[dict],
    video_index: dict[str, Path],
    num_glosses: int,
) -> tuple[list[str], dict[str, list[dict]]]:
    """Pick the N glosses with the most clips that are actually present.

    Ranking by *available* clips rather than by the metadata's instance count
    matters: a gloss can list 30 instances and have 4 files on disk, and
    choosing it would give the model almost nothing to learn from.
    """
    available: dict[str, list[dict]] = defaultdict(list)

    for entry in metadata:
        gloss = entry.get("gloss")
        if not gloss:
            continue

        for instance in entry.get("instances", []):
            video_id = str(instance.get("video_id", "")).strip()
            path = video_index.get(video_id) or video_index.get(video_id.lstrip("0"))
            if path is None:
                continue

            available[gloss].append(
                {
                    "video_id": video_id,
                    "path": str(path),
                    "signer_id": int(instance.get("signer_id", -1)),
                    "frame_start": int(instance.get("frame_start", 1)),
                    "frame_end": int(instance.get("frame_end", -1)),
                    "official_split": str(instance.get("split", "unknown")),
                }
            )

    ranked = sorted(available.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    chosen = [gloss for gloss, _ in ranked[:num_glosses]]

    return chosen, {gloss: available[gloss] for gloss in chosen}


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _init_worker(model_path: str) -> None:
    global _LANDMARKER_PATH
    _LANDMARKER_PATH = model_path


def _build_landmarker():
    """One HandLandmarker, in VIDEO mode.

    A fresh landmarker is built per clip rather than reused across clips. VIDEO
    mode carries tracking state between calls, which is exactly what we want
    *within* a clip and exactly what we do not want between two unrelated ones —
    a reused tracker can carry a hand's position from the end of one video into
    the start of the next and invent motion that never happened.
    """
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    return vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=_LANDMARKER_PATH),
            running_mode=vision.RunningMode.VIDEO,
            # Two hands: word-level signs frequently use both, unlike
            # fingerspelling. This is why Model B's features are 126 wide.
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    )


def resample_sequence(frames: list[np.ndarray], length: int = SEQUENCE_LENGTH) -> np.ndarray:
    """Resample a variable-length frame list to exactly `length` timesteps.

    Nearest-neighbour selection along a linear index, not interpolation.
    Interpolating between two landmark frames would invent hand positions that
    were never observed, and in the middle of a fast movement those invented
    poses can be anatomically impossible. Picking real frames keeps every
    timestep something the camera actually saw.
    """
    if not frames:
        return np.zeros((length, TWO_HAND_FEATURES), dtype=np.float32)

    if len(frames) == 1:
        return np.repeat(frames[0][None, :], length, axis=0).astype(np.float32)

    indices = np.linspace(0, len(frames) - 1, num=length)
    return np.stack([frames[int(round(i))] for i in indices]).astype(np.float32)


def extract_one(job: dict) -> dict:
    """Decode one clip and return its (30, 126) sequence plus diagnostics."""
    import mediapipe as mp_lib

    path = Path(job["path"])
    result: dict = {
        "gloss": job["gloss"],
        "video_id": job["video_id"],
        "signer_id": job["signer_id"],
        "official_split": job["official_split"],
        "sequence": None,
        "status": "ok",
        "frames_read": 0,
        "frames_with_hands": 0,
    }

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        result["status"] = "unreadable"
        return result

    try:
        landmarker = _build_landmarker()

        # WLASL frame numbers are 1-based; frame_end of -1 means "to the end".
        start = max(0, job["frame_start"] - 1)
        end = job["frame_end"] - 1 if job["frame_end"] > 0 else None

        if start > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start)

        frames: list[np.ndarray] = []
        frames_with_hands = 0
        index = start
        timestamp_ms = 0

        while True:
            if end is not None and index > end:
                break

            ok, frame = capture.read()
            if not ok:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)

            # MediaPipe requires strictly increasing timestamps in VIDEO mode.
            # The real frame interval does not matter here — we resample by
            # index afterwards — so a fixed 33 ms step is both valid and stable
            # across clips with different frame rates.
            timestamp_ms += 33
            detection = landmarker.detect_for_video(mp_image, timestamp_ms)

            if detection.hand_landmarks:
                hands = [
                    {
                        "handedness": detection.handedness[hand_index][0].category_name,
                        "landmarks": [
                            [point.x, point.y, point.z]
                            for point in detection.hand_landmarks[hand_index]
                        ],
                    }
                    for hand_index in range(len(detection.hand_landmarks))
                ]
                frames.append(normalize_hands(hands))
                frames_with_hands += 1
            else:
                # Kept, not dropped: an all-zero frame is a masked timestep and
                # preserves the gesture's real timing.
                frames.append(np.zeros(TWO_HAND_FEATURES, dtype=np.float32))

            index += 1

        result["frames_read"] = len(frames)
        result["frames_with_hands"] = frames_with_hands

        if not frames:
            result["status"] = "empty"
            return result

        detection_rate = frames_with_hands / len(frames)
        if detection_rate < MIN_DETECTION_RATE:
            result["status"] = "too_few_hands"
            return result

        result["sequence"] = resample_sequence(frames).tolist()
        return result

    except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the run
        result["status"] = f"error: {type(exc).__name__}"
        return result
    finally:
        capture.release()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--num-glosses", type=int, default=20,
                        help="How many glosses to keep, ranked by available clips")
    parser.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 2))
    parser.add_argument("--limit-per-gloss", type=int, default=0,
                        help="Cap clips per gloss (0 = no cap)")
    parser.add_argument("--dry-run", action="store_true",
                        help="3 clips per gloss, nothing written")
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        default="include",
        help="include = Indian Sign Language words (default) · wlasl = ASL words",
    )
    args = parser.parse_args()

    if not HAND_MODEL.is_file():
        print(f"ERROR: {HAND_MODEL} missing. Run ./scripts/setup.sh", file=sys.stderr)
        return 1

    config = DATASETS[args.dataset]
    raw_dir = config["dir"]
    cap = 3 if args.dry_run else args.limit_per_gloss

    print(f"Dataset:  {config['title']}")
    print(f"Language: {config['language']}")

    # --- locate the dataset -------------------------------------------------
    if config["layout"] == "folders":
        # INCLUDE: one folder per word, clips already trimmed to a single sign.
        if not raw_dir.is_dir():
            print(f"\nERROR: {config['title']} not found under {raw_dir}",
                  file=sys.stderr)
            print("\nExpected one folder per word, at any nesting depth:",
                  file=sys.stderr)
            print(f"  {raw_dir.relative_to(REPO_ROOT)}/Adjectives/1. loud/*.mp4",
                  file=sys.stderr)
            print(f"  {raw_dir.relative_to(REPO_ROOT)}/Greetings/2. hello/*.mp4",
                  file=sys.stderr)
            print("\nDownload INCLUDE from:", file=sys.stderr)
            print("  https://zenodo.org/record/4010759", file=sys.stderr)
            return 1

        glosses, instances_by_gloss = discover_folder_classes(
            raw_dir, args.num_glosses, cap
        )

        if not glosses:
            print(f"\nERROR: no folder under {raw_dir} contains video files.",
                  file=sys.stderr)
            print("Check the archive extracted fully.", file=sys.stderr)
            return 1

        print(f"Layout:   folders ({len(glosses)} word classes discovered)")

    else:
        # WLASL: a metadata JSON drives everything.
        videos_root = find_videos_root(raw_dir)
        metadata_path = find_metadata_json(raw_dir)

        if videos_root is None or metadata_path is None:
            print(f"ERROR: WLASL not found under {raw_dir}", file=sys.stderr)
            print("\nExpected:", file=sys.stderr)
            print(f"  {raw_dir.relative_to(REPO_ROOT)}/videos/*.mp4", file=sys.stderr)
            print(f"  {raw_dir.relative_to(REPO_ROOT)}/WLASL_v0.3.json", file=sys.stderr)
            print("\nDownload it from:", file=sys.stderr)
            print("  https://www.kaggle.com/datasets/risangbaskoro/wlasl-processed",
                  file=sys.stderr)
            return 1

        print(f"Videos:   {videos_root}")
        print(f"Metadata: {metadata_path.name}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        video_index = build_video_index(videos_root)
        print(f"Files on disk: {len(set(video_index.values())):,}")

        glosses, instances_by_gloss = select_glosses(
            metadata, video_index, args.num_glosses
        )

        if not glosses:
            print("\nERROR: no gloss has any clip present on disk.", file=sys.stderr)
            print("The metadata and the video folder do not appear to match.",
                  file=sys.stderr)
            return 1

        if cap:
            instances_by_gloss = {
                gloss: items[:cap] for gloss, items in instances_by_gloss.items()
            }

    print(f"\nSelected {len(glosses)} glosses (ranked by clips actually present):")
    for gloss in glosses:
        count = len(instances_by_gloss[gloss])
        signers = len({item["signer_id"] for item in instances_by_gloss[gloss]})
        print(f"  {gloss:<16} {count:>3} clips   {signers:>2} signers")

    smallest = min(len(instances_by_gloss[g]) for g in glosses)
    if smallest < 7:
        print(f"\n  NOTE: the smallest gloss has only {smallest} clips. With a")
        print("  signer-disjoint split that may leave it absent from a split;")
        print("  preprocess_dynamic.py reports coverage per split and will say so.")

    # --- build the job list -------------------------------------------------
    jobs: list[dict] = []
    for gloss in glosses:
        for item in instances_by_gloss[gloss]:
            jobs.append({**item, "gloss": gloss})

    print(f"\nExtracting {len(jobs):,} clips with {args.workers} workers")
    print("Video decoding is the slow part — expect a few minutes.\n")

    started = time.time()
    results: list[dict] = []

    if args.workers > 1:
        context = mp.get_context("spawn")
        with context.Pool(
            processes=args.workers, initializer=_init_worker, initargs=(str(HAND_MODEL),)
        ) as pool:
            for outcome in tqdm(
                pool.imap_unordered(extract_one, jobs), total=len(jobs), unit="clip"
            ):
                results.append(outcome)
    else:
        _init_worker(str(HAND_MODEL))
        for job in tqdm(jobs, unit="clip"):
            results.append(extract_one(job))

    elapsed = time.time() - started

    # --- report -------------------------------------------------------------
    kept = [item for item in results if item["sequence"] is not None]
    statuses = Counter(item["status"] for item in results)

    print(f"\n{'=' * 62}")
    print(f"  clips processed   {len(results):,}")
    print(f"  sequences kept    {len(kept):,}")
    print(f"  discarded         {len(results) - len(kept):,} "
          f"({(len(results) - len(kept)) / max(1, len(results)):.1%})")
    print(f"  time              {elapsed / 60:.1f} min")
    print(f"{'=' * 62}")

    print("\nWhy clips were discarded:")
    for status, count in statuses.most_common():
        if status != "ok":
            print(f"  {status:<20} {count:>4}")

    per_gloss = Counter(item["gloss"] for item in kept)
    print("\nSequences per gloss:")
    for gloss in glosses:
        total = sum(1 for item in results if item["gloss"] == gloss)
        print(f"  {gloss:<16} {per_gloss.get(gloss, 0):>3} / {total:<3} kept")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    if not kept:
        print("\nERROR: no usable sequences. Nothing written.", file=sys.stderr)
        return 1

    # --- save ---------------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    sequences = np.stack([np.asarray(item["sequence"], dtype=np.float32) for item in kept])

    output = PROCESSED_DIR / "dynamic_sequences.npz"
    np.savez_compressed(
        output,
        sequences=sequences,
        glosses=np.array([item["gloss"] for item in kept]),
        signer_ids=np.array([item["signer_id"] for item in kept]),
        video_ids=np.array([item["video_id"] for item in kept]),
        official_splits=np.array([item["official_split"] for item in kept]),
    )
    print(f"\nWrote {output.relative_to(REPO_ROOT)}  {sequences.shape}")

    report = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source_dataset": config["title"],
        "language": config["language"],
        "citation": config["citation"],
        "self_recorded_data": False,
        "normalization_version": NORMALIZATION_VERSION,
        "sequence_length": SEQUENCE_LENGTH,
        "features_per_frame": TWO_HAND_FEATURES,
        "min_detection_rate": MIN_DETECTION_RATE,
        "glosses": glosses,
        "clips_processed": len(results),
        "sequences_kept": len(kept),
        "discard_reasons": dict(statuses),
        "per_gloss": {gloss: per_gloss.get(gloss, 0) for gloss in glosses},
        "signers": sorted({int(item["signer_id"]) for item in kept}),
        "extraction_time_seconds": round(elapsed, 1),
    }

    report_path = PROCESSED_DIR / "video_extraction_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path.relative_to(REPO_ROOT)}")

    print("\nNext: python ml/scripts/preprocess_dynamic.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
