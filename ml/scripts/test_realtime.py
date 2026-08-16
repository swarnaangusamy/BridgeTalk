#!/usr/bin/env python3
"""Run the trained model live from a webcam, in a plain OpenCV window.

THIS SCRIPT DOES NOT COLLECT TRAINING DATA.
It writes nothing. It exists to *evaluate* an already-trained model, and it is
one of only two webcam scripts in this project (the other is
record_eval_clip.py, which records a clip for offline evaluation). All training
data comes from public datasets — see ml/README.md.

WHY RUN THIS BEFORE ANY WEB CODE EXISTS
---------------------------------------
When the browser demo eventually misbehaves, the cause is in one of two places:
the model, or the plumbing (WebSocket, throttling, smoothing, React state). If
you have never seen the model work on its own, you cannot tell which — and you
will spend an evening debugging a WebSocket that was fine all along.

This script is the model, a webcam, and nothing else. If letters appear here,
the model works and every later bug is plumbing.

WHAT YOU SHOULD EXPECT
----------------------
Live accuracy will be **noticeably worse than the test-split number**, and that
is the expected result, not a failure. The model was trained on one dataset's
camera, lighting, framing and hands; yours are different. That difference is
called the domain gap, it is well documented in the literature, and measuring
it honestly is more valuable to the report than hiding it.

CONTROLS
    q or Esc   quit
    c          clear the accumulated sentence
    h          toggle the landmark skeleton
    SPACE      pause / resume

Usage:
    python ml/scripts/test_realtime.py
    python ml/scripts/test_realtime.py --camera 1 --threshold 0.7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, deque
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.normalization import NORMALIZATION_VERSION, normalize_hand  # noqa: E402

MODELS_DIR = REPO_ROOT / "ml" / "models"
HAND_MODEL = REPO_ROOT / "frontend" / "public" / "models" / "hand_landmarker.task"

# MediaPipe's 21 landmarks, connected into a hand skeleton. Drawing this is the
# single most convincing element of a live demo: it makes visible that the
# system is tracking joints rather than guessing from pixels.
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),           # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),           # index
    (5, 9), (9, 10), (10, 11), (11, 12),      # middle
    (9, 13), (13, 14), (14, 15), (15, 16),    # ring
    (13, 17), (17, 18), (18, 19), (19, 20),   # little
    (0, 17),                                  # palm edge
]


def draw_landmarks(frame: np.ndarray, landmarks, colour=(80, 220, 120)) -> None:
    """Draw the hand skeleton onto the frame, in place.

    MediaPipe reports landmarks in normalised [0, 1] image coordinates, so they
    are multiplied back up by the frame dimensions to get pixels.
    """
    height, width = frame.shape[:2]
    points = [(int(point.x * width), int(point.y * height)) for point in landmarks]

    for start, end in HAND_CONNECTIONS:
        cv2.line(frame, points[start], points[end], colour, 2, cv2.LINE_AA)

    for index, point in enumerate(points):
        # The wrist is the normalisation origin, so it is drawn larger — it is
        # the one landmark whose position defines every other value.
        radius = 6 if index == 0 else 4
        cv2.circle(frame, point, radius, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, point, radius, (30, 30, 30), 1, cv2.LINE_AA)


def draw_panel(
    frame: np.ndarray,
    label: str,
    confidence: float,
    sentence: str,
    fps: float,
    latency_ms: float,
    stable: bool,
    hand_present: bool,
) -> None:
    """Draw the prediction overlay, in place."""
    height, width = frame.shape[:2]

    # Translucent backdrop, so white text stays readable over any background.
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 108), (20, 20, 28), -1)
    cv2.rectangle(overlay, (0, height - 74), (width, height), (20, 20, 28), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    if not hand_present:
        cv2.putText(frame, "no hand detected", (16, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 160, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "-> neutral state ('nothing') without calling the model",
                    (16, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 190, 220), 1, cv2.LINE_AA)
    else:
        colour = (100, 235, 140) if stable else (90, 190, 245)
        cv2.putText(frame, label, (16, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.7, colour, 3, cv2.LINE_AA)

        # Confidence bar. A number alone is easy to miss while signing; a bar
        # you can see out of the corner of your eye is not.
        bar_x, bar_y, bar_w, bar_h = 150, 30, 320, 26
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (70, 70, 80), 1)
        filled = int(bar_w * min(max(confidence, 0.0), 1.0))
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + filled, bar_y + bar_h), colour, -1)
        cv2.putText(frame, f"{confidence:.0%}", (bar_x + bar_w + 12, bar_y + 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (235, 235, 235), 1, cv2.LINE_AA)

        status = "STABLE" if stable else "settling"
        cv2.putText(frame, status, (150, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)

    cv2.putText(frame, f"{fps:4.1f} fps   {latency_ms:5.1f} ms/frame",
                (width - 250, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 190, 200), 1, cv2.LINE_AA)

    cv2.putText(frame, sentence[-42:] or "(empty)", (16, height - 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "q quit   c clear   h skeleton   SPACE pause",
                (16, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (150, 155, 170), 1, cv2.LINE_AA)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="confidence gate, default 0.80")
    parser.add_argument("--majority-window", type=int, default=10)
    parser.add_argument("--majority-min", type=int, default=7)
    parser.add_argument("--cooldown-ms", type=int, default=1500)
    parser.add_argument("--mirror", action="store_true", default=True,
                        help="mirror the preview (on by default — an un-mirrored "
                             "preview is disorienting to sign into)")
    args = parser.parse_args()

    # --- preflight ----------------------------------------------------------
    model_path = MODELS_DIR / "static_model.keras"
    labels_path = MODELS_DIR / "labels.json"
    metadata_path = MODELS_DIR / "metadata.json"

    for path in (model_path, labels_path, HAND_MODEL):
        if not path.is_file():
            print(f"ERROR: missing {path}", file=sys.stderr)
            print("Run preprocess.py and train_static.py first "
                  "(and ./scripts/setup.sh for the MediaPipe model).", file=sys.stderr)
            return 1

    class_names = json.loads(labels_path.read_text(encoding="utf-8"))["classes"]

    # The same guard the backend applies: a model trained under a different
    # normalisation would produce confident nonsense, so refuse to run it.
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        trained_version = metadata.get("normalization_version")
        if trained_version != NORMALIZATION_VERSION:
            print(
                f"ERROR: model was trained with normalization version {trained_version}, "
                f"but this code is version {NORMALIZATION_VERSION}.\n"
                "Retrain the model, or check out the matching code.",
                file=sys.stderr,
            )
            return 1
        print(f"Model val accuracy (from training): "
              f"{metadata.get('metrics', {}).get('val_accuracy')}")

    from tensorflow import keras
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    import mediapipe as mp_lib

    print("Loading model…")
    model = keras.models.load_model(model_path)

    landmarker = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            # VIDEO mode, unlike the IMAGE mode used for extraction: here the
            # frames really are consecutive, and letting MediaPipe track across
            # them gives steadier landmarks than treating each as unrelated.
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    )

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        print(f"ERROR: could not open camera {args.camera}.", file=sys.stderr)
        print("  - Is another app (Zoom, Teams, Photo Booth) holding it?", file=sys.stderr)
        print("  - On macOS, grant camera access to your terminal in", file=sys.stderr)
        print("    System Settings > Privacy & Security > Camera.", file=sys.stderr)
        print("  - Try --camera 1 if you have more than one.", file=sys.stderr)
        return 1

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("\nRunning. Sign at the camera.  q to quit, c to clear.\n")

    # --- smoothing state ----------------------------------------------------
    # The same algorithm the backend implements in Phase 5, kept here so this
    # script shows what the demo will actually behave like rather than raw
    # flickering argmax.
    recent = deque(maxlen=args.majority_window)
    sentence = ""
    last_emitted: str | None = None
    last_emit_time = 0.0
    no_hand_streak = 0

    frame_times: deque[float] = deque(maxlen=30)
    show_skeleton = True
    paused = False
    timestamp_ms = 0

    label, confidence, stable, hand_present = "-", 0.0, False, False

    try:
        while True:
            if not paused:
                ok, frame = capture.read()
                if not ok:
                    print("Camera stopped returning frames.", file=sys.stderr)
                    break

                if args.mirror:
                    frame = cv2.flip(frame, 1)

                started = time.perf_counter()

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)

                # VIDEO mode requires a monotonically increasing timestamp.
                timestamp_ms += 33
                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                hand_present = bool(result.hand_landmarks)

                if hand_present:
                    no_hand_streak = 0
                    landmarks = result.hand_landmarks[0]

                    if show_skeleton:
                        draw_landmarks(frame, landmarks)

                    features = normalize_hand(
                        np.array([[p.x, p.y, p.z] for p in landmarks], dtype=np.float32)
                    )

                    probabilities = model.predict(features[None, :], verbose=0)[0]
                    index = int(probabilities.argmax())
                    label = class_names[index]
                    confidence = float(probabilities[index])

                    # 1. Confidence gate — ignore anything the model is unsure of.
                    if confidence >= args.threshold:
                        recent.append(label)
                    else:
                        recent.append(None)

                    # 2. Majority vote over the rolling window.
                    counts = Counter(item for item in recent if item is not None)
                    stable = False
                    if counts:
                        winner, votes = counts.most_common(1)[0]
                        if votes >= args.majority_min:
                            stable = True
                            now = time.time()
                            # 3. Debounce — holding a handshape must not spell AAAAA.
                            same_as_last = winner == last_emitted
                            cooled_down = (now - last_emit_time) * 1000 >= args.cooldown_ms

                            if not same_as_last or cooled_down:
                                if winner == "space":
                                    sentence += " "
                                elif winner == "del":
                                    sentence = sentence[:-1]
                                else:
                                    sentence += winner
                                last_emitted = winner
                                last_emit_time = now
                else:
                    # 4. Neutral reset — no hand closes the current word and
                    #    frees the next sign to repeat a letter immediately.
                    no_hand_streak += 1
                    label, confidence, stable = "-", 0.0, False
                    recent.append(None)
                    if no_hand_streak >= 8:
                        last_emitted = None

                elapsed_ms = (time.perf_counter() - started) * 1000
                frame_times.append(elapsed_ms)

            average_ms = sum(frame_times) / len(frame_times) if frame_times else 0.0
            fps = 1000.0 / average_ms if average_ms > 0 else 0.0

            draw_panel(frame, label, confidence, sentence, fps, average_ms, stable, hand_present)
            if paused:
                cv2.putText(frame, "PAUSED", (frame.shape[1] // 2 - 70, frame.shape[0] // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (90, 190, 245), 3, cv2.LINE_AA)

            cv2.imshow("BridgeTalk — Model A live check (no data is recorded)", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                sentence = ""
                last_emitted = None
            if key == ord("h"):
                show_skeleton = not show_skeleton
            if key == ord(" "):
                paused = not paused

    finally:
        capture.release()
        cv2.destroyAllWindows()

    print(f"\nFinal sentence: {sentence!r}")
    print("Nothing was recorded or saved. This script never writes training data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
