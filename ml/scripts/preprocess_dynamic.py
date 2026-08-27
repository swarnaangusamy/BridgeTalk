#!/usr/bin/env python3
"""Split and augment WLASL landmark sequences for Model B.

THE SPLIT IS THE POINT OF THIS FILE
-----------------------------------
Model A's honest limitation, stated in ml/README.md, is that the ASL Alphabet
dataset carries no signer metadata. Its test split measures "the same hands,
later frames" — a real number, but not the one a user experiences.

**WLASL records `signer_id`.** That makes a stronger evaluation possible here
than anywhere else in this project: hold out entire *people*. A signer-disjoint
split means the test set contains hands the model has genuinely never seen, so
its accuracy answers the question a reviewer actually cares about — "will this
work for someone new?" — rather than "can it recognise frames near ones it
memorised?".

Expect that number to be lower than a random split would give, and expect the
gap to be large. That gap is not a bug to be tuned away; it is the measurement
working correctly. A random split over these sequences would score far higher
and mean far less, because the same person signing the same word twice produces
two near-identical clips, and putting one in train and the other in test grades
the model on something it has effectively already seen.

    --split-strategy signer     (default) hold out whole people
    --split-strategy official   WLASL's own train/val/test fields
    --split-strategy random     stratified by gloss — for comparison only

AUGMENTATION, AND ONE SUBTLETY THAT MATTERS
-------------------------------------------
Applied to the training split only, and never to validation or test — augmented
eval data would mean grading the model on samples we invented.

The subtlety: an all-zero frame means "no hands visible here", and the model's
Masking layer skips exactly those timesteps. Adding Gaussian noise to a zero
frame would make it non-zero, silently un-masking it and teaching the network
that empty frames contain faint hand-shaped noise. Every augmentation below
therefore preserves zero frames exactly.

USAGE
-----
    python ml/scripts/preprocess_dynamic.py
    python ml/scripts/preprocess_dynamic.py --split-strategy official
    python ml/scripts/preprocess_dynamic.py --no-augment
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import numpy as np  # noqa: E402

from app.ml.normalization import (  # noqa: E402
    NUM_LANDMARKS,
    NORMALIZATION_VERSION,
    SEQUENCE_FEATURES,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
)

# A frame is [left_shape(63) | right_shape(63) | left_pos(3) | right_pos(3)].
# Every augmentation below has to treat the position tail as coordinates too:
# rotating the hands but not the path they travel would teach the model a
# motion no signer produces.
POSITION_START = TWO_HAND_FEATURES

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "ml" / "models"

TRAIN_SHARE, VAL_SHARE = 0.70, 0.15

ROTATION_DEGREES = 12.0
NOISE_SIGMA = 0.015


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def split_by_signer(
    glosses: np.ndarray, signer_ids: np.ndarray, seed: int
) -> dict[str, np.ndarray]:
    """Assign whole signers to splits, greedily balancing clip counts.

    Signers are placed largest-first into whichever split is currently furthest
    below its target share. Largest-first matters: placing a signer with 40
    clips after the small ones would overshoot whichever split received them
    and there would be no way to correct it.
    """
    by_signer: dict[int, list[int]] = defaultdict(list)
    for index, signer in enumerate(signer_ids):
        by_signer[int(signer)].append(index)

    order = sorted(by_signer, key=lambda s: (-len(by_signer[s]), s))

    total = len(glosses)
    targets = {
        "train": TRAIN_SHARE * total,
        "val": VAL_SHARE * total,
        "test": (1.0 - TRAIN_SHARE - VAL_SHARE) * total,
    }
    assigned: dict[str, list[int]] = {"train": [], "val": [], "test": []}

    for signer in order:
        deficits = {
            name: targets[name] - len(assigned[name]) for name in assigned
        }
        chosen = max(deficits, key=lambda name: deficits[name])
        assigned[chosen].extend(by_signer[signer])

    return {name: np.array(sorted(indices), dtype=int) for name, indices in assigned.items()}


def split_by_official(official_splits: np.ndarray) -> dict[str, np.ndarray]:
    """Use WLASL's own split fields, so numbers are comparable to the literature."""
    mapping = {"train": [], "val": [], "test": []}
    for index, value in enumerate(official_splits):
        name = str(value).strip().lower()
        if name in mapping:
            mapping[name].append(index)
        else:
            # WLASL occasionally omits or misspells the field; keep the clip in
            # training rather than discarding data we paid CPU time to extract.
            mapping["train"].append(index)
    return {name: np.array(indices, dtype=int) for name, indices in mapping.items()}


