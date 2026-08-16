#!/usr/bin/env python3
"""Evaluate the trained static model on the held-out test split.

Produces the numbers and figures that go in the report:

    docs/images/confusion_matrix.png    where the model gets confused
    docs/images/per_class_accuracy.png  which letters are weak
    docs/images/training_curves.png     accuracy and loss over epochs
    ml/models/evaluation_report.json    machine-readable metrics

HOW TO READ A CONFUSION MATRIX
------------------------------
Rows are the true letter, columns are what the model predicted. A perfect model
is a bright diagonal and nothing else. Every off-diagonal cell is a mistake, and
*where* the mistakes cluster tells you far more than the headline accuracy does.

For ASL fingerspelling, expect confusion among M, N, S and T. All four are a
closed fist with the thumb tucked in a slightly different place. Once the hand
is reduced to 21 points, the difference between them is a couple of millimetres
of thumb position — and the thumb is the landmark most often occluded by the
fingers folded over it. That is a limitation of the representation, not a bug in
the training, and it is the honest answer when someone asks why accuracy is not
higher.

Usage:
    python ml/scripts/evaluate.py
    python ml/scripts/evaluate.py --split val
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import matplotlib  # noqa: E402

# Render to a file rather than trying to open a window. Without this the script
# fails or hangs when run over SSH or from a terminal with no display.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import seaborn as sns  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    classification_report,
    confusion_matrix,
    top_k_accuracy_score,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "ml" / "models"
IMAGES_DIR = REPO_ROOT / "docs" / "images"


def plot_confusion_matrix(matrix: np.ndarray, class_names: list[str], output_path: Path) -> None:
    """Save a row-normalised confusion matrix heatmap.

    Row normalisation (each row sums to 1) matters: raw counts make classes
    with more test samples look worse simply for being larger. Normalised, each
    cell reads as "of all the true A's, what fraction were called B?".
    """
    normalised = matrix.astype(np.float64)
    row_sums = normalised.sum(axis=1, keepdims=True)
    normalised = np.divide(normalised, row_sums, where=row_sums != 0)

    figure, axis = plt.subplots(figsize=(13, 11))
    sns.heatmap(
        normalised,
        annot=False,
        cmap="viridis",
        xticklabels=class_names,
        yticklabels=class_names,
        vmin=0.0,
        vmax=1.0,
        square=True,
        cbar_kws={"label": "fraction of true class"},
        ax=axis,
    )
    axis.set_xlabel("Predicted")
    axis.set_ylabel("True")
    axis.set_title("BridgeTalk Model A — confusion matrix (row-normalised)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def plot_per_class_accuracy(matrix: np.ndarray, class_names: list[str], output_path: Path) -> None:
    """Save a bar chart of per-class recall, worst first."""
    totals = matrix.sum(axis=1)
    correct = np.diag(matrix)
    recall = np.divide(correct, totals, where=totals != 0, out=np.zeros_like(correct, dtype=float))

    order = np.argsort(recall)
    sorted_names = [class_names[i] for i in order]
    sorted_recall = recall[order]

    figure, axis = plt.subplots(figsize=(12, 6))
    # Colour by severity so the weak classes are obvious at a glance.
    colours = ["#d64545" if value < 0.85 else "#e2a03f" if value < 0.95 else "#3f9d5a"
               for value in sorted_recall]
    axis.bar(sorted_names, sorted_recall, color=colours)
    axis.axhline(0.85, linestyle="--", linewidth=1, color="#888")
    axis.set_ylim(0.0, 1.0)
    axis.set_ylabel("Recall")
    axis.set_xlabel("Class")
    axis.set_title("Per-class recall on the held-out test split (worst first)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def plot_training_curves(history: dict, output_path: Path) -> None:
    """Save accuracy and loss curves.

    The gap between the train and validation curves is the thing to look at:
    curves that separate and keep separating mean the model is memorising.
    """
    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 5))

    left.plot(history.get("accuracy", []), label="train")
    left.plot(history.get("val_accuracy", []), label="validation")
    left.set_xlabel("Epoch")
    left.set_ylabel("Accuracy")
    left.set_title("Accuracy")
    left.legend()
    left.grid(alpha=0.3)

    right.plot(history.get("loss", []), label="train")
    right.plot(history.get("val_loss", []), label="validation")
    right.set_xlabel("Epoch")
    right.set_ylabel("Loss")
    right.set_title("Loss")
    right.legend()
    right.grid(alpha=0.3)

    figure.suptitle("BridgeTalk Model A — training history")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def top_confusions(matrix: np.ndarray, class_names: list[str], limit: int = 12) -> list[dict]:
    """The most frequent specific mistakes, largest first."""
    pairs = []
    totals = matrix.sum(axis=1)

    for true_index in range(len(class_names)):
        for predicted_index in range(len(class_names)):
            if true_index == predicted_index:
                continue
            count = int(matrix[true_index, predicted_index])
            if count == 0:
                continue
            pairs.append(
                {
                    "true": class_names[true_index],
                    "predicted": class_names[predicted_index],
                    "count": count,
                    "fraction_of_true_class": round(
                        count / totals[true_index] if totals[true_index] else 0.0, 4
                    ),
                }
            )

    pairs.sort(key=lambda item: item["count"], reverse=True)
    return pairs[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", choices=["test", "val"], default="test")
    parser.add_argument("--model", type=Path, default=MODELS_DIR / "static_model.keras")
    args = parser.parse_args()

    if not args.model.is_file():
        print(f"ERROR: {args.model} not found. Run train_static.py first.", file=sys.stderr)
        return 1

    labels_path = MODELS_DIR / "labels.json"
    if not labels_path.is_file():
        print(f"ERROR: {labels_path} not found. Run preprocess.py first.", file=sys.stderr)
        return 1

    from tensorflow import keras

    class_names = json.loads(labels_path.read_text(encoding="utf-8"))["classes"]

    features = np.load(PROCESSED_DIR / f"X_{args.split}.npy")
    targets = np.load(PROCESSED_DIR / f"y_{args.split}.npy")

    print(f"Model:  {args.model.relative_to(REPO_ROOT)}")
    print(f"Split:  {args.split}  ({len(features):,} samples, {len(class_names)} classes)\n")

    model = keras.models.load_model(args.model)
    probabilities = model.predict(features, verbose=0)
    predictions = probabilities.argmax(axis=1)

    accuracy = accuracy_score(targets, predictions)
    # Top-3 matters for a real-time system: a smoothing layer that considers
    # the top few candidates over several frames can recover from a single
    # frame's top-1 mistake, so this number bounds what smoothing can achieve.
    top3 = top_k_accuracy_score(targets, probabilities, k=3, labels=np.arange(len(class_names)))

    print(f"{'=' * 58}")
    print(f"  top-1 accuracy   {accuracy:.4f}")
    print(f"  top-3 accuracy   {top3:.4f}")
    print(f"{'=' * 58}\n")

    report_text = classification_report(
        targets, predictions, target_names=class_names, digits=4, zero_division=0
    )
    print(report_text)

    report_dict = classification_report(
        targets, predictions, target_names=class_names, output_dict=True, zero_division=0
    )

    matrix = confusion_matrix(targets, predictions, labels=np.arange(len(class_names)))

    # --- figures ------------------------------------------------------------
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    confusion_path = IMAGES_DIR / "confusion_matrix.png"
    plot_confusion_matrix(matrix, class_names, confusion_path)
    print(f"Wrote {confusion_path.relative_to(REPO_ROOT)}")

    per_class_path = IMAGES_DIR / "per_class_accuracy.png"
    plot_per_class_accuracy(matrix, class_names, per_class_path)
    print(f"Wrote {per_class_path.relative_to(REPO_ROOT)}")

    history_path = MODELS_DIR / "training_history.json"
    if history_path.is_file():
        curves_path = IMAGES_DIR / "training_curves.png"
        plot_training_curves(json.loads(history_path.read_text(encoding="utf-8")), curves_path)
        print(f"Wrote {curves_path.relative_to(REPO_ROOT)}")

    # --- confusions ---------------------------------------------------------
    confusions = top_confusions(matrix, class_names)
    print("\nMost frequent confusions:")
    for item in confusions[:10]:
        print(
            f"  {item['true']:>5} → {item['predicted']:<5} "
            f"{item['count']:>4} times  ({item['fraction_of_true_class']:.1%} of true {item['true']})"
        )

    # --- save ---------------------------------------------------------------
    evaluation = {
        "split": args.split,
        "samples": int(len(features)),
        "classes": class_names,
        "top1_accuracy": round(float(accuracy), 4),
        "top3_accuracy": round(float(top3), 4),
        "per_class": {
            name: {
                "precision": round(report_dict[name]["precision"], 4),
                "recall": round(report_dict[name]["recall"], 4),
                "f1": round(report_dict[name]["f1-score"], 4),
                "support": int(report_dict[name]["support"]),
            }
            for name in class_names
            if name in report_dict
        },
        "macro_avg": {
            key: round(value, 4) for key, value in report_dict["macro avg"].items()
        },
        "weighted_avg": {
            key: round(value, 4) for key, value in report_dict["weighted avg"].items()
        },
        "top_confusions": confusions,
        "confusion_matrix": matrix.tolist(),
    }

    evaluation_path = MODELS_DIR / "evaluation_report.json"
    evaluation_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    print(f"\nWrote {evaluation_path.relative_to(REPO_ROOT)}")

    print("\nNext: python ml/scripts/test_realtime.py  (live webcam check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
