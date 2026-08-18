#!/usr/bin/env python3
"""Train Model B — the dynamic word-sign classifier.

WHY THIS MODEL IS RECURRENT AND MODEL A IS NOT
----------------------------------------------
Model A classifies a hand *shape*. The letter A is fully determined by a single
frame, so a multilayer perceptron over 63 numbers is genuinely the right tool,
and adding recurrence would cost training time for no benefit.

A word sign is not a shape, it is a *trajectory*. "Again", "help" and "want"
each involve hands moving through space over roughly a second, and any single
frame of one is close to meaningless — several of them pass through nearly
identical poses. The model therefore has to see the whole sequence and learn
what changes across it, which is what an LSTM does.

ARCHITECTURE (per the build spec, section 8.2)

    Input (30, 126)
      → Masking(0.0)
      → LSTM 128, return_sequences=True → Dropout 0.3
      → LSTM  64                        → Dropout 0.3
      → Dense 64 ReLU
      → Dense n_classes Softmax

**The Masking layer is load-bearing.** An all-zero timestep means MediaPipe
found no hands in that frame, which happens constantly at the start and end of a
clip. Without masking, the LSTM would treat "hands at the coordinate origin" as
a real observation and spend capacity modelling the silence around each sign.

SET YOUR EXPECTATIONS BEFORE READING THE OUTPUT
-----------------------------------------------
This model will score far below Model A's 90.5%, and that is not a failure of
the code. Three reasons, all structural:

  * **Two orders of magnitude less data.** Model A trains on tens of thousands
    of samples; WLASL gives roughly 20 clips per gloss.
  * **A much harder label space.** Fingerspelling has one canonical form per
    letter. Word signs vary between signers, regions and dialects.
  * **A signer-disjoint test split** (see preprocess_dynamic.py) — the test set
    contains people the model has never seen. Model A's split could not make
    that guarantee, so its number is measured under easier conditions.

Published WLASL baselines sit around 55-80% on a 20-gloss subset with far
larger models than this one. Reporting a number in that range honestly is worth
more than reporting an inflated one from a leaky split.

Usage:
    python ml/scripts/train_dynamic.py
    python ml/scripts/train_dynamic.py --epochs 150 --batch-size 16
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

import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.normalization import NORMALIZATION_VERSION, TWO_HAND_FEATURES  # noqa: E402

PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "ml" / "models"


def load_split(name: str) -> tuple[np.ndarray, np.ndarray]:
    features_path = PROCESSED_DIR / f"X_dyn_{name}.npy"
    targets_path = PROCESSED_DIR / f"y_dyn_{name}.npy"

    if not features_path.is_file() or not targets_path.is_file():
        raise FileNotFoundError(
            f"Missing {features_path.name} / {targets_path.name}. "
            "Run: python ml/scripts/preprocess_dynamic.py"
        )

    return np.load(features_path), np.load(targets_path)


def build_model(sequence_length: int, num_classes: int, learning_rate: float):
    """Assemble the LSTM described in the module docstring."""
    from tensorflow import keras
    from tensorflow.keras import layers

    model = keras.Sequential(
        [
            keras.Input(shape=(sequence_length, TWO_HAND_FEATURES), name="sequence"),
            # Skip timesteps that are entirely zero — frames where no hand was
            # detected. See the docstring: this is not an optimisation, it
            # changes what the network learns.
            layers.Masking(mask_value=0.0, name="mask_empty_frames"),
            layers.LSTM(128, return_sequences=True, name="lstm_128"),
            layers.Dropout(0.3, name="dropout_1"),
            layers.LSTM(64, name="lstm_64"),
            layers.Dropout(0.3, name="dropout_2"),
            layers.Dense(64, activation="relu", name="dense_64"),
            layers.Dense(num_classes, activation="softmax", name="predictions"),
        ],
        name="bridgetalk_dynamic_classifier",
    )

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    return model


def compute_class_weights(targets: np.ndarray, num_classes: int) -> dict[int, float]:
    """Weight rare glosses up, so the model cannot coast on the common ones.

    WLASL gloss counts are uneven and cannot be balanced by subsampling the way
    Model A's classes were — throwing away clips from a gloss that only has
    fifteen of them would leave nothing to learn from. Reweighting the loss
    achieves the same correction without discarding data.
    """
    counts = np.bincount(targets, minlength=num_classes).astype(np.float64)
    total = counts.sum()

    weights: dict[int, float] = {}
    for index in range(num_classes):
        # A class absent from training gets weight 1.0 rather than infinity.
        weights[index] = float(total / (num_classes * counts[index])) if counts[index] else 1.0

    return weights


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-class-weights", action="store_true")
    args = parser.parse_args()

    import tensorflow as tf
    from tensorflow import keras

    keras.utils.set_random_seed(args.seed)

    print(f"TensorFlow {tf.__version__}")
    print(f"Devices: {[d.device_type for d in tf.config.list_physical_devices()]}")

    # --- data ---------------------------------------------------------------
    X_train, y_train = load_split("train")
    X_val, y_val = load_split("val")

    labels_path = MODELS_DIR / "labels_dynamic.json"
    if not labels_path.is_file():
        print(f"ERROR: {labels_path} missing. Run preprocess_dynamic.py first.",
              file=sys.stderr)
        return 1

    class_names = json.loads(labels_path.read_text(encoding="utf-8"))["classes"]
    num_classes = len(class_names)
    sequence_length = int(X_train.shape[1])

    print(f"\nTrain: {X_train.shape}   Val: {X_val.shape}   Classes: {num_classes}")

    if X_train.shape[-1] != TWO_HAND_FEATURES:
        print(
            f"ERROR: sequences have {X_train.shape[-1]} features per frame, "
            f"expected {TWO_HAND_FEATURES}. Re-run extraction.",
            file=sys.stderr,
        )
        return 1

    observed = int(max(y_train.max(), y_val.max())) + 1 if len(y_val) else int(y_train.max()) + 1
    if observed > num_classes:
        print(
            f"ERROR: labels_dynamic.json lists {num_classes} classes but the arrays "
            f"contain {observed}. Re-run preprocess_dynamic.py.",
            file=sys.stderr,
        )
        return 1

    # How much of the data is actually masked — worth printing, because if this
    # is very high the clips are mostly empty and no architecture will save it.
    masked_fraction = float(np.mean(np.all(X_train == 0.0, axis=-1)))
    print(f"Masked (no-hand) timesteps in training data: {masked_fraction:.1%}")
    if masked_fraction > 0.5:
        print("  NOTE: over half of all timesteps contain no detected hand.")
        print("  Hand detection, not the classifier, is the limiting factor here.")

    # --- model --------------------------------------------------------------
    model = build_model(sequence_length, num_classes, args.learning_rate)
    model.summary()

    class_weights = (
        None if args.no_class_weights else compute_class_weights(y_train, num_classes)
    )
    if class_weights:
        spread = max(class_weights.values()) / max(1e-9, min(class_weights.values()))
        print(f"\nClass weights applied (heaviest/lightest = {spread:.1f}x)")

    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=args.patience,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=max(4, args.patience // 3),
            min_lr=1e-6,
            verbose=1,
        ),
    ]

    print(f"\nTraining up to {args.epochs} epochs, batch {args.batch_size}\n")
    started = time.time()

    history = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val) if len(X_val) else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks if len(X_val) else [],
        class_weight=class_weights,
        verbose=2,
    )

    elapsed = time.time() - started

    # --- results ------------------------------------------------------------
    train_loss, train_accuracy = model.evaluate(X_train, y_train, verbose=0)
    if len(X_val):
        val_loss, val_accuracy = model.evaluate(X_val, y_val, verbose=0)
    else:
        val_loss, val_accuracy = float("nan"), float("nan")

    epochs_run = len(history.history["loss"])

    print(f"\n{'=' * 58}")
    print(f"  epochs run       {epochs_run} of {args.epochs}")
    print(f"  training time    {elapsed / 60:.1f} min")
    print(f"  train accuracy   {train_accuracy:.4f}")
    print(f"  val accuracy     {val_accuracy:.4f}")
    print(f"  val loss         {val_loss:.4f}")
    print(f"{'=' * 58}")

    gap = train_accuracy - val_accuracy
    if gap > 0.15:
        print(f"\n  NOTE: train exceeds val by {gap:.1%}.")
        print("  With ~20 clips per gloss this is expected rather than surprising —")
        print("  the honest fix is more data, not more regularisation.")

    # --- save ---------------------------------------------------------------
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "dynamic_model.keras"
    model.save(model_path)
    print(f"\nSaved {model_path.relative_to(REPO_ROOT)}")

    manifest_path = MODELS_DIR / "dynamic_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )

    metadata = {
        "model": "dynamic_model.keras",
        "model_type": "LSTM",
        "task": "WLASL word-level sign classification",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "normalization_version": NORMALIZATION_VERSION,
        "input_shape": [sequence_length, TWO_HAND_FEATURES],
        "output_shape": [num_classes],
        "class_names": class_names,
        "source_dataset": "WLASL processed (risangbaskoro/wlasl-processed)",
        "self_recorded_data": False,
        "split_strategy": manifest.get("split_strategy"),
        "signer_disjoint": manifest.get("signer_disjoint"),
        "architecture": "Masking / LSTM128-seq / Drop0.3 / LSTM64 / Drop0.3 / Dense64 / Softmax",
        "hyperparameters": {
            "optimizer": "adam",
            "learning_rate": args.learning_rate,
            "loss": "sparse_categorical_crossentropy",
            "batch_size": args.batch_size,
            "max_epochs": args.epochs,
            "epochs_run": epochs_run,
            "early_stopping_patience": args.patience,
            "class_weights": not args.no_class_weights,
            "seed": args.seed,
        },
        "metrics": {
            "train_accuracy": round(float(train_accuracy), 4),
            "val_accuracy": round(float(val_accuracy), 4),
            "val_loss": round(float(val_loss), 4),
            "train_val_gap": round(float(gap), 4),
        },
        "masked_timestep_fraction": round(masked_fraction, 4),
        "training_time_seconds": round(elapsed, 1),
        "samples": {"train": int(len(X_train)), "val": int(len(X_val))},
    }

    metadata_path = MODELS_DIR / "dynamic_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved {metadata_path.relative_to(REPO_ROOT)}")

    history_path = MODELS_DIR / "dynamic_training_history.json"
    history_path.write_text(
        json.dumps(
            {key: [float(v) for v in values] for key, values in history.history.items()},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {history_path.relative_to(REPO_ROOT)}")

    print(
        "\nNext: python ml/scripts/evaluate.py --model ml/models/dynamic_model.keras \\"
        "\n        --labels ml/models/labels_dynamic.json --prefix dyn_ "
        "--report dynamic_evaluation_report.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
