"""Sliding-window buffer that turns a live landmark stream into LSTM inputs.

THE MISMATCH THIS FILE EXISTS TO MANAGE
---------------------------------------
Model B is trained on **segmented** clips. Every training sample is one word
sign, trimmed by WLASL's own `frame_start`/`frame_end` metadata so it begins
roughly when the sign begins and ends when it ends.

Live inference has no such luxury. Landmarks arrive as an unbroken stream, and
nothing in it announces "a sign starts here". This is the single largest reason
Model B's live behaviour is worse than its test accuracy, and it is a property
of the problem rather than a bug in the model:

  * a window can straddle the end of one sign and the start of the next,
    producing a sequence that belongs to no class at all;
  * a window can land mostly on the rest position between signs, where the
    model still has to answer with one of its N glosses;
  * the model was never shown either of those during training, so its
    confidence on them is not calibrated.

Continuous sign language segmentation is an open research problem, not
something to solve in a mini project. What this module does instead is apply
the two cheap heuristics that recover most of the benefit, and say plainly what
they do not fix.

THE TWO HEURISTICS
------------------
1. **A run of hand-free frames is a boundary.** When the hands leave the frame
   for `reset_after_empty` frames, the buffer is cleared. People genuinely do
   drop their hands between signs, so this gives real segmentation for free
   whenever they do.

2. **A window must contain enough hand.** If fewer than `min_detection_rate` of
   the window's frames contain a detected hand, no prediction is attempted.
   This is the same threshold extraction applied when deciding which training
   clips were usable, so the model is only ever asked about windows resembling
   what it was trained on.

Neither heuristic helps a signer who moves continuously from one sign to the
next without pausing. That case is stated in the docs as a known limitation.

WHY THE STRIDE EXISTS
---------------------
Frames arrive at about 10 per second. Classifying on every one would run the
LSTM ten times a second over windows that overlap by 29/30 — almost all of that
work is spent re-deriving the same answer. Predicting every `stride` frames
cuts it by that factor with no practical loss in responsiveness, because the
smoothing layer downstream needs several agreeing predictions anyway.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from app.config import settings
from app.ml.normalization import TWO_HAND_FEATURES


class SequenceBuffer:
    """Per-connection rolling window of normalised two-hand landmark frames.

    One instance per WebSocket, for the same reason the smoother is
    per-connection: two people signing at once must not have their frames
    interleaved into one sequence.
    """

    def __init__(
        self,
        length: Optional[int] = None,
        stride: Optional[int] = None,
        min_detection_rate: Optional[float] = None,
        reset_after_empty: Optional[int] = None,
    ) -> None:
        self.length = length if length is not None else settings.sequence_length
        self.stride = stride if stride is not None else settings.dynamic_stride
        self.min_detection_rate = (
            min_detection_rate
            if min_detection_rate is not None
            else settings.dynamic_min_detection_rate
        )
        self.reset_after_empty = (
            reset_after_empty
            if reset_after_empty is not None
            else settings.dynamic_reset_frames
        )

        if self.length < 2:
            raise ValueError("sequence length must be at least 2")
        if self.stride < 1:
            raise ValueError("stride must be at least 1")

        self._frames: deque[np.ndarray] = deque(maxlen=self.length)
        self._empty_streak = 0
        self._since_prediction = 0

    # ------------------------------------------------------------------ #
    # Feeding
    # ------------------------------------------------------------------ #

    def push(self, features: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Add one frame; return a window shaped (length, 126) when ready.

        Args:
            features: a normalised 126-float vector, or None when no hand was
                detected in this frame.

        Returns:
            The window to classify, or None if this frame did not produce one.
        """
        if features is None:
            # An all-zero frame is exactly what the training pipeline recorded
            # for a hand-free frame, and what the model's Masking layer skips.
            # Storing zeros rather than skipping the frame keeps the window's
            # timing honest — the gap between two signs stays a real gap.
            frame = np.zeros(TWO_HAND_FEATURES, dtype=np.float32)
            self._empty_streak += 1
        else:
            frame = np.asarray(features, dtype=np.float32)
            if frame.shape != (TWO_HAND_FEATURES,):
                raise ValueError(
                    f"Expected {TWO_HAND_FEATURES} features, got shape {frame.shape}"
                )
            self._empty_streak = 0

        # --- heuristic 1: hands gone for long enough is a sign boundary ------
        if self._empty_streak >= self.reset_after_empty:
            self.reset()
            return None

        self._frames.append(frame)
        self._since_prediction += 1

        if len(self._frames) < self.length:
            return None

        if self._since_prediction < self.stride:
            return None

        window = np.stack(self._frames)

        # --- heuristic 2: refuse windows that are mostly empty ---------------
        detected = float(np.mean(np.any(window != 0.0, axis=-1)))
        if detected < self.min_detection_rate:
            # Do not reset the stride counter. The next frame that arrives
            # should be reconsidered immediately rather than waiting another
            # full stride, because the hands may have just re-entered the frame.
            return None

        self._since_prediction = 0
        return window

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Drop the window. Called at a sign boundary and on an explicit clear."""
        self._frames.clear()
        self._empty_streak = 0
        self._since_prediction = 0

    @property
    def filled(self) -> int:
        return len(self._frames)

    @property
    def is_ready(self) -> bool:
        return len(self._frames) >= self.length

    def describe(self) -> dict[str, float | int]:
        """Buffer state for the UI, so 'nothing is happening' is explainable.

        Without this the dynamic mode looks broken while it is simply filling:
        the first prediction cannot arrive until `length` frames have been seen,
        which is three seconds at 10 FPS.
        """
        return {
            "filled": len(self._frames),
            "length": self.length,
            "stride": self.stride,
            "min_detection_rate": self.min_detection_rate,
        }
