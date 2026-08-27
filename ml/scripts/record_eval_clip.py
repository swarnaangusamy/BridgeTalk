#!/usr/bin/env python3
"""Record a short webcam clip to EVALUATE the trained model against.

THIS SCRIPT DOES NOT PRODUCE TRAINING DATA.

Read that again, because the distinction is the whole point. Every model in
BridgeTalk is trained on public datasets only (see ml/README.md). This script
exists so that we can *measure* how the trained model performs on a webcam it
has never seen — the domain gap — with a clip we can replay, rather than a
one-off impression from waving at the camera.

The output goes to `ml/data/eval/`, which is gitignored, is never read by
preprocess.py or by either training script, and carries a manifest that says
so explicitly.

WHY THIS IS WORTH HAVING
------------------------
`test_realtime.py` shows you the model working, live. It is not a measurement:
you cannot repeat it, you cannot compare two models on it, and "it felt about
right" is not a number.

Recording a clip with known labels turns that into something measurable. Sign
each letter you record, tell the script what you signed, and it reports the
model's accuracy on real footage from a real webcam — which is the number that
honestly describes what a user would experience, and it will be lower than the
90.5% test-split figure.

Usage
-----
    # Record 3 seconds each of A, B and L
    python ml/scripts/record_eval_clip.py --labels A B L

    # Score a previously recorded session
    python ml/scripts/record_eval_clip.py --score
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.normalization import NORMALIZATION_VERSION, normalize_hand  # noqa: E402

EVAL_DIR = REPO_ROOT / "ml" / "data" / "eval"
MODELS_DIR = REPO_ROOT / "ml" / "models"
HAND_MODEL = REPO_ROOT / "frontend" / "public" / "models" / "hand_landmarker.task"


def build_landmarker():
    """MediaPipe in VIDEO mode — consecutive frames really are consecutive here."""
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    return vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    )


def record(labels: list[str], seconds_per_label: float, camera_index: int) -> int:
    """Capture landmark frames for each label in turn."""
    import mediapipe as mp_lib

    if not HAND_MODEL.is_file():
        print(f"ERROR: {HAND_MODEL} missing. Run ./scripts/setup.sh", file=sys.stderr)
        return 1

    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        print(f"ERROR: could not open camera {camera_index}.", file=sys.stderr)
        print("  - Close Zoom/Teams/Photo Booth, or try --camera 1", file=sys.stderr)
        print("  - macOS: grant camera access to your terminal in", file=sys.stderr)
        print("    System Settings > Privacy & Security > Camera", file=sys.stderr)
        return 1

    landmarker = build_landmarker()
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    samples: list[dict] = []
    timestamp_ms = 0

    print("\nFor each letter: get into position, then press SPACE to record.")
    print("Press q at any time to stop.\n")

    try:
        for label in labels:
            # --- wait for the user to be ready ------------------------------
            armed = False
            while not armed:
                ok, frame = capture.read()
                if not ok:
                    print("Camera stopped returning frames.", file=sys.stderr)
                    return 1

                frame = cv2.flip(frame, 1)
                cv2.putText(frame, f"Sign: {label}", (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (90, 190, 245), 3, cv2.LINE_AA)
                cv2.putText(frame, "SPACE to record, q to quit", (20, 105),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 210), 1, cv2.LINE_AA)
                cv2.imshow("BridgeTalk — record evaluation clip (NOT training data)", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("Stopped by user.")
                    return 0
                if key == ord(" "):
                    armed = True

            # --- record -----------------------------------------------------
            started = time.time()
            captured = 0
            missed = 0

            while time.time() - started < seconds_per_label:
                ok, frame = capture.read()
                if not ok:
                    break

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)

                timestamp_ms += 33
                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                if result.hand_landmarks:
                    points = np.array(
                        [[p.x, p.y, p.z] for p in result.hand_landmarks[0]], dtype=np.float32
                    )
                    try:
                        samples.append(
                            {"label": label, "features": normalize_hand(points).tolist()}
                        )
                        captured += 1
                    except ValueError:
                        missed += 1
                else:
                    missed += 1

                remaining = seconds_per_label - (time.time() - started)
                cv2.putText(frame, f"REC {label}  {remaining:.1f}s", (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (90, 90, 245), 3, cv2.LINE_AA)
                cv2.putText(frame, f"{captured} frames captured", (20, 105),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 210), 1, cv2.LINE_AA)
                cv2.imshow("BridgeTalk — record evaluation clip (NOT training data)", frame)

                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    return 0

            rate = missed / (captured + missed) * 100 if (captured + missed) else 0
            print(f"  {label}: {captured} frames captured, {missed} with no hand ({rate:.0f}%)")

    finally:
        capture.release()
        cv2.destroyAllWindows()

    if not samples:
        print("\nNo frames captured — nothing written.")
        return 1

    output = EVAL_DIR / "eval_clip.json"
    output.write_text(
        json.dumps(
            {
                # Stated in the file itself, so that anyone who finds this data
                # later cannot mistake it for a training set.
                "purpose": "EVALUATION ONLY — never used for training",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "normalization_version": NORMALIZATION_VERSION,
                "labels": labels,
                "frame_count": len(samples),
                "samples": samples,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nWrote {len(samples)} frames to {output.relative_to(REPO_ROOT)}")
    print("This file is gitignored and is never read by preprocess.py or the")
    print("training scripts. Score it with:  --score")
    return 0


def score() -> int:
    """Run the trained model over a recorded clip and report real accuracy."""
    clip_path = EVAL_DIR / "eval_clip.json"
    if not clip_path.is_file():
        print(f"ERROR: no clip at {clip_path}. Record one first.", file=sys.stderr)
        return 1

    model_path = MODELS_DIR / "static_model.keras"
    labels_path = MODELS_DIR / "labels.json"
    for path in (model_path, labels_path):
        if not path.is_file():
            print(f"ERROR: {path} missing. Train the model first.", file=sys.stderr)
            return 1

    clip = json.loads(clip_path.read_text(encoding="utf-8"))

    # The same guard the backend applies: a model trained under different
    # normalisation would score confidently and meaninglessly.
    if clip.get("normalization_version") != NORMALIZATION_VERSION:
        print(
            f"ERROR: clip was recorded with normalization version "
            f"{clip.get('normalization_version')}, code is version "
            f"{NORMALIZATION_VERSION}. Re-record it.",
            file=sys.stderr,
        )
        return 1

    from tensorflow import keras

    class_names = json.loads(labels_path.read_text(encoding="utf-8"))["classes"]
    model = keras.models.load_model(model_path)

    features = np.array([s["features"] for s in clip["samples"]], dtype=np.float32)
    truth = [s["label"] for s in clip["samples"]]

    probabilities = model.predict(features, verbose=0)
    predictions = [class_names[int(row.argmax())] for row in probabilities]

    correct = sum(1 for t, p in zip(truth, predictions) if t == p)
    total = len(truth)

    print(f"\nClip recorded {clip['recorded_at']}")
    print(f"{total} frames, {len(set(truth))} letters\n")

    print(f"{'letter':>8} {'frames':>7} {'correct':>8} {'accuracy':>9}  most often confused with")
    print("-" * 72)

    for label in sorted(set(truth)):
        indices = [i for i, t in enumerate(truth) if t == label]
        hits = sum(1 for i in indices if predictions[i] == label)

        wrong = [predictions[i] for i in indices if predictions[i] != label]
        confused = max(set(wrong), key=wrong.count) if wrong else "—"

        print(
            f"{label:>8} {len(indices):>7} {hits:>8} "
            f"{hits / len(indices) * 100:>8.1f}%  {confused}"
        )

    print("-" * 72)
    print(f"{'TOTAL':>8} {total:>7} {correct:>8} {correct / total * 100:>8.1f}%")

    print(
        "\nThis number is the honest one: it is the model meeting a webcam, a room\n"
        "and a pair of hands it has never seen. Expect it below the held-out test\n"
        "accuracy — that difference IS the domain gap, and measuring it is more\n"
        "useful than hoping it is small."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--labels", nargs="+", default=["A", "B", "L", "Y", "W"],
                        help="Letters to record, in order (default: A B L Y W)")
    parser.add_argument("--seconds", type=float, default=3.0, help="Seconds per letter")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--score", action="store_true", help="Score an existing clip")
    args = parser.parse_args()

    return score() if args.score else record(args.labels, args.seconds, args.camera)


if __name__ == "__main__":
    sys.exit(main())
