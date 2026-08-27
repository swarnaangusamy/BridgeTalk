"""Loads the trained Keras models and runs inference on landmark data.

Models are loaded **once, at application startup**, and held in memory for the
process lifetime. Loading per request would add hundreds of milliseconds to a
system whose entire selling point is sub-second response.

THREE MODELS, ONE CLASS
-----------------------
BridgeTalk ships three classifiers with genuinely different shapes:

  * **Model A (static)** — 63 floats of one hand → an ASL fingerspelled letter.
  * **Model C (isl)** — 126 floats of two hands → an ISL fingerspelled letter.
  * **Model B (dynamic)** — a (30, 126) sequence of two-handed frames → a word.

The ASL/ISL split is not a localisation setting. ASL fingerspells with one
hand and ISL with two, so the feature vectors are different widths and one
model's weights are not merely less accurate on the other's data — they are
the wrong shape entirely.

They differ in input shape, in which files they read, and in how good they are.
They do **not** differ in how they must be loaded, version-guarded or failed
safely, so that logic lives in one class configured three times rather than
being copied. A second copy would be the obvious place for the version guard to
quietly go missing from one of them.

THE VERSION GUARD
-----------------
Each model's metadata records the `normalization_version` it was trained with.
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
from app.ml.normalization import (
    NORMALIZATION_VERSION,
    SEQUENCE_FEATURES,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
)

logger = logging.getLogger("bridgetalk.predictor")


class ModelNotLoadedError(RuntimeError):
    """Raised when inference is attempted without a usable model."""


class SignPredictor:
    """Wraps one trained classifier.

    Deliberately tolerant of a missing model: the API must still start so that
    auth, meetings and transcripts work while someone is still training. This
    matters more for Model B than Model A — the dynamic model is a stretch goal
    and a deployment without one is a normal, supported state, not an error.

    Attempting to *predict* without a model raises, and the WebSocket turns that
    into a clear MODEL_NOT_LOADED message rather than a 500.
    """

    def __init__(
        self,
        *,
        mode: str,
        model_path: str,
        labels_path: str,
        metadata_path: str,
        input_shape: tuple[int, ...],
        train_command: str,
    ) -> None:
        self.mode = mode
        self._model_path = model_path
        self._labels_path = labels_path
        self._metadata_path = metadata_path
        self.input_shape = input_shape
        self._train_command = train_command

        self._model: Any = None
        self._compiled: Any = None
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
        model_path: Path = settings.resolve_path(self._model_path)
        labels_path: Path = settings.resolve_path(self._labels_path)
        metadata_path: Path = settings.resolve_path(self._metadata_path)

        missing = [path for path in (model_path, labels_path) if not path.is_file()]
        if missing:
            self.load_error = (
                f"Missing {', '.join(path.name for path in missing)}. "
                f"Train the model first: {self._train_command}"
            )
            logger.warning("%s model not loaded — %s", self.mode, self.load_error)
            return False

        # --- version guard, before spending time loading weights ------------
        if metadata_path.is_file():
            try:
                self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                self.load_error = f"{metadata_path.name} is not valid JSON: {exc}"
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
            logger.warning(
                "No %s — cannot verify normalisation version for the %s model",
                metadata_path.name,
                self.mode,
            )

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

            # Compile one traced graph for inference, with a fixed input
            # signature so it is traced exactly once.
            #
            # This is not a micro-optimisation. Keras runs an LSTM wrapped in a
            # Masking layer through its generic per-timestep path, and in eager
            # mode every one of the 30 timesteps costs a separate op dispatch.
            # Measured on this project's word model: 1373 ms eager, 218 ms via
            # model.predict(), and 18 ms compiled. A full second of latency
            # would have made real-time captioning impossible, and nothing in
            # the output would have hinted at the cause — the predictions are
            # perfectly correct, just far too late to use.
            import tensorflow as tf

            self._compiled = tf.function(
                lambda batch: self._model(batch, training=False),
                input_signature=[
                    tf.TensorSpec([1, *self.input_shape], tf.float32)
                ],
            )

        except Exception as exc:  # noqa: BLE001 - any failure means no model
            self.load_error = f"Failed to load model: {exc}"
            logger.error(self.load_error)
            self._model = None
            self._compiled = None
            return False

        # --- shape sanity ---------------------------------------------------
        # A model whose output width disagrees with its labels file would
        # silently map probabilities to the wrong classes.
        output_classes = int(self._model.output_shape[-1])
        if output_classes != len(self.class_names):
            self.load_error = (
                f"Model outputs {output_classes} classes but {labels_path.name} lists "
                f"{len(self.class_names)}. These files are from different runs."
            )
            logger.error(self.load_error)
            self._model = None
            return False

        # Input shape is checked too, not just output width. Loading the static
        # model into the dynamic slot would otherwise fail much later, on the
        # first frame, as a confusing shape error inside TensorFlow.
        expected_input = tuple(self._model.input_shape[1:])
        if expected_input != self.input_shape:
            self.load_error = (
                f"Model expects input {expected_input} but the {self.mode} pipeline "
                f"produces {self.input_shape}. This looks like the wrong model file."
            )
            logger.error(self.load_error)
            self._model = None
            return False

        self.load_error = None
        logger.info(
            "%s model loaded in %.2fs — %d classes, val accuracy %s",
            self.mode.capitalize(),
            elapsed,
            len(self.class_names),
            self.metadata.get("metrics", {}).get("val_accuracy", "unknown"),
        )

        # Warm up through the same path inference uses. The first call into
        # Keras traces the graph and can take 100ms+; paying that here means
        # the first real prediction is not anomalously slow and does not skew
        # the latency figure shown in the UI.
        self._compiled(np.zeros((1, *self.input_shape), dtype=np.float32))
        logger.info("%s model warmed up", self.mode.capitalize())

        return True

    # ------------------------------------------------------------------ #
    # Inference
    # ------------------------------------------------------------------ #

    def predict(self, features: np.ndarray) -> tuple[str, float, np.ndarray]:
        """Classify one sample.

        Args:
            features: shape (63,) for the static model, (30, 126) for the
                dynamic one — a single sample, without a batch dimension.

        Returns:
            (label, confidence, full probability vector)

        Raises:
            ModelNotLoadedError: if no model is available.
            ValueError: if the input is the wrong shape.
        """
        if self._model is None:
            raise ModelNotLoadedError(self.load_error or "No model loaded")

        features = np.asarray(features, dtype=np.float32)

        if features.shape != self.input_shape:
            raise ValueError(
                f"Expected input of shape {self.input_shape}, got {features.shape}"
            )

        # Through the compiled graph built in load(), NOT model.predict() and
        # NOT an eager call.
        #
        # `predict()` is built for batches: it constructs a tf.data pipeline,
        # sets up callbacks and dispatches through the training loop machinery,
        # which is pure overhead for one sample. An eager call avoids that and
        # is fine for the MLPs — but is catastrophic for the recurrent word
        # model, where masking forces a per-timestep path. The compiled graph is
        # the only option that is fast for both. Measured here:
        #
        #     word model (BiLSTM)   eager 1373 ms | predict 218 ms | compiled 18 ms
        #     letter model (MLP)    eager    6 ms | predict  53 ms | compiled  <2 ms
        probabilities = self._compiled(features[None, ...]).numpy()[0]
        index = int(probabilities.argmax())

        return self.class_names[index], float(probabilities[index]), probabilities

    def describe(self) -> dict[str, Any]:
        """Model status for /health and the frontend's status panel."""
        return {
            "mode": self.mode,
            "loaded": self.is_loaded,
            "error": self.load_error,
            "classes": len(self.class_names),
            "class_names": self.class_names,
            "normalization_version": NORMALIZATION_VERSION,
            "val_accuracy": self.metadata.get("metrics", {}).get("val_accuracy"),
            "trained_at": self.metadata.get("trained_at"),
            "source_dataset": self.metadata.get("source_dataset"),
            # Which sign language this model was trained on. The UI labels the
            # mode toggle from this rather than a hardcoded string, so a toggle
            # cannot claim "ASL" while an ISL model is loaded.
            "language": self.metadata.get("language"),
            "signer_disjoint": self.metadata.get("signer_disjoint"),
        }


