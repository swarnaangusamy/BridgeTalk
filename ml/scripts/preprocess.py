#!/usr/bin/env python3
"""Split and augment extracted landmarks into train/val/test arrays.

Reads  ml/data/processed/static_landmarks.csv   (from extract_landmarks_images.py)
Writes ml/data/processed/X_train.npy, y_train.npy, X_val.npy, … plus
       labels.json and dataset_manifest.json

THE TWO DECISIONS THAT MATTER HERE
----------------------------------

**1. The split is contiguous, not random.**

The obvious thing is `train_test_split(shuffle=True)`. It is also wrong for
this dataset, and it would quietly inflate our reported accuracy by a lot.

ASL Alphabet's images were captured as continuous video: A1.jpg, A2.jpg and
A3.jpg are consecutive frames of one person holding one pose. They are
near-identical. Split them randomly and A2 lands in training while A3 lands in
test — so the model is graded on a frame it has effectively already memorised.
Reported accuracy goes up; real accuracy does not.

So we sort by the numeric index in each filename and cut contiguous blocks:
the first 70% of each class to train, the next 15% to validation, the last 15%
to test. Adjacent near-duplicate frames stay on the same side of the line.

Be honest about the limit of this: the dataset has no signer metadata, and
appears to be a small number of people (possibly one) per class. So even a
contiguous split cannot give us a *different signer* in the test set. Our test
accuracy therefore measures "same hands, later frames", not "a stranger's
hands". The real check on that is test_realtime.py, run against a webcam the
model has never seen. Expect that number to be lower, and say so.

**2. Augmentation happens in normalised space, then re-normalises.**

Rotation and coordinate noise are applied to the 63-float vector, and the
result is re-normalised so it satisfies the same invariants as live input.

Scale jitter is deliberately NOT applied. It would be a no-op: normalisation
already divides by the largest distance from the wrist, so scaling a hand up
and re-normalising gives back exactly what you started with. Scale invariance
is already guaranteed by the representation, so jittering it teaches nothing.
That is a property of choosing landmarks over pixels, and it is worth saying
out loud rather than adding an augmentation that does nothing.

Augmentation is applied to the TRAINING SPLIT ONLY. Augmenting validation or
test data would mean grading the model on data we invented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.normalization import NORMALIZATION_VERSION, SINGLE_HAND_FEATURES  # noqa: E402

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
INPUT_CSV = PROCESSED_DIR / "static_landmarks.csv"
MODELS_DIR = REPO_ROOT / "ml" / "models"

# Split proportions, per the data hygiene rules.
TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15
# test gets the remainder

# Classes that cannot be learned from landmarks and are excluded, with reasons
# recorded in the manifest rather than silently dropped.
UNLEARNABLE_CLASSES = {
    "nothing": (
        "Images contain no hand, so MediaPipe finds no landmarks and there is "
        "nothing to classify. 99.9% of this class was discarded during "
        "extraction; the few rows that survived are false detections. The "
        "neutral state is handled in the pipeline instead: when no hand is "
        "detected the backend emits 'nothing' without calling the model."
    )
}


def numeric_suffix(filename: str) -> int:
    """Extract the trailing number from a filename like 'A1234.jpg' -> 1234.

    Used to restore capture order, which is what makes a contiguous split
    meaningful. Files without a number sort last but keep a stable order.
    """
    match = re.search(r"(\d+)(?=\.[A-Za-z]+$)", filename)
    return int(match.group(1)) if match else 10**9


def rotate_2d(features: np.ndarray, angle_radians: float) -> np.ndarray:
    """Rotate landmarks in the image plane around the wrist.

    Simulates the hand being tilted. Only x and y are rotated: z is MediaPipe's
    depth estimate, which an in-plane tilt does not change.

    Args:
        features: (n, 63) normalised vectors.
        angle_radians: rotation angle.
    """
    points = features.reshape(-1, 21, 3).copy()
    cos_a, sin_a = np.cos(angle_radians), np.sin(angle_radians)

    x = points[:, :, 0].copy()
    y = points[:, :, 1].copy()
    points[:, :, 0] = x * cos_a - y * sin_a
    points[:, :, 1] = x * sin_a + y * cos_a

    return points.reshape(-1, SINGLE_HAND_FEATURES)


def renormalize(features: np.ndarray) -> np.ndarray:
    """Re-apply the wrist-centre / unit-scale invariants after augmentation.

    Mirrors backend/app/ml/normalization.py exactly, but vectorised across a
    whole batch. Augmented samples must satisfy the same invariants as live
    input, or we would be training on data the model can never encounter.
    """
    points = features.reshape(-1, 21, 3).copy()

    # Translate: wrist back to the origin.
    points -= points[:, 0:1, :]

    # Scale: furthest landmark back to distance 1.
    distances = np.linalg.norm(points, axis=2)
    scales = distances.max(axis=1, keepdims=True)[:, :, None]
    scales = np.where(scales < 1e-8, 1.0, scales)  # avoid dividing by zero

    return (points / scales).reshape(-1, SINGLE_HAND_FEATURES).astype(np.float32)


def augment(
    features: np.ndarray,
    labels: np.ndarray,
    rounds: int,
    max_rotation_degrees: float,
    noise_std: float,
    mirror: bool,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate augmented copies of the training set.

    Args:
        rounds: how many augmented copies to produce per original sample.
        max_rotation_degrees: in-plane rotation range, +/- this value.
        noise_std: standard deviation of Gaussian noise added per coordinate,
            in normalised units (where the hand spans 1.0).
        mirror: also produce a horizontally mirrored copy. This matters for
            accessibility rather than for accuracy: it teaches the model
            left-handed signing, which the dataset contains almost none of.
    """
    augmented_features = [features]
    augmented_labels = [labels]

    for _ in range(rounds):
        angles = rng.uniform(
            -np.radians(max_rotation_degrees), np.radians(max_rotation_degrees), size=len(features)
        )

        # Rotating each sample by its own angle, in one pass per unique angle,
        # would be slow. Rotating the batch by a single sampled angle per round
        # and adding per-sample noise gives comparable diversity far faster.
        rotated = rotate_2d(features, float(rng.uniform(
            -np.radians(max_rotation_degrees), np.radians(max_rotation_degrees)
        )))
        del angles

        noisy = rotated + rng.normal(0.0, noise_std, size=rotated.shape).astype(np.float32)
        augmented_features.append(renormalize(noisy))
        augmented_labels.append(labels)

    if mirror:
        # Mirroring in x turns a right hand into a left hand. The landmark
        # indices stay the same — index 4 is still the thumb tip — so no
        # re-ordering is needed, unlike mirroring an image.
        mirrored = features.reshape(-1, 21, 3).copy()
        mirrored[:, :, 0] *= -1.0
        mirrored = mirrored.reshape(-1, SINGLE_HAND_FEATURES)

        augmented_features.append(renormalize(mirrored))
        augmented_labels.append(labels)

    return (
        np.concatenate(augmented_features).astype(np.float32),
        np.concatenate(augmented_labels),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=INPUT_CSV)
    parser.add_argument(
        "--augment-rounds",
        type=int,
        default=2,
        help="Augmented copies per training sample (default 2).",
    )
    parser.add_argument("--max-rotation", type=float, default=12.0, help="degrees, default 12")
    parser.add_argument("--noise-std", type=float, default=0.015, help="default 0.015")
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Skip left-handed mirroring (mirroring is on by default).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--random-split",
        action="store_true",
        help="Shuffle before splitting. Produces a HIGHER but DISHONEST accuracy — "
        "see the module docstring. Provided so the difference can be measured.",
    )
    parser.add_argument(
        "--balance",
        choices=["min", "none"],
        default="min",
        help="'min' (default) subsamples every class down to the size of the "
        "smallest, so no class dominates. 'none' keeps everything.",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"ERROR: {args.input} not found.", file=sys.stderr)
        print("Run: python ml/scripts/extract_landmarks_images.py", file=sys.stderr)
        return 1

    rng = np.random.default_rng(args.seed)

    print(f"Reading {args.input.relative_to(REPO_ROOT)}")
    frame = pd.read_csv(args.input)
    print(f"  {len(frame):,} rows, {len(frame.columns)} columns")

    feature_columns = [f"f{i}" for i in range(SINGLE_HAND_FEATURES)]
    missing = set(feature_columns) - set(frame.columns)
    if missing:
        print(f"ERROR: CSV is missing feature columns: {sorted(missing)[:5]}…", file=sys.stderr)
        return 1

    # --- drop classes that cannot be learned from landmarks -----------------
    dropped_report = {}
    for class_name, reason in UNLEARNABLE_CLASSES.items():
        count = int((frame["label"] == class_name).sum())
        if count:
            frame = frame[frame["label"] != class_name]
            dropped_report[class_name] = {"rows_dropped": count, "reason": reason}
            print(f"\n  Dropping class '{class_name}' ({count} rows)")
            print(f"    {reason.splitlines()[0]}")

    labels_sorted = sorted(frame["label"].unique())
    label_to_index = {label: index for index, label in enumerate(labels_sorted)}
    print(f"\n  {len(labels_sorted)} classes: {', '.join(labels_sorted)}")

    # --- balance ------------------------------------------------------------
    # Classes do not survive extraction equally: N and M lose ~35% of their
    # images to failed hand detection while Y loses ~1%. Left alone, the model
    # sees far more Y than N and its prior tilts accordingly — which makes the
    # already-hard classes harder.
    #
    # Subsampling is done with an even stride across capture order, not by
    # taking the first N rows. Taking the first N would keep only the earliest
    # frames of each recording and throw away whatever variation appeared
    # later, which is exactly the variation worth training on.
    raw_counts = frame["label"].value_counts().to_dict()
    balance_report = {"mode": args.balance, "before": {k: int(v) for k, v in sorted(raw_counts.items())}}

    if args.balance == "min":
        target = int(min(raw_counts.values()))
        smallest_class = min(raw_counts, key=raw_counts.get)
        print(f"\nBalancing every class down to {target:,} rows (smallest: '{smallest_class}')")

        balanced_parts = []
        for label in labels_sorted:
            subset = frame[frame["label"] == label].copy()
            subset["_order"] = subset["source"].map(numeric_suffix)
            subset = subset.sort_values("_order")

            if len(subset) > target:
                # np.linspace gives evenly spaced indices spanning the full range.
                keep = np.linspace(0, len(subset) - 1, target).round().astype(int)
                subset = subset.iloc[np.unique(keep)]

            balanced_parts.append(subset.drop(columns="_order"))

        frame = pd.concat(balanced_parts)
        dropped = sum(raw_counts.values()) - len(frame)
        print(f"  {sum(raw_counts.values()):,} → {len(frame):,} rows ({dropped:,} dropped)")

    balance_report["after"] = {
        k: int(v) for k, v in sorted(frame["label"].value_counts().to_dict().items())
    }

    # --- split ---------------------------------------------------------------
    split_mode = "random (INFLATES accuracy)" if args.random_split else "contiguous by capture order"
    print(f"\nSplitting 70/15/15 — {split_mode}")

    train_parts, val_parts, test_parts = [], [], []

    for label in labels_sorted:
        subset = frame[frame["label"] == label].copy()

        if args.random_split:
            subset = subset.sample(frac=1.0, random_state=args.seed)
        else:
            # Restore capture order so neighbouring frames stay together.
            subset["_order"] = subset["source"].map(numeric_suffix)
            subset = subset.sort_values("_order").drop(columns="_order")

        count = len(subset)
        train_end = int(count * TRAIN_FRACTION)
        val_end = train_end + int(count * VAL_FRACTION)

        train_parts.append(subset.iloc[:train_end])
        val_parts.append(subset.iloc[train_end:val_end])
        test_parts.append(subset.iloc[val_end:])

    def to_arrays(parts: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray]:
        combined = pd.concat(parts)
        features = combined[feature_columns].to_numpy(dtype=np.float32)
        targets = combined["label"].map(label_to_index).to_numpy(dtype=np.int32)
        return features, targets

    X_train, y_train = to_arrays(train_parts)
    X_val, y_val = to_arrays(val_parts)
    X_test, y_test = to_arrays(test_parts)

    print(f"  train {len(X_train):>7,}   val {len(X_val):>6,}   test {len(X_test):>6,}")

    # --- augment (training split only) --------------------------------------
    original_train_size = len(X_train)
    if args.augment_rounds > 0 or not args.no_mirror:
        print(
            f"\nAugmenting training split: {args.augment_rounds} rotated+noisy rounds"
            f"{', plus left-handed mirroring' if not args.no_mirror else ''}"
        )
        X_train, y_train = augment(
            X_train,
            y_train,
            rounds=args.augment_rounds,
            max_rotation_degrees=args.max_rotation,
            noise_std=args.noise_std,
            mirror=not args.no_mirror,
            rng=rng,
        )
        print(f"  train {original_train_size:,} → {len(X_train):,}")

    # Shuffle the training set so augmented copies are not all at the end,
    # which would make each mini-batch homogeneous and destabilise training.
    order = rng.permutation(len(X_train))
    X_train, y_train = X_train[order], y_train[order]

    # --- sanity checks ------------------------------------------------------
    # An invariant violated here means the augmentation is producing samples
    # the model can never see at inference time.
    for name, array in [("train", X_train), ("val", X_val), ("test", X_test)]:
        assert not np.isnan(array).any(), f"{name} contains NaN"
        assert not np.isinf(array).any(), f"{name} contains Inf"
        wrists = array.reshape(-1, 21, 3)[:, 0, :]
        assert np.abs(wrists).max() < 1e-5, f"{name}: wrist is not at the origin"
        max_distance = np.linalg.norm(array.reshape(-1, 21, 3), axis=2).max(axis=1)
        assert np.allclose(max_distance, 1.0, atol=1e-4), f"{name}: scale invariant broken"
    print("\n  invariants OK — wrist at origin, furthest landmark at 1.0, no NaN/Inf")

    # --- write --------------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for name, array in [
        ("X_train", X_train), ("y_train", y_train),
        ("X_val", X_val), ("y_val", y_val),
        ("X_test", X_test), ("y_test", y_test),
    ]:
        np.save(PROCESSED_DIR / f"{name}.npy", array)
    print(f"\nWrote 6 .npy arrays to {PROCESSED_DIR.relative_to(REPO_ROOT)}")

    labels_path = MODELS_DIR / "labels.json"
    labels_path.write_text(
        json.dumps({"classes": labels_sorted, "label_to_index": label_to_index}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {labels_path.relative_to(REPO_ROOT)}")

    manifest = {
        "source_dataset": "ASL Alphabet (grassknoted/asl-alphabet)",
        "source_url": "https://www.kaggle.com/datasets/grassknoted/asl-alphabet",
        "self_recorded_data": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "normalization_version": NORMALIZATION_VERSION,
        "feature_count": SINGLE_HAND_FEATURES,
        "classes": labels_sorted,
        "class_count": len(labels_sorted),
        "dropped_classes": dropped_report,
        "class_balancing": balance_report,
        "split": {
            "mode": "random" if args.random_split else "contiguous_by_capture_order",
            "rationale": (
                "ASL Alphabet frames are consecutive video frames, so a random "
                "split leaks near-duplicate images across train and test and "
                "inflates accuracy. Contiguous blocks keep neighbouring frames "
                "together. The dataset has no signer metadata, so no split can "
                "guarantee an unseen signer in test — that is measured live by "
                "test_realtime.py instead."
            ),
            "train": len(X_train),
            "train_before_augmentation": original_train_size,
            "val": len(X_val),
            "test": len(X_test),
            "fractions": [TRAIN_FRACTION, VAL_FRACTION, round(1 - TRAIN_FRACTION - VAL_FRACTION, 2)],
        },
        "augmentation": {
            "applied_to": "train split only",
            "rotation_rounds": args.augment_rounds,
            "max_rotation_degrees": args.max_rotation,
            "coordinate_noise_std": args.noise_std,
            "horizontal_mirroring": not args.no_mirror,
            "scale_jitter": False,
            "scale_jitter_note": (
                "Deliberately omitted. Normalisation divides by the largest "
                "distance from the wrist, so scaling a sample and re-normalising "
                "returns the original vector — scale jitter is a mathematical "
                "no-op under this representation."
            ),
            "seed": args.seed,
        },
        "class_distribution": {
            "train": {labels_sorted[i]: int(c) for i, c in sorted(Counter(y_train.tolist()).items())},
            "val": {labels_sorted[i]: int(c) for i, c in sorted(Counter(y_val.tolist()).items())},
            "test": {labels_sorted[i]: int(c) for i, c in sorted(Counter(y_test.tolist()).items())},
        },
    }

    manifest_path = MODELS_DIR / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path.relative_to(REPO_ROOT)}")

    print(f"\nShapes:  X_train {X_train.shape}  X_val {X_val.shape}  X_test {X_test.shape}")
    print("Next: python ml/scripts/train_static.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
