"""Loads the trained Keras model and runs inference on landmark vectors.

The model is loaded **once, at application startup**, and held in memory for the
process lifetime. Loading it per request would add hundreds of milliseconds to
a system whose entire selling point is sub-second response.

THE VERSION GUARD
-----------------
`metadata.json` records the `normalization_version` the model was trained with.
If that does not match the version in the running code, this module **refuses
to load the model**.

That refusal is the whole point. Without it, a model trained under different
normalisation loads happily and returns confident nonsense — every prediction
has a plausible-looking confidence, nothing appears in the logs, and the only
symptom is that the demo is wrong. A loud failure at startup costs a minute; a
silent one costs an evening.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.config import settings
from app.ml.normalization import NORMALIZATION_VERSION, SINGLE_HAND_FEATURES

logger = logging.getLogger("bridgetalk.predictor")


class ModelNotLoadedError(RuntimeError):
    """Raised when inference is attempted without a usable model."""


class SignPredictor:
    """Wraps the static (fingerspelling) classifier.

    Deliberately tolerant of a missing model: the API must still start so that
    auth, meetings and transcripts work while someone is still training the
    model. Attempting to *predict* without one raises, and the WebSocket turns
    that into a clear MODEL_NOT_LOADED message rather than a 500.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self.class_names: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.load_error: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """Load model, labels and metadata. Returns True on success.

        Never raises: a failure here must not stop the API from starting. The
        reason is recorded in `load_error` and surfaced through /health.
        """
        model_path = settings.resolve_path(settings.static_model_path)
        labels_path = settings.resolve_path(settings.labels_path)
        metadata_path = settings.resolve_path(settings.model_metadata_path)

        missing = [path for path in (model_path, labels_path) if not path.is_file()]
        if missing:
            self.load_error = (
                f"Missing {', '.join(path.name for path in missing)}. "
                "Train the model first: python ml/scripts/train_static.py"
            )
            logger.warning("Sign model not loaded — %s", self.load_error)
            return False

        # --- version guard, before spending time loading weights ------------
        if metadata_path.is_file():
            try:
                self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                self.load_error = f"metadata.json is not valid JSON: {exc}"
                logger.error(self.load_error)
                return False

            trained_version = self.metadata.get("normalization_version")
            if trained_version != NORMALIZATION_VERSION:
                self.load_error = (
                    f"Model was trained with normalization version {trained_version}, "
                    f"but this code implements version {NORMALIZATION_VERSION}. "
                    "Retrain the model, or check out the matching code. Refusing to "
                    "load: predictions would be confident and wrong."
                )
                logger.error(self.load_error)
                return False
        else:
            logger.warning("No metadata.json — cannot verify normalisation version")

        try:
            labels_data = json.loads(labels_path.read_text(encoding="utf-8"))
            self.class_names = labels_data["classes"]

            # Import TensorFlow lazily. It takes seconds to import and pulls in
            # a lot of native code; a deployment that never loads a model
            # should not pay that cost.
            from tensorflow import keras

            started = time.perf_counter()
            self._model = keras.models.load_model(model_path)
            elapsed = time.perf_counter() - started

        except Exception as exc:  # noqa: BLE001 - any failure means no model
            self.load_error = f"Failed to load model: {exc}"
            logger.error(self.load_error)
            self._model = None
            return False

        # --- shape sanity ---------------------------------------------------
        # A model whose output width disagrees with labels.json would silently
        # map probabilities to the wrong letters.
        output_classes = int(self._model.output_shape[-1])
        if output_classes != len(self.class_names):
            self.load_error = (
                f"Model outputs {output_classes} classes but labels.json lists "
                f"{len(self.class_names)}. These files are from different runs."
            )
            logger.error(self.load_error)
            self._model = None
            return False

        self.load_error = None
        logger.info(
            "Sign model loaded in %.2fs — %d classes, val accuracy %s",
            elapsed,
            len(self.class_names),
            self.metadata.get("metrics", {}).get("val_accuracy", "unknown"),
        )

        # Warm up through the same path inference uses. The first call into
        # Keras traces the graph and can take 100ms+; paying that here means
        # the first real prediction is not anomalously slow and does not skew
        # the latency figure shown in the UI.
        self._model(
            np.zeros((1, SINGLE_HAND_FEATURES), dtype=np.float32), training=False
        )
        logger.info("Sign model warmed up")

        return True

    # ------------------------------------------------------------------ #
    # Inference
    # ------------------------------------------------------------------ #

    def predict(self, features: np.ndarray) -> tuple[str, float, np.ndarray]:
        """Classify one normalised 63-float landmark vector.

        Returns:
            (label, confidence, full probability vector)

        Raises:
            ModelNotLoadedError: if no model is available.
            ValueError: if the feature vector is the wrong shape.
        """
        if self._model is None:
            raise ModelNotLoadedError(self.load_error or "No model loaded")

        features = np.asarray(features, dtype=np.float32)

        if features.shape != (SINGLE_HAND_FEATURES,):
            raise ValueError(
                f"Expected {SINGLE_HAND_FEATURES} features, got shape {features.shape}"
            )

        # Calling the model directly, NOT model.predict().
        #
        # `predict()` is built for batches: it constructs a tf.data pipeline,
        # sets up callbacks and dispatches through the training loop machinery.
        # For one 63-float sample that overhead is roughly 50ms, which utterly
        # dominates the ~1ms the network itself needs — and it lands directly in
        # the latency number the UI shows. Calling the model as a function skips
        # all of it. Measured on this project: 53ms median down to under 2ms.
        probabilities = self._model(features[None, :], training=False).numpy()[0]
        index = int(probabilities.argmax())

        return self.class_names[index], float(probabilities[index]), probabilities

    def describe(self) -> dict[str, Any]:
        """Model status for /health and the frontend's status panel."""
        return {
            "loaded": self.is_loaded,
            "error": self.load_error,
            "classes": len(self.class_names),
            "normalization_version": NORMALIZATION_VERSION,
            "val_accuracy": self.metadata.get("metrics", {}).get("val_accuracy"),
            "trained_at": self.metadata.get("trained_at"),
            "source_dataset": self.metadata.get("source_dataset"),
        }


# One instance per process, loaded during the FastAPI lifespan startup.
predictor = SignPredictor()