# One instance of each per process, loaded during the FastAPI lifespan startup.
predictor = SignPredictor(
    mode="static",
    model_path=settings.static_model_path,
    labels_path=settings.labels_path,
    metadata_path=settings.model_metadata_path,
    input_shape=(SINGLE_HAND_FEATURES,),
    train_command="python ml/scripts/train_static.py",
)

# Indian Sign Language alphabet. Same MLP architecture as Model A and the same
# "one frame is the whole answer" premise — but 126 features, because ISL
# fingerspells with both hands where ASL uses one. That difference is why the
# ASL model cannot simply be pointed at ISL data.
isl_predictor = SignPredictor(
    mode="isl",
    model_path=settings.isl_model_path,
    labels_path=settings.isl_labels_path,
    metadata_path=settings.isl_metadata_path,
    input_shape=(TWO_HAND_FEATURES,),
    train_command="python ml/scripts/train_static.py --dataset isl",
)

dynamic_predictor = SignPredictor(
    mode="dynamic",
    model_path=settings.dynamic_model_path,
    labels_path=settings.dynamic_labels_path,
    metadata_path=settings.dynamic_metadata_path,
    input_shape=(settings.sequence_length, SEQUENCE_FEATURES),
    train_command="python ml/scripts/train_dynamic.py",
)
