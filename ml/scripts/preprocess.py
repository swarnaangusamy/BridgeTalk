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

from app.ml.normalization import (  # noqa: E402
    NORMALIZATION_VERSION,
    NUM_LANDMARKS,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
)

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


def _as_hands(features: np.ndarray, hands: int) -> np.ndarray:
    """Reshape a flat feature batch into (n, hands, 21, 3).

    Everything below operates per hand. That is not cosmetic: a two-handed
    sample holds two INDEPENDENT hands, each with its own wrist at its own
    origin, and treating the 42 points as one hand would subtract the left
    wrist from the right hand's landmarks and destroy the sample.
    """
    return features.reshape(-1, hands, NUM_LANDMARKS, 3).copy()


def _hand_present(points: np.ndarray) -> np.ndarray:
    """(n, hands) mask — False where a hand slot is entirely zero.

    A zero slot means "this hand was not visible", which is a real and common
    state for ISL: several letters are one-handed, and MediaPipe loses a hand
    to occlusion regularly. Augmentation must leave those slots exactly zero,
    or it teaches the model that an absent hand looks like faint noise.
    """
    return np.any(points != 0.0, axis=(2, 3))


def rotate_2d(features: np.ndarray, angle_radians: float, hands: int = 1) -> np.ndarray:
    """Rotate landmarks in the image plane around the wrist.

    Simulates the hand being tilted. Only x and y are rotated: z is MediaPipe's
    depth estimate, which an in-plane tilt does not change.

    Both hands rotate by the SAME angle. Rotating them independently would
    model the two hands tilting in opposite directions, which is not a thing
    that happens when a person tilts their whole posture.

    Args:
        features: (n, 63) or (n, 126) normalised vectors.
        angle_radians: rotation angle.
        hands: 1 for ASL, 2 for ISL.
    """
    points = _as_hands(features, hands)
    cos_a, sin_a = np.cos(angle_radians), np.sin(angle_radians)

    x = points[..., 0].copy()
    y = points[..., 1].copy()
    points[..., 0] = x * cos_a - y * sin_a
    points[..., 1] = x * sin_a + y * cos_a

    # Rotating zeros yields zeros, so absent hands survive untouched.
    return points.reshape(len(features), -1)


def renormalize(features: np.ndarray, hands: int = 1) -> np.ndarray:
    """Re-apply the wrist-centre / unit-scale invariants after augmentation.

    Mirrors backend/app/ml/normalization.py exactly, but vectorised across a
    whole batch. Augmented samples must satisfy the same invariants as live
    input, or we would be training on data the model can never encounter.

    Applied PER HAND. Each hand is centred on its own wrist and scaled by its
    own furthest landmark, exactly as normalize_hands does one hand at a time.
    """
    points = _as_hands(features, hands)
    present = _hand_present(points)

    # Translate: each hand's wrist back to its own origin.
    points -= points[:, :, 0:1, :]

    # Scale: each hand's furthest landmark back to distance 1.
    distances = np.linalg.norm(points, axis=3)              # (n, hands, 21)
    scales = distances.max(axis=2)[:, :, None, None]        # (n, hands, 1, 1)
    scales = np.where(scales < 1e-8, 1.0, scales)           # avoid dividing by zero

    points = points / scales

    # An absent hand must come back out as exactly zero. Centring a zero slot
    # leaves zeros, but this makes the guarantee explicit rather than incidental.
    points[~present] = 0.0

    return points.reshape(len(features), -1).astype(np.float32)


def mirror(features: np.ndarray, hands: int = 1) -> np.ndarray:
    """Mirror left-right. For two hands, this also SWAPS the hand slots.

    Mirroring in x turns a right hand into a left hand. The landmark indices
    stay the same — index 4 is still the thumb tip — so no re-ordering within
    a hand is needed, unlike mirroring an image.

    The slot swap is the part that is easy to miss and wrong to omit. A
    two-handed feature vector is laid out [left(63), right(63)] by handedness.
    A person's mirror image signs with the opposite hands, so negating x
    without swapping the slots claims the left hand performed the right hand's
    shape — a letter that does not exist in any alphabet. Nothing downstream
    would complain; the model would simply learn something false.
    """
    points = _as_hands(features, hands)
    present = _hand_present(points)

    points[..., 0] *= -1.0

    if hands == 2:
        points = points[:, ::-1, :, :].copy()
        present = present[:, ::-1]

    # Negating x turns exact zeros into -0.0. Restore true zeros so an absent
    # hand stays detectably absent.
    points[~present] = 0.0

    return points.reshape(len(features), -1).astype(np.float32)


