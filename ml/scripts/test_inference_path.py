#!/usr/bin/env python3
"""Feed held-out samples through the LIVE inference path and report accuracy.

WHY THIS IS NOT THE SAME AS evaluate.py
---------------------------------------
`evaluate.py` loads the .npy arrays that preprocessing wrote and calls the
model. That measures the model.

This measures the **path the browser actually uses**: the predictor the backend
loads at startup, the compiled inference graph, the normalisation the WebSocket
handler calls, and — for word signs — the sliding window and the smoothing
layer. Those are different code than the training pipeline, and a mismatch
between them is the classic silent failure of this kind of project: high
training accuracy, garbage live predictions, and nothing in any log.

A gap between this number and evaluate.py's is the thing to investigate. They
should agree closely; where they do not, something in the serving path differs
from the training path.

Usage:
    python ml/scripts/test_inference_path.py              # every loaded model
    python ml/scripts/test_inference_path.py --model isl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

PROCESSED = REPO_ROOT / "ml" / "data" / "processed"
MODELS = REPO_ROOT / "ml" / "models"


def load_split(prefix: str, split: str = "test"):
    x = PROCESSED / f"X_{prefix}{split}.npy"
    y = PROCESSED / f"y_{prefix}{split}.npy"
    if not x.is_file() or not y.is_file():
        return None, None
    return np.load(x), np.load(y)


def check_static(name: str, predictor, prefix: str, labels_file: str) -> dict | None:
    """Single-frame models: ASL letters and ISL fingerspelling."""
    if not predictor.load():
        print(f"  {name}: not loaded — {predictor.load_error}")
        return None

    features, targets = load_split(prefix)
    if features is None:
        print(f"  {name}: no held-out split on disk (run preprocess first)")
        return None

    classes = json.loads((MODELS / labels_file).read_text())["classes"]

    correct = 0
    latencies = []
    for vector, truth in zip(features, targets):
        started = time.perf_counter()
        # Exactly the call the WebSocket handler makes.
        label, _confidence, _probs = predictor.predict(vector)
        latencies.append((time.perf_counter() - started) * 1000)
        if label == classes[int(truth)]:
            correct += 1

    accuracy = correct / len(targets)
    print(f"  {name}: {accuracy:.4f} top-1 over {len(targets):,} held-out samples")
    print(f"     median latency {np.median(latencies):.2f} ms  p95 {np.percentile(latencies, 95):.2f} ms")
    return {
        "model": name,
        "samples": int(len(targets)),
        "top1_accuracy": round(float(accuracy), 4),
        "median_latency_ms": round(float(np.median(latencies)), 2),
    }


def check_dynamic(name: str, predictor) -> dict | None:
    """Word signs, pushed through the real SequenceBuffer frame by frame.

    This is the one that most needs checking: the buffer centres the position
    channels over the window, and if that differed from what extraction did to
    the training clips the model would be fed inputs it never saw.
    """
    from app.ml.sequence import SequenceBuffer

    if not predictor.load():
        print(f"  {name}: not loaded — {predictor.load_error}")
        return None

    features, targets = load_split("dyn_")
    if features is None:
        print(f"  {name}: no held-out split on disk")
        return None

    classes = json.loads((MODELS / "labels_dynamic.json").read_text())["classes"]

    correct = 0
    judged = 0
    latencies = []

    for clip, truth in zip(features, targets):
        buffer = SequenceBuffer()
        last = None
        for frame in clip:
            window = buffer.push(frame)
            if window is None:
                continue
            started = time.perf_counter()
            label, _confidence, _probs = predictor.predict(window)
            latencies.append((time.perf_counter() - started) * 1000)
            last = label

        if last is None:
            # The buffer never produced a window: the clip was too sparse to
            # classify. Counted separately rather than as a wrong answer.
            continue
        judged += 1
        if last == classes[int(truth)]:
            correct += 1

    if judged == 0:
        print(f"  {name}: no clip produced a window")
        return None

    accuracy = correct / judged
    skipped = len(targets) - judged
    print(f"  {name}: {accuracy:.4f} top-1 over {judged:,} clips through the real buffer")
    if skipped:
        print(f"     {skipped} clip(s) produced no window at all (too sparse)")
    print(f"     median latency {np.median(latencies):.2f} ms  p95 {np.percentile(latencies, 95):.2f} ms")
    return {
        "model": name,
        "clips_judged": judged,
        "clips_skipped": int(skipped),
        "top1_accuracy": round(float(accuracy), 4),
        "median_latency_ms": round(float(np.median(latencies)), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["asl", "isl", "words", "all"], default="all")
    args = parser.parse_args()

    from app.ml.predictor import dynamic_predictor, isl_predictor, predictor

    print("Held-out samples through the LIVE inference path")
    print("(the predictor the backend loads, not the training arrays)\n")

    results = []
    if args.model in ("asl", "all"):
        r = check_static("ASL letters", predictor, "", "labels.json")
        if r:
            results.append(r)
    if args.model in ("isl", "all"):
        r = check_static("ISL fingerspelling", isl_predictor, "isl_", "labels_isl.json")
        if r:
            results.append(r)
    if args.model in ("words", "all"):
        r = check_dynamic("ISL words", dynamic_predictor)
        if r:
            results.append(r)

    if not results:
        print("\nNothing could be measured. Train a model first.")
        return 1

    output = MODELS / "inference_path_report.json"
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {output.relative_to(REPO_ROOT)}")

    print(
        "\nCompare each number with evaluate.py's. They should agree closely —\n"
        "a gap means the serving path differs from the training path, which is\n"
        "the silent failure this script exists to catch."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
