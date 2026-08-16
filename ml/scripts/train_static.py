#!/usr/bin/env python3
"""Train Model A — the static fingerspelling classifier.

WHY THIS MODEL IS THIS SMALL
----------------------------
The input is 63 numbers describing hand shape. MediaPipe has already done the
hard computer-vision work: finding the hand, locating each joint, and rejecting
the background. What is left is a geometry problem — "which letter does this
arrangement of 21 points correspond to?" — and a four-layer perceptron is
genuinely the right tool for it.

A convolutional network over the raw images would have to relearn hand
detection from scratch, would take hours on a CPU instead of minutes, and would
additionally memorise the dataset's lighting and backgrounds. It would score
well on the test split and fall apart in a different room.

ARCHITECTURE (per the build spec, section 8.1)

    Input (63,)
      → Dense 256 ReLU → BatchNorm → Dropout 0.3
      → Dense 128 ReLU → BatchNorm → Dropout 0.3
      → Dense  64 ReLU
      → Dense  n_classes Softmax

BatchNorm keeps activations in a stable range so training does not stall.
Dropout randomly silences 30% of units each step, which stops the network
leaning on any single feature — important here, because consecutive dataset
frames are near-identical and memorisation is the easy path.

Usage:
    python ml/scripts/train_static.py
    python ml/scripts/train_static.py --epochs 30 --batch-size 128
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Silence TensorFlow's C++ INFO/WARNING chatter before it is imported. It has
# nothing useful to say on CPU and drowns out the training output.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.normalization import NORMALIZATION_VERSION, SINGLE_HAND_FEATURES  # noqa: E402

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "ml" / "models"


def load_split(name: str) -> tuple[np.ndarray, np.ndarray]:
    features_path = PROCESSED_DIR / f"X_{name}.npy"
    targets_path = PROCESSED_DIR / f"y_{name}.npy"

    if not features_path.is_file() or not targets_path.is_file():
        raise FileNotFoundError(
            f"Missing {features_path.name} / {targets_path.name}. "
            "Run: python ml/scripts/preprocess.py"
        )

    return np.load(features_path), np.load(targets_path)


def build_model(num_classes: int, learning_rate: float):
    """Assemble the MLP described in the module docstring."""
    from tensorflow import keras
    from tensorflow.keras import layers

    model = keras.Sequential(
        [
            keras.Input(shape=(SINGLE_HAND_FEATURES,), name="landmarks"),
            layers.Dense(256, activation="relu", name="dense_256"),
            layers.BatchNormalization(name="bn_1"),
            layers.Dropout(0.3, name="dropout_1"),
            layers.Dense(128, activation="relu", name="dense_128"),
            layers.BatchNormalization(name="bn_2"),
            layers.Dropout(0.3, name="dropout_2"),
            layers.Dense(64, activation="relu", name="dense_64"),
            layers.Dense(num_classes, activation="softmax", name="predictions"),
        ],
        name="bridgetalk_static_classifier",
    )

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        # "sparse" because the labels are integers (0, 1, 2, …) rather than
        # one-hot vectors. It computes the same loss without materialising a
        # 28-wide one-hot matrix for every sample.
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    return model


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import tensorflow as tf
    from tensorflow import keras

    # Reproducibility: without a fixed seed, two runs of the same code give
    # different accuracies and there is no way to tell whether a change helped.
    keras.utils.set_random_seed(args.seed)

    print(f"TensorFlow {tf.__version__}")
    print(f"Devices: {[device.device_type for device in tf.config.list_physical_devices()]}")

    # --- data ---------------------------------------------------------------
    X_train, y_train = load_split("train")
    X_val, y_val = load_split("val")

    labels_path = MODELS_DIR / "labels.json"
    if not labels_path.is_file():
        print(f"ERROR: {labels_path} missing. Run preprocess.py first.", file=sys.stderr)
        return 1

    labels_data = json.loads(labels_path.read_text(encoding="utf-8"))
    class_names = labels_data["classes"]
    num_classes = len(class_names)

    print(f"\nTrain: {X_train.shape}   Val: {X_val.shape}   Classes: {num_classes}")

    # Guard against a stale preprocessing run: if labels.json and the arrays
    # disagree the model trains happily and predicts the wrong letters.
    observed = int(max(y_train.max(), y_val.max())) + 1
    if observed != num_classes:
        print(
            f"ERROR: labels.json lists {num_classes} classes but the arrays contain "
            f"{observed}. Re-run preprocess.py.",
            file=sys.stderr,
        )
        return 1

    # --- model --------------------------------------------------------------
    model = build_model(num_classes, args.learning_rate)
    model.summary()

    callbacks = [
        # Stop when validation loss stops improving, and put back the best
        # weights rather than whatever the last epoch happened to produce.
        # Without restore_best_weights, early stopping saves a model that is
        # by definition slightly worse than the best one seen.
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=args.patience,
            restore_best_weights=True,
            verbose=1,
        ),
        # When progress plateaus, a smaller step size often finds a better
        # minimum rather than bouncing around it.
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=max(3, args.patience // 3),
            min_lr=1e-6,
            verbose=1,
        ),
    ]

    print(f"\nTraining up to {args.epochs} epochs, batch {args.batch_size}\n")
    started = time.time()

    history = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
        verbose=2,
    )

    elapsed = time.time() - started

    # --- results ------------------------------------------------------------
    val_loss, val_accuracy = model.evaluate(X_val, y_val, verbose=0)
    train_loss, train_accuracy = model.evaluate(X_train, y_train, verbose=0)

    epochs_run = len(history.history["loss"])

    print(f"\n{'=' * 58}")
    print(f"  epochs run       {epochs_run} of {args.epochs}")
    print(f"  training time    {elapsed / 60:.1f} min")
    print(f"  train accuracy   {train_accuracy:.4f}")
    print(f"  val accuracy     {val_accuracy:.4f}")
    print(f"  val loss         {val_loss:.4f}")
    print(f"{'=' * 58}")

    # A large train/val gap means the model has memorised rather than learned.
    gap = train_accuracy - val_accuracy
    if gap > 0.10:
        print(f"\n  NOTE: train exceeds val by {gap:.1%} — this is overfitting.")
        print("  More augmentation or stronger dropout would be the next lever.")

    # --- save ---------------------------------------------------------------
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "static_model.keras"
    model.save(model_path)
    print(f"\nSaved {model_path.relative_to(REPO_ROOT)}")

    metadata = {
        "model": "static_model.keras",
        "model_type": "MLP",
        "task": "ASL static fingerspelling classification",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        # The backend refuses to load a model whose normalisation version does
        # not match the running code. That turns a stale model file into a loud
        # startup error instead of a silent accuracy collapse.
        "normalization_version": NORMALIZATION_VERSION,
        "input_shape": [SINGLE_HAND_FEATURES],
        "output_shape": [num_classes],
        "class_names": class_names,
        "source_dataset": "ASL Alphabet (grassknoted/asl-alphabet)",
        "self_recorded_data": False,
        "architecture": "Dense256-BN-Drop0.3 / Dense128-BN-Drop0.3 / Dense64 / Softmax",
        "hyperparameters": {
            "optimizer": "adam",
            "learning_rate": args.learning_rate,
            "loss": "sparse_categorical_crossentropy",
            "batch_size": args.batch_size,
            "max_epochs": args.epochs,
            "epochs_run": epochs_run,
            "early_stopping_patience": args.patience,
            "seed": args.seed,
        },
        "metrics": {
            "train_accuracy": round(float(train_accuracy), 4),
            "val_accuracy": round(float(val_accuracy), 4),
            "val_loss": round(float(val_loss), 4),
            "train_val_gap": round(float(gap), 4),
        },
        "training_time_seconds": round(elapsed, 1),
        "samples": {"train": int(len(X_train)), "val": int(len(X_val))},
    }

    metadata_path = MODELS_DIR / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved {metadata_path.relative_to(REPO_ROOT)}")

    # Training history, for the accuracy/loss curves in the report.
    history_path = MODELS_DIR / "training_history.json"
    history_path.write_text(
        json.dumps({key: [float(v) for v in values] for key, values in history.history.items()},
                   indent=2),
        encoding="utf-8",
    )
    print(f"Saved {history_path.relative_to(REPO_ROOT)}")

    print("\nNext: python ml/scripts/evaluate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