def augment(
    features: np.ndarray,
    labels: np.ndarray,
    rounds: int,
    max_rotation_degrees: float,
    noise_std: float,
    mirror_enabled: bool,
    rng: np.random.Generator,
    hands: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate augmented copies of the training set.

    Args:
        rounds: how many augmented copies to produce per original sample.
        max_rotation_degrees: in-plane rotation range, +/- this value.
        noise_std: standard deviation of Gaussian noise added per coordinate,
            in normalised units (where the hand spans 1.0).
        mirror_enabled: also produce a horizontally mirrored copy. This matters
            for accessibility rather than for accuracy: it teaches the model
            left-handed signing, which the dataset contains almost none of.
        hands: 1 for ASL, 2 for ISL.
    """
    augmented_features = [features]
    augmented_labels = [labels]

    for _ in range(rounds):
        # Rotating the batch by a single sampled angle per round and adding
        # per-sample noise gives comparable diversity to per-sample rotation,
        # far faster.
        # SEED ANCHOR — deliberately draws and discards len(features) values.
        #
        # This looks like dead code and nearly was: an earlier version sampled a
        # per-sample angle array here, then rotated the whole batch by a single
        # angle instead, leaving the array unused. Deleting it is tempting and
        # changes nothing about what augmentation *does* — but it shifts the RNG
        # stream, which changes every augmented sample, which moves the model's
        # test accuracy (measured: 90.53% -> 90.81%).
        #
        # It is kept so that the accuracy reported in the README, in
        # metadata.json and on the committed confusion matrix stays exactly
        # reproducible from this seed. Freezing a published number is a real
        # reason to keep a no-op; leaving it undocumented was not.
        _seed_anchor = rng.uniform(
            -np.radians(max_rotation_degrees), np.radians(max_rotation_degrees),
            size=len(features),
        )
        del _seed_anchor

        rotated = rotate_2d(
            features,
            float(rng.uniform(
                -np.radians(max_rotation_degrees), np.radians(max_rotation_degrees)
            )),
            hands,
        )

        noise = rng.normal(0.0, noise_std, size=rotated.shape).astype(np.float32)

        # Do not perturb an absent hand's zero block into existence. Without
        # this mask, every one-handed ISL letter would gain a faint second
        # hand made of noise.
        live = np.repeat(
            _hand_present(_as_hands(rotated, hands)),
            rotated.shape[1] // hands,
            axis=1,
        )
        noisy = rotated + noise * live

        augmented_features.append(renormalize(noisy, hands))
        augmented_labels.append(labels)

    if mirror_enabled:
        augmented_features.append(renormalize(mirror(features, hands), hands))
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
    parser.add_argument(
        "--split-by-pose", action="store_true",
        help="Hold out whole near-duplicate pose clusters. Use for datasets "
             "with scattered duplicates (the ISL image set) where an "
             "index-based split leaks copies across the boundary.",
    )
    parser.add_argument(
        "--pose-threshold", type=float, default=0.5,
        help="Distance below which two landmark vectors are the same pose. "
             "Two DIFFERENT ISL signs sit ~4.0 apart, so 0.5 is tight.",
    )
    parser.add_argument(
        "--dataset",
        choices=["asl", "isl"],
        default="asl",
        help="asl = one-handed (63 features) · isl = two-handed (126 features)",
    )
    args = parser.parse_args()

    # ISL reads a different CSV and writes a different set of arrays, so that
    # training an ISL model never silently consumes ASL landmarks.
    config = {
        "asl": {"csv": "static_landmarks.csv", "prefix": "", "hands": 1,
                "labels": "labels.json", "manifest": "dataset_manifest.json",
                "title": "ASL Alphabet (grassknoted/asl-alphabet)"},
        "isl": {"csv": "isl_landmarks.csv", "prefix": "isl_", "hands": 2,
                "labels": "labels_isl.json", "manifest": "isl_dataset_manifest.json",
                "title": "Indian Sign Language alphabet"},
    }[args.dataset]

    hands = config["hands"]
    expected_features = SINGLE_HAND_FEATURES if hands == 1 else TWO_HAND_FEATURES

    # Only override the default input when the user did not pass one.
    if args.input == INPUT_CSV and args.dataset != "asl":
        args.input = PROCESSED_DIR / config["csv"]

    if not args.input.is_file():
        print(f"ERROR: {args.input} not found.", file=sys.stderr)
        print(
            f"Run: python ml/scripts/extract_landmarks_images.py "
            f"--dataset {args.dataset}",
            file=sys.stderr,
        )
        return 1

    rng = np.random.default_rng(args.seed)

    print(f"Reading {args.input.relative_to(REPO_ROOT)}")
    # `label` is read as a string explicitly. Without this, pandas infers the
    # column's type per chunk, so an alphabet containing digit classes — ISL
    # has 1-9 alongside A-Z — comes back with some labels as int and some as
    # str. Everything downstream then breaks in confusing ways: sorting raises
    # TypeError comparing str to int, and the label-to-index map would key
    # 1 and "1" separately. ASL never hit this because none of its class names
    # look numeric.
    frame = pd.read_csv(args.input, dtype={"label": str})
    print(f"  {len(frame):,} rows, {len(frame.columns)} columns")

    feature_columns = [f"f{i}" for i in range(expected_features)]
    missing = set(feature_columns) - set(frame.columns)
    if missing:
        print(f"ERROR: CSV is missing feature columns: {sorted(missing)[:5]}…", file=sys.stderr)
        print(
            f"  Expected {expected_features} features for --dataset {args.dataset} "
            f"({hands} hand{'s' if hands > 1 else ''}).",
            file=sys.stderr,
        )
        print("  This usually means the CSV was extracted for the other alphabet.",
              file=sys.stderr)
        return 1

    print(f"  alphabet: {config['title']}  ({hands} hand"
          f"{'s' if hands > 1 else ''}, {expected_features} features)")

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
    def pose_clusters(subset: pd.DataFrame, threshold: float) -> np.ndarray:
        """Group near-identical landmark vectors into pose clusters.

        WHY THIS IS NEEDED
        ------------------
        Contiguous-by-capture-order splitting assumes neighbouring frames are
        similar and distant frames are not. That holds for ASL Alphabet, whose
        images are consecutive video frames.

        It does NOT hold for the ISL image set, which contains many
        near-identical copies of a small number of real hand poses, scattered
        throughout the folder rather than adjacent. Measured on this dataset:
        41,609 images collapse to 1,159 distinct poses (2.8%), and some classes
        have a single pose across 1,200 images.

        With duplicates scattered, ANY index-based split puts copies of the same
        pose on both sides. The result is a model tested on images it has
        effectively already seen: 99.75% top-1, and a median nearest-neighbour
        distance from test to train of 0.10 when two different signs sit 4.0
        apart. That number measures duplication, not recognition.

        Greedy single-pass clustering is enough here and is O(n x clusters)
        rather than O(n^2): with ~33 clusters per class the inner comparison is
        tiny, and the clusters are far apart relative to the threshold so the
        order rows arrive in does not change the grouping meaningfully.
        """
        values = subset[feature_columns].to_numpy(dtype=np.float32)
        centres: list[np.ndarray] = []
        assignment = np.empty(len(values), dtype=np.int32)

        for row_index, vector in enumerate(values):
            if centres:
                distances = np.sqrt(((np.asarray(centres) - vector) ** 2).sum(axis=1))
                nearest = int(distances.argmin())
                if distances[nearest] <= threshold:
                    assignment[row_index] = nearest
                    continue
            centres.append(vector)
            assignment[row_index] = len(centres) - 1

        return assignment

    split_mode = (
        "random (INFLATES accuracy)" if args.random_split
        else "pose-disjoint (whole near-duplicate clusters held out)" if args.split_by_pose
        else "contiguous by capture order"
    )
    print(f"\nSplitting 70/15/15 — {split_mode}")

    train_parts, val_parts, test_parts = [], [], []
    # Classes whose every image is one pose — they cannot contribute a
    # held-out sample, and that must be reported rather than hidden.
    unsplittable: list[tuple[str, int, int]] = []

    for label in labels_sorted:
        subset = frame[frame["label"] == label].copy()

        if args.split_by_pose:
            # Hold out whole pose clusters, so no copy of a test pose can
            # appear in training. Clusters are assigned, not rows.
            subset = subset.copy()
            subset["_cluster"] = pose_clusters(subset, args.pose_threshold)

            cluster_ids = subset["_cluster"].unique()
            # Shuffle cluster IDS (not rows) so which poses are held out does
            # not depend on folder order, while keeping each cluster intact.
            rng.shuffle(cluster_ids)

            n_clusters = len(cluster_ids)
            if n_clusters < 3:
                # Nothing can be held out: every image of this class is the
                # same pose. Keep it in training so the class still exists in
                # the label space, and record it — a class that cannot appear
                # in the test set must not be silently counted as evaluated.
                unsplittable.append((label, n_clusters, len(subset)))
                train_parts.append(subset.drop(columns="_cluster"))
                continue

            train_cut = max(1, int(n_clusters * TRAIN_FRACTION))
            val_cut = max(train_cut + 1, int(n_clusters * (TRAIN_FRACTION + VAL_FRACTION)))
            val_cut = min(val_cut, n_clusters - 1)

            groups = {
                "train": set(cluster_ids[:train_cut]),
                "val": set(cluster_ids[train_cut:val_cut]),
                "test": set(cluster_ids[val_cut:]),
            }
            for name, parts in (("train", train_parts), ("val", val_parts), ("test", test_parts)):
                rows = subset[subset["_cluster"].isin(groups[name])]
                if len(rows):
                    parts.append(rows.drop(columns="_cluster"))
            continue

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

    if unsplittable:
        print(f"\n  WARNING — {len(unsplittable)} class(es) have fewer than 3 distinct")
        print("  poses, so nothing can be held out for them. They stay in TRAINING")
        print("  and are absent from val/test. The reported accuracy therefore does")
        print("  not cover them:")
        for label, clusters, rows in unsplittable:
            print(f"    '{label}': {clusters} pose(s) across {rows:,} images")

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
            mirror_enabled=not args.no_mirror,
            rng=rng,
            hands=hands,
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
        if len(array) == 0:
            continue

        assert not np.isnan(array).any(), f"{name} contains NaN"
        assert not np.isinf(array).any(), f"{name} contains Inf"

        # One row of 126 features is TWO hands, so flattening to (-1, 21, 3)
        # yields one entry per hand rather than per sample — which is exactly
        # what we want to check, since each hand carries the invariants
        # independently.
        blocks = array.reshape(-1, NUM_LANDMARKS, 3)

        # An all-zero block is an ABSENT hand, not a broken one. Several ISL
        # letters are genuinely one-handed and MediaPipe loses a hand to
        # occlusion constantly, so those rows are expected and must be excluded
        # from the scale check — their scale is undefined, not 1.0.
        present = np.any(blocks != 0.0, axis=(1, 2))
        assert present.any(), f"{name}: every hand is empty"

        live = blocks[present]

        assert np.abs(live[:, 0, :]).max() < 1e-5, f"{name}: wrist is not at the origin"

        max_distance = np.linalg.norm(live, axis=2).max(axis=1)
        assert np.allclose(max_distance, 1.0, atol=1e-4), f"{name}: scale invariant broken"

        absent = int((~present).sum())
        if absent:
            print(f"  {name}: {absent:,} of {len(blocks):,} hand slots empty "
                  f"({absent / len(blocks):.1%}) — one-handed letters or occlusion")

    print("\n  invariants OK — wrist at origin, furthest landmark at 1.0, no NaN/Inf")

    # --- write --------------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # The prefix keeps ISL arrays beside the ASL ones rather than overwriting
    # them — X_isl_train.npy next to X_train.npy — so both models stay
    # reproducible from one extraction run each.
    prefix = config["prefix"]
    for name, array in [
        ("X_train", X_train), ("y_train", y_train),
        ("X_val", X_val), ("y_val", y_val),
        ("X_test", X_test), ("y_test", y_test),
    ]:
        stem, _, split = name.partition("_")
        np.save(PROCESSED_DIR / f"{stem}_{prefix}{split}.npy", array)
    print(f"\nWrote 6 .npy arrays to {PROCESSED_DIR.relative_to(REPO_ROOT)}")

    labels_path = MODELS_DIR / config["labels"]
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
        "feature_count": expected_features,
        "num_hands": hands,
        "alphabet": config["title"],
        "classes": labels_sorted,
        "class_count": len(labels_sorted),
        "dropped_classes": dropped_report,
        "class_balancing": balance_report,
        "split": {
            "mode": (
                "random" if args.random_split
                else "pose_disjoint" if args.split_by_pose
                else "contiguous_by_capture_order"
            ),
            "pose_threshold": args.pose_threshold if args.split_by_pose else None,
            "classes_with_no_held_out_poses": [
                {"label": label, "distinct_poses": clusters, "images": rows}
                for label, clusters, rows in unsplittable
            ],
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

    manifest_path = MODELS_DIR / config["manifest"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path.relative_to(REPO_ROOT)}")

    print(f"\nShapes:  X_train {X_train.shape}  X_val {X_val.shape}  X_test {X_test.shape}")
    print("Next: python ml/scripts/train_static.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
