#!/usr/bin/env python3
"""Measure recognition on CONTINUOUS signing, not on pre-cut clips.

WHY THIS SCRIPT EXISTS
----------------------
`evaluate.py` reports 89.9% on the test split. That number is real and it is
also not what a user experiences, because it grades the model on clips that
someone already cut to contain exactly one sign.

A person signing a sentence does not stop between words, does not drop their
hands, and does not tell the system where one sign ends. The model therefore
faces windows that straddle two signs and windows that sit in the transition
between them — neither of which it was ever trained on, and both of which it
must answer with one of its N words because it has no way to say "this is not
a sign".

This script builds that harder input out of the same held-out test clips:
concatenate them end to end with NO gap, push the frames through the real
`SequenceBuffer`, the real predictor and the real smoother, and compare the
words that come out against the words that went in.

WHAT IT REPORTS
---------------
Word Error Rate, the standard measure for this, decomposed so the failure mode
is visible rather than averaged away:

    substitutions  a word was recognised as the wrong word
    deletions      a word was signed and nothing came out
    insertions     a word came out that was never signed
                   (usually a window straddling two signs)

WER of 0% is perfect; WER can exceed 100% when insertions pile up.

Usage:
    python ml/scripts/evaluate_continuous.py
    python ml/scripts/evaluate_continuous.py --sentences 40 --words-per-sentence 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.predictor import dynamic_predictor  # noqa: E402
from app.ml.sequence import SequenceBuffer  # noqa: E402
from app.ml.smoothing import PredictionSmoother, SmoothingConfig  # noqa: E402

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "ml" / "models"


def edit_ops(reference: list[str], hypothesis: list[str]) -> dict[str, int]:
    """Levenshtein alignment, keeping the three error types apart.

    A single WER number hides which problem you have. Deletions mean signs are
    being missed; insertions mean the system is inventing words in the gaps
    between them. Those call for opposite fixes, so they are counted separately.
    """
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = np.zeros((rows, cols), dtype=np.int32)
    cost[:, 0] = np.arange(rows)
    cost[0, :] = np.arange(cols)

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                cost[i, j] = cost[i - 1, j - 1]
            else:
                cost[i, j] = 1 + min(cost[i - 1, j - 1], cost[i - 1, j], cost[i, j - 1])

    # Walk back to attribute each error to a type.
    i, j = len(reference), len(hypothesis)
    ops = {"substitutions": 0, "deletions": 0, "insertions": 0, "hits": 0}
    while i > 0 or j > 0:
        if i > 0 and j > 0 and reference[i - 1] == hypothesis[j - 1] and cost[i, j] == cost[i - 1, j - 1]:
            ops["hits"] += 1; i -= 1; j -= 1
        elif i > 0 and j > 0 and cost[i, j] == cost[i - 1, j - 1] + 1:
            ops["substitutions"] += 1; i -= 1; j -= 1
        elif i > 0 and cost[i, j] == cost[i - 1, j] + 1:
            ops["deletions"] += 1; i -= 1
        else:
            ops["insertions"] += 1; j -= 1
    return ops


def build_stream(
    clips: np.ndarray, labels: list[str], indices: list[int], gap_frames: int
) -> tuple[np.ndarray, list[str]]:
    """Concatenate clips into one continuous stream.

    `gap_frames` of empty (hands-down) frames between signs models the OLD
    demo instruction. Zero models what a real signer does.
    """
    frames: list[np.ndarray] = []
    spoken: list[str] = []

    for position, index in enumerate(indices):
        frames.extend(clips[index])
        spoken.append(labels[index])
        if gap_frames and position < len(indices) - 1:
            frames.extend(np.zeros((gap_frames, clips.shape[2]), dtype=np.float32))

    return np.stack(frames), spoken


def run_stream(stream: np.ndarray) -> list[str]:
    """Push a stream through the real live path and collect emitted words."""
    buffer = SequenceBuffer()
    smoother = PredictionSmoother(SmoothingConfig.for_dynamic(), word_mode=True)

    emitted: list[str] = []
    now_ms = 0.0

    for frame in stream:
        # 10 FPS is the client's send rate, so each frame is 100 ms of clock.
        now_ms += 100.0

        is_empty = bool(np.all(frame == 0.0))
        window = buffer.push(None if is_empty else frame)

        if window is None:
            if is_empty:
                smoother.push(None, 0.0, now_ms=now_ms)
            continue

        label, confidence, _ = dynamic_predictor.predict(window)
        result = smoother.push(label, confidence, now_ms=now_ms)
        if result.emitted is not None:
            emitted.append(result.emitted)

    return emitted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sentences", type=int, default=30)
    parser.add_argument("--words-per-sentence", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--gaps", type=int, nargs="+", default=[0, 10],
        help="Empty frames inserted between signs. 0 = continuous signing.",
    )
    args = parser.parse_args()

    if not dynamic_predictor.load():
        print(f"ERROR: {dynamic_predictor.load_error}", file=sys.stderr)
        return 1

    features = np.load(PROCESSED_DIR / "X_dyn_test.npy")
    targets = np.load(PROCESSED_DIR / "y_dyn_test.npy")
    class_names = json.loads(
        (MODELS_DIR / "labels_dynamic.json").read_text(encoding="utf-8")
    )["classes"]
    labels = [class_names[index] for index in targets]

    print(f"Model: {len(class_names)} words   Test clips: {len(features)}")
    print(f"Sentences: {args.sentences} x {args.words_per_sentence} words\n")

    rng = np.random.default_rng(args.seed)
    sentences = [
        list(rng.choice(len(features), size=args.words_per_sentence, replace=False))
        for _ in range(args.sentences)
    ]

    print(f"{'gap':>5}  {'WER':>8}  {'sub':>5}  {'del':>5}  {'ins':>5}  {'hits':>5}   what this models")
    print("-" * 84)

    report = {}
    for gap in args.gaps:
        totals = {"substitutions": 0, "deletions": 0, "insertions": 0, "hits": 0}
        reference_length = 0

        for indices in sentences:
            stream, spoken = build_stream(features, labels, indices, gap)
            heard = run_stream(stream)
            ops = edit_ops(spoken, heard)
            for key in totals:
                totals[key] += ops[key]
            reference_length += len(spoken)

        errors = totals["substitutions"] + totals["deletions"] + totals["insertions"]
        wer = errors / max(1, reference_length)

        description = (
            "continuous — hands never drop" if gap == 0
            else f"{gap} empty frames ({gap / 10:.1f}s pause) between signs"
        )
        print(f"{gap:>5}  {wer:>7.1%}  {totals['substitutions']:>5} "
              f"{totals['deletions']:>5} {totals['insertions']:>5} "
              f"{totals['hits']:>5}   {description}")

        report[f"gap_{gap}"] = {
            "word_error_rate": round(float(wer), 4),
            "reference_words": reference_length,
            **totals,
        }

    print()
    print("Deletions mean signs are being missed entirely; insertions mean words")
    print("are being invented between real ones. They need opposite fixes.")

    output = MODELS_DIR / "continuous_evaluation_report.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
