#!/usr/bin/env python3
"""Measure the recognition gates: accuracy, and the idle false-positive rate.

WHY BOTH NUMBERS ARE NEEDED
---------------------------
Accuracy alone cannot tell you whether a threshold is right. A model with 40
classes always returns one of them, so a gate that is too loose produces
captions from resting hands — the reported "detecting M at 71% while not
signing". A gate that is too tight produces nothing at all.

So this reports two things against the same thresholds:

  * ACCURACY — of the held-out clips that pass the gates, how many are right,
    and how many are rejected outright (a rejection is a missed caption, not a
    wrong one, and the two matter differently).

  * IDLE FALSE POSITIVES — fed input that contains no sign at all, how often do
    the gates let something through? This is the number that decides whether a
    silent participant generates captions. The target is zero.

Mirrors the gates in frontend/src/config/recognition.js. If those change, run
this again — the two must agree or the measurement is describing other code.

Usage:
    python ml/scripts/measure_gates.py
    python ml/scripts/measure_gates.py --confidence 0.8 --margin 0.2
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

PROCESSED = REPO_ROOT / "ml" / "data" / "processed"
MODELS = REPO_ROOT / "ml" / "models"

# Defaults mirror frontend/src/config/recognition.js
DEFAULT_CONFIDENCE = 0.70
DEFAULT_MARGIN = 0.15
DEFAULT_REST_MOTION = 0.012


def gates(probabilities: np.ndarray, confidence_floor: float, margin_floor: float):
    """Apply the two acceptance gates. Returns (accepted, index, conf, margin)."""
    order = np.argsort(probabilities)[::-1]
    best, second = float(probabilities[order[0]]), float(probabilities[order[1]])
    margin = best - second
    accepted = best >= confidence_floor and margin >= margin_floor
    return accepted, int(order[0]), best, margin


def measure_accuracy(predictor, features, targets, classes, conf, marg, sequence=False):
    """How the gates behave on held-out data that genuinely contains signs."""
    from app.ml.sequence import SequenceBuffer

    accepted = correct = rejected = 0
    for sample, truth in zip(features, targets):
        if sequence:
            buffer = SequenceBuffer()
            probabilities = None
            for frame in sample:
                window = buffer.push(frame)
                if window is not None:
                    _, _, probabilities = predictor.predict(window)
            if probabilities is None:
                rejected += 1
                continue
        else:
            _, _, probabilities = predictor.predict(sample)

        passed, index, _, _ = gates(probabilities, conf, marg)
        if not passed:
            rejected += 1
            continue
        accepted += 1
        if classes[index] == classes[int(truth)]:
            correct += 1

    total = len(targets)
    return {
        "samples": int(total),
        "accepted": accepted,
        "rejected": rejected,
        "rejection_rate": round(rejected / total, 4) if total else 0.0,
        "accuracy_of_accepted": round(correct / accepted, 4) if accepted else None,
        "accuracy_overall": round(correct / total, 4) if total else None,
    }


def measure_idle(predictor, width, conf, marg, sequence=False, trials=400, seed=0):
    """Feed input containing NO sign and count what gets through.

    Three kinds, because they fail differently:

      zeros   — hands out of frame. The strongest case for silence.
      frozen  — one real pose held perfectly still. This is the case the old
                system failed: a resting hand IS a valid handshape, so the
                model answers confidently and only the motion gate can stop it.
      random  — noise in the shape of landmarks. Not a hand at all.
    """
    from app.ml.sequence import SequenceBuffer

    rng = np.random.default_rng(seed)
    results = {}

    def run(name, make_sample):
        leaked = 0
        for _ in range(trials):
            sample = make_sample()
            if sequence:
                buffer = SequenceBuffer()
                probabilities = None
                for frame in sample:
                    window = buffer.push(frame)
                    if window is not None:
                        _, _, probabilities = predictor.predict(window)
                if probabilities is None:
                    continue
            else:
                _, _, probabilities = predictor.predict(sample)
            passed, _, _, _ = gates(probabilities, conf, marg)
            if passed:
                leaked += 1
        results[name] = {
            "trials": trials,
            "passed_the_gates": leaked,
            "false_positive_rate": round(leaked / trials, 4),
        }

    if sequence:
        run("zeros", lambda: np.zeros((30, width), dtype=np.float32))
        # A real pose repeated for every timestep: zero motion.
        pool = np.load(PROCESSED / "X_dyn_test.npy")
        run("frozen_pose", lambda: np.repeat(
            pool[rng.integers(len(pool))][rng.integers(30)][None, :], 30, axis=0))
        run("random", lambda: rng.normal(0, 0.4, (30, width)).astype(np.float32))
    else:
        run("zeros", lambda: np.zeros(width, dtype=np.float32))
        run("random", lambda: rng.normal(0, 0.4, width).astype(np.float32))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    args = parser.parse_args()

    from app.ml.predictor import dynamic_predictor, isl_predictor

    print(f"Gates: confidence >= {args.confidence}, margin >= {args.margin}")
    print("(mirrors frontend/src/config/recognition.js)\n")

    report = {"confidence_floor": args.confidence, "margin_floor": args.margin}

    # --- ISL words ---------------------------------------------------------
    if dynamic_predictor.load():
        classes = json.loads((MODELS / "labels_dynamic.json").read_text())["classes"]
        X = np.load(PROCESSED / "X_dyn_test.npy")
        y = np.load(PROCESSED / "y_dyn_test.npy")

        print("ISL WORDS (dynamic)")
        acc = measure_accuracy(dynamic_predictor, X, y, classes,
                               args.confidence, args.margin, sequence=True)
        print(f"  held-out clips       {acc['samples']}")
        print(f"  rejected by gates    {acc['rejected']} ({acc['rejection_rate']:.1%})")
        print(f"  accuracy of accepted {acc['accuracy_of_accepted']}")
        print(f"  accuracy overall     {acc['accuracy_overall']}")

        idle = measure_idle(dynamic_predictor, X.shape[2],
                            args.confidence, args.margin, sequence=True)
        print("  IDLE FALSE POSITIVES (input with no sign in it):")
        for name, data in idle.items():
            print(f"    {name:<12} {data['passed_the_gates']:>4}/{data['trials']} "
                  f"= {data['false_positive_rate']:.1%}")
        report["isl_words"] = {"accuracy": acc, "idle": idle}
        print()

    # --- ISL fingerspelling ------------------------------------------------
    if isl_predictor.load():
        classes = json.loads((MODELS / "labels_isl.json").read_text())["classes"]
        X = np.load(PROCESSED / "X_isl_test.npy")
        y = np.load(PROCESSED / "y_isl_test.npy")

        print("ISL FINGERSPELLING (static)")
        acc = measure_accuracy(isl_predictor, X, y, classes, args.confidence, args.margin)
        print(f"  held-out samples     {acc['samples']}")
        print(f"  rejected by gates    {acc['rejected']} ({acc['rejection_rate']:.1%})")
        print(f"  accuracy of accepted {acc['accuracy_of_accepted']}")
        print(f"  accuracy overall     {acc['accuracy_overall']}")

        idle = measure_idle(isl_predictor, X.shape[1], args.confidence, args.margin)
        print("  IDLE FALSE POSITIVES:")
        for name, data in idle.items():
            print(f"    {name:<12} {data['passed_the_gates']:>4}/{data['trials']} "
                  f"= {data['false_positive_rate']:.1%}")
        report["isl_letters"] = {"accuracy": acc, "idle": idle}

    output = MODELS / "gate_measurement.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {output.relative_to(REPO_ROOT)}")
    print(
        "\nNote on 'frozen_pose': a resting hand IS a valid handshape, so the\n"
        "model answers it confidently and no confidence gate can reject it.\n"
        "Only the MOTION gate can, and that lives in the browser — these\n"
        "numbers are the worst case with motion gating removed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