def split_randomly(glosses: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    """Stratified-by-gloss random split. For comparison only — it leaks signers."""
    rng = np.random.default_rng(seed)
    assigned: dict[str, list[int]] = {"train": [], "val": [], "test": []}

    for gloss in sorted(set(glosses.tolist())):
        indices = np.where(glosses == gloss)[0]
        rng.shuffle(indices)
        train_end = int(len(indices) * TRAIN_SHARE)
        val_end = train_end + max(1, int(len(indices) * VAL_SHARE))
        assigned["train"].extend(indices[:train_end].tolist())
        assigned["val"].extend(indices[train_end:val_end].tolist())
        assigned["test"].extend(indices[val_end:].tolist())

    return {name: np.array(sorted(indices), dtype=int) for name, indices in assigned.items()}


# ---------------------------------------------------------------------------
# Augmentation
# ---------------------------------------------------------------------------


def _frame_mask(sequence: np.ndarray) -> np.ndarray:
    """True for timesteps that contain at least one detected hand.

    These are the frames the LSTM's Masking layer will attend to. Every
    augmentation restricts itself to them, so masked frames stay exactly zero.
    """
    return np.any(sequence != 0.0, axis=-1)


def rotate_sequence(sequence: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate every hand in the sequence about the wrist, in the image plane.

    One angle for the whole sequence, not one per frame. A per-frame angle
    would make the hands jitter rotationally between timesteps and would teach
    the recurrent layers a motion that no signer produces.
    """
    radians = np.deg2rad(degrees)
    cos, sin = np.cos(radians), np.sin(radians)

    out = sequence.copy()
    live = _frame_mask(sequence)
    if not live.any():
        return out

    for hand in range(2):
        start = hand * SINGLE_HAND_FEATURES
        block = out[live, start : start + SINGLE_HAND_FEATURES].reshape(-1, NUM_LANDMARKS, 3)

        # A hand slot that is entirely zero is an absent hand, not a hand at the
        # origin. Rotating it is harmless (zeros rotate to zeros) but the guard
        # keeps the intent explicit.
        x, y = block[..., 0].copy(), block[..., 1].copy()
        block[..., 0] = x * cos - y * sin
        block[..., 1] = x * sin + y * cos

        out[live, start : start + SINGLE_HAND_FEATURES] = block.reshape(-1, SINGLE_HAND_FEATURES)

    # Rotate the wrist positions by the same angle. Omitting this would rotate
    # each hand's shape while leaving its trajectory pointing the old way.
    for slot in range(2):
        start = POSITION_START + slot * 3
        pos = out[live, start : start + 3]
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = x * cos - y * sin
        pos[:, 1] = x * sin + y * cos
        out[live, start : start + 3] = pos

    return out


def jitter_sequence(sequence: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Add Gaussian coordinate noise to detected frames only."""
    out = sequence.copy()
    live = _frame_mask(sequence)
    if not live.any():
        return out

    noise = rng.normal(0.0, sigma, size=out[live].shape).astype(np.float32)

    # Do not perturb an absent hand's zero block into existence.
    present = out[live] != 0.0
    out[live] = out[live] + noise * present

    return out


def mirror_sequence(sequence: np.ndarray) -> np.ndarray:
    """Mirror left-right: negate x AND swap the two hand slots.

    Swapping the slots is the part that is easy to forget and wrong to omit.
    The feature vector is laid out [left_hand, right_hand] by handedness. A
    person's mirror image signs with the opposite hands, so a mirrored sample
    whose slots were left untouched would claim that a left hand performed the
    right hand's trajectory — teaching the model a sign that does not exist.
    """
    out = sequence.copy()
    live = _frame_mask(sequence)

    for hand in range(2):
        start = hand * SINGLE_HAND_FEATURES
        block = out[:, start : start + SINGLE_HAND_FEATURES].reshape(len(out), NUM_LANDMARKS, 3)
        block[..., 0] *= -1.0
        out[:, start : start + SINGLE_HAND_FEATURES] = block.reshape(len(out), SINGLE_HAND_FEATURES)

    left = out[:, :SINGLE_HAND_FEATURES].copy()
    out[:, :SINGLE_HAND_FEATURES] = out[:, SINGLE_HAND_FEATURES:POSITION_START]
    out[:, SINGLE_HAND_FEATURES:POSITION_START] = left

    # The same two operations on the position tail: mirror the x axis, then
    # swap which hand each path belongs to.
    out[:, POSITION_START::3] *= -1.0
    left_pos = out[:, POSITION_START : POSITION_START + 3].copy()
    out[:, POSITION_START : POSITION_START + 3] = out[:, POSITION_START + 3 :]
    out[:, POSITION_START + 3 :] = left_pos

    # Negating x turned exact zeros into -0.0, which is not `!= 0.0` safe to
    # reason about later. Restore true zeros on frames that had no hands.
    out[~live] = 0.0

    return out


TRANSITION_LABEL = "__transition__"


def build_misaligned_windows(
    sequences: np.ndarray,
    targets: np.ndarray,
    rng: np.random.Generator,
    per_clip: int = 3,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Teach the model what a MISALIGNED window looks like, and what a boundary is.

    THE PROBLEM THIS SOLVES
    -----------------------
    Every training clip is cut to contain exactly one sign, so the model only
    ever sees perfectly aligned windows. Live, a signer does not stop between
    words, and a 30-frame window almost never lines up with a sign — it holds
    the tail of one and the head of the next.

    Measured on a continuous stream built from held-out clips, that showed up
    as deletions: 23 of 120 signs produced no output at all, because no window
    ever looked enough like its training data to clear the confidence gate.

    WHAT THIS BUILDS
    ----------------
    Windows spanning two different clips, cut at a random offset:

        offset  6  ->  24 frames of A, 6 of B    -> still mostly A, label A
        offset 15  ->  15 frames of A, 15 of B   -> neither, label __transition__
        offset 24  ->   6 frames of A, 24 of B   -> mostly B, label B

    The first and third teach tolerance to misalignment. The middle one gives
    the model a way to say **"this is not a word"** — which it previously did
    not have, and without which it must answer every boundary window with one
    of the real classes and hope the smoother filters it out.

    Both hands of this are built from the public dataset. Nothing is recorded.
    """
    if len(sequences) < 2:
        return np.empty((0, *sequences.shape[1:]), np.float32), np.empty(0, np.int64), 0

    length = sequences.shape[1]
    windows: list[np.ndarray] = []
    labels: list[int] = []
    transitions = 0

    # Mostly-A and mostly-B keep their own label; the middle band is a boundary.
    mostly = max(2, int(length * 0.25))       # <= 25% of the other clip
    balanced_low = int(length * 0.40)
    balanced_high = int(length * 0.60)

    for index in range(len(sequences)):
        for _ in range(per_clip):
            other = int(rng.integers(len(sequences)))
            if other == index:
                continue

            offset = int(rng.integers(mostly, length - mostly + 1))
            window = np.concatenate(
                [sequences[index][offset:], sequences[other][:offset]]
            )

            if offset <= mostly:
                labels.append(int(targets[index]))
            elif offset >= length - mostly:
                labels.append(int(targets[other]))
            elif balanced_low <= offset <= balanced_high:
                if targets[index] == targets[other]:
                    # Two clips of the SAME word joined is still that word, not
                    # a boundary. Mislabelling it would teach the opposite.
                    labels.append(int(targets[index]))
                else:
                    labels.append(-1)       # resolved to the transition id later
                    transitions += 1
            else:
                labels.append(int(targets[index] if offset < length // 2 else targets[other]))

            windows.append(window)

    if not windows:
        return np.empty((0, *sequences.shape[1:]), np.float32), np.empty(0, np.int64), 0

    return np.stack(windows).astype(np.float32), np.array(labels, dtype=np.int64), transitions


def augment_training_set(
    sequences: np.ndarray, targets: np.ndarray, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Grow the training split with rotated, noised and mirrored variants."""
    rng = np.random.default_rng(seed)

    grown = [sequences]
    labels = [targets]

    rotated = np.stack(
        [
            rotate_sequence(sequence, rng.uniform(-ROTATION_DEGREES, ROTATION_DEGREES))
            for sequence in sequences
        ]
    )
    grown.append(rotated)
    labels.append(targets)

    noised = np.stack([jitter_sequence(sequence, NOISE_SIGMA, rng) for sequence in sequences])
    grown.append(noised)
    labels.append(targets)

    mirrored = np.stack([mirror_sequence(sequence) for sequence in sequences])
    grown.append(mirrored)
    labels.append(targets)

    return (
        np.concatenate(grown).astype(np.float32),
        np.concatenate(labels).astype(np.int64),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--split-strategy", choices=["signer", "official", "random"], default="signer"
    )
    parser.add_argument("--no-augment", action="store_true")
    parser.add_argument("--no-misaligned", action="store_true",
                        help="Skip boundary/misaligned windows (for comparison)")
    parser.add_argument("--misaligned-per-clip", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    source = PROCESSED_DIR / "dynamic_sequences.npz"
    if not source.is_file():
        print(f"ERROR: {source} not found.", file=sys.stderr)
        print("Run: python ml/scripts/extract_landmarks_video.py", file=sys.stderr)
        return 1

    # Provenance comes from the extraction report, never from a constant here.
    # Hard-coding it meant a manifest that confidently said "WLASL" while
    # describing Indian Sign Language data — the kind of wrong that survives
    # into a report because nothing checks it.
    report_path = PROCESSED_DIR / "video_extraction_report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.is_file()
        else {}
    )

    data = np.load(source, allow_pickle=False)
    sequences = data["sequences"].astype(np.float32)
    glosses = data["glosses"]
    signer_ids = data["signer_ids"]
    official_splits = data["official_splits"]

    print(f"Loaded {sequences.shape[0]:,} sequences of shape {sequences.shape[1:]}")

    class_names = sorted(set(glosses.tolist()))
    class_index = {name: index for index, name in enumerate(class_names)}
    targets = np.array([class_index[g] for g in glosses], dtype=np.int64)

    print(f"Classes: {len(class_names)}   Signers: {len(set(signer_ids.tolist()))}")

    # --- split --------------------------------------------------------------
    # A signer-disjoint split is only possible when the dataset records WHO
    # signed each clip. WLASL does; INCLUDE does not, and extraction stores -1
    # rather than inventing an ID. Silently "succeeding" here would be the worst
    # outcome: every clip lands in one bucket, and the manifest goes on claiming
    # the strongest evaluation this project offers.
    known_signers = sorted({int(s) for s in signer_ids.tolist() if int(s) >= 0})
    strategy = args.split_strategy

    if strategy == "signer" and len(known_signers) < 3:
        print("\n  NOTE: this dataset does not record signer identity"
              f" ({len(known_signers)} known signers).")
        print("  A signer-disjoint split is impossible, so falling back to a")
        print("  stratified random split. The resulting accuracy answers")
        print('  "can it recognise clips like the ones it trained on?" rather')
        print('  than "will it work for someone new?" — a weaker question.')
        print("  This is recorded as signer_disjoint: false in the manifest so")
        print("  nothing downstream can overstate it.")
        strategy = "random"

    if strategy == "signer":
        indices = split_by_signer(glosses, signer_ids, args.seed)
    elif strategy == "official":
        indices = split_by_official(official_splits)
    else:
        indices = split_randomly(glosses, args.seed)

    print(f"\nSplit strategy: {strategy}"
          f"{' (requested: ' + args.split_strategy + ')' if strategy != args.split_strategy else ''}")
    for name in ("train", "val", "test"):
        chosen = indices[name]
        signers = sorted({int(signer_ids[i]) for i in chosen}) if len(chosen) else []
        print(f"  {name:<6} {len(chosen):>5} clips   {len(signers):>2} signers")

    # --- coverage check -----------------------------------------------------
    # A gloss missing from val or test is not a crash, but it silently changes
    # what the reported accuracy means, so it is stated rather than buried.
    problems: list[str] = []
    for name in ("train", "val", "test"):
        present = {glosses[i] for i in indices[name]}
        missing = [gloss for gloss in class_names if gloss not in present]
        if missing:
            problems.append(f"{name}: missing {', '.join(missing)}")

    if problems:
        print("\n  WARNING — not every gloss appears in every split:")
        for problem in problems:
            print(f"    {problem}")
        print("\n  This is the cost of a signer-disjoint split on a dataset where")
        print("  some glosses come from very few people. The accuracy figure stays")
        print("  valid, but it is computed over the glosses that ARE present.")
        print("  --split-strategy official trades signer-disjointness for coverage.")

    if len(indices["train"]) == 0 or len(indices["test"]) == 0:
        print("\nERROR: a split came out empty.", file=sys.stderr)
        print("Too few clips, or too few signers to hold any out.", file=sys.stderr)
        print("Try --split-strategy random, or extract more clips per gloss.",
              file=sys.stderr)
        return 1

    X_train = sequences[indices["train"]]
    y_train = targets[indices["train"]]
    X_val = sequences[indices["val"]]
    y_val = targets[indices["val"]]
    X_test = sequences[indices["test"]]
    y_test = targets[indices["test"]]

    # --- misaligned windows + the transition class ---------------------------
    # Added BEFORE the geometric augmentation, so rotation, noise and mirroring
    # apply to boundary windows too. A boundary the model has only seen from
    # one camera angle is barely a boundary.
    transition_index: int | None = None

    if not args.no_misaligned:
        rng_windows = np.random.default_rng(args.seed + 1)
        extra_X, extra_y, transition_count = build_misaligned_windows(
            X_train, y_train, rng_windows, per_clip=args.misaligned_per_clip
        )

        if len(extra_X):
            if transition_count:
                # The transition class is appended last, so every existing
                # label index keeps its meaning and labels_dynamic.json stays
                # aligned with models trained before this existed.
                transition_index = len(class_names)
                class_names = class_names + [TRANSITION_LABEL]
                extra_y = np.where(extra_y == -1, transition_index, extra_y)

            X_train = np.concatenate([X_train, extra_X])
            y_train = np.concatenate([y_train, extra_y])

            print(f"\nMisaligned windows: +{len(extra_X):,} "
                  f"({transition_count:,} of them boundaries)")
            print("  teaches tolerance to windows that straddle two signs, and")
            print("  gives the model a way to say 'this is not a word'")

    # --- augment ------------------------------------------------------------
    if not args.no_augment:
        before = len(X_train)
        X_train, y_train = augment_training_set(X_train, y_train, args.seed)
        print(f"\nAugmented training split: {before:,} -> {len(X_train):,} sequences")
        print("  rotation ±12°, Gaussian noise σ=0.015, left-right mirroring")
        print("  (training split only; masked frames left exactly zero)")

    # --- save ---------------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, features, labels in (
        ("train", X_train, y_train),
        ("val", X_val, y_val),
        ("test", X_test, y_test),
    ):
        np.save(PROCESSED_DIR / f"X_dyn_{name}.npy", features)
        np.save(PROCESSED_DIR / f"y_dyn_{name}.npy", labels)

    print(f"\nTrain {X_train.shape}   Val {X_val.shape}   Test {X_test.shape}")

    labels_path = MODELS_DIR / "labels_dynamic.json"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(
        json.dumps(
            {
                "classes": class_names,
                "count": len(class_names),
                # The backend never shows this to a user; it emits nothing when
                # the transition class wins. Recorded so the label list is
                # self-describing rather than having a mystery entry.
                "transition_class": TRANSITION_LABEL if transition_index is not None else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {labels_path.relative_to(REPO_ROOT)}")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dataset": report.get("source_dataset", "unknown — extraction report missing"),
        "language": report.get("language", "unknown"),
        "citation": report.get("citation"),
        "self_recorded_data": False,
        "normalization_version": NORMALIZATION_VERSION,
        "sequence_length": int(sequences.shape[1]),
        "features_per_frame": TWO_HAND_FEATURES,
        "classes": class_names,
        "transition_class": TRANSITION_LABEL if transition_index is not None else None,
        "split_strategy": strategy,
        "split_strategy_requested": args.split_strategy,
        # The single most important honesty flag in this file. The backend
        # forwards it to the UI, which only says "tested on unseen signers"
        # when it is true.
        "signer_disjoint": strategy == "signer",
        "signers_recorded_by_dataset": bool(known_signers),
        "splits": {
            "train": int(len(X_train)),
            "val": int(len(X_val)),
            "test": int(len(X_test)),
        },
        "signers_per_split": {
            name: sorted({int(signer_ids[i]) for i in indices[name]})
            for name in ("train", "val", "test")
        },
        "class_distribution": {
            name: int(count)
            for name, count in sorted(Counter(glosses.tolist()).items())
        },
        "coverage_warnings": problems,
        "augmentation": {
            "applied": not args.no_augment,
            "split": "train only",
            "rotation_degrees": ROTATION_DEGREES,
            "noise_sigma": NOISE_SIGMA,
            "mirroring": True,
            "masked_frames_preserved": True,
        },
        "seed": args.seed,
    }

    manifest_path = MODELS_DIR / "dynamic_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path.relative_to(REPO_ROOT)}")

    print("\nNext: python ml/scripts/train_dynamic.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
