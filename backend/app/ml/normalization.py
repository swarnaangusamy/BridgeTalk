"""Landmark normalisation — the single most safety-critical file in the project.

WHY THIS EXISTS
---------------
MediaPipe reports each hand landmark as an (x, y, z) coordinate in image space.
Those raw numbers depend on two things that have nothing to do with *which sign
is being made*:

  * **where** the hand is in the frame — signing in the top-left corner produces
    completely different numbers from signing in the centre;
  * **how far** the hand is from the camera — leaning in doubles every value.

Train on raw coordinates and the model learns "the letter A is a hand in the
middle of the frame, 60 cm away", which collapses the moment anyone sits
differently. Normalisation strips both effects out, leaving only hand *shape*.

THE PROCEDURE (normalization version 1)
---------------------------------------
1. **Translate** — subtract the wrist (landmark 0) from all 21 points, so the
   wrist sits at the origin. Position invariance.
2. **Scale** — divide by the largest Euclidean distance from the wrist to any
   landmark, so the hand always spans the same radius. Distance invariance.
3. **Flatten** to 63 floats in fixed landmark order (x0,y0,z0, x1,y1,z1, …).
4. **Two hands** — concatenate as [left(63), right(63)] using MediaPipe's
   handedness label; a missing hand is zero-filled.

THE RULE THAT MATTERS
---------------------
This procedure must produce byte-identical numbers everywhere it runs:
training, backend inference, and the browser. A mismatch is the classic silent
failure of this kind of project — 97% validation accuracy, garbage live
predictions, and nothing in any log to tell you why.

To guarantee that, this module is the **only** Python implementation. The
training scripts in ml/ import it rather than reimplementing it, so training
and inference cannot drift apart by construction. The browser necessarily has
its own copy in frontend/src/utils/landmarkUtils.js, and
backend/tests/test_normalization_parity.py runs the same inputs through both
and asserts they agree to 1e-6.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

# Bumped whenever the maths below changes in a way that invalidates trained
# models. metadata.json records the version a model was trained with, and the
# backend refuses to load a model whose version does not match. That turns a
# stale model file into a loud startup error instead of a silent accuracy
# collapse that takes a day to diagnose.
NORMALIZATION_VERSION = 1

# MediaPipe's hand model always returns exactly 21 landmarks per hand.
NUM_LANDMARKS = 21
COORDS_PER_LANDMARK = 3
SINGLE_HAND_FEATURES = NUM_LANDMARKS * COORDS_PER_LANDMARK  # 63
TWO_HAND_FEATURES = SINGLE_HAND_FEATURES * 2  # 126

# Below this scale the "hand" is a degenerate blob — every landmark sitting on
# top of the wrist. Dividing by it would produce infinities, so we return zeros
# and let the confidence gate downstream reject the frame.
_MIN_SCALE = 1e-8


def normalize_hand(landmarks: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    """Normalise one hand's 21 landmarks into a 63-float feature vector.

    Args:
        landmarks: 21 points, each (x, y, z). Accepts a nested list or an
            array-like of shape (21, 3).

    Returns:
        float32 array of shape (63,), wrist-centred and scale-normalised.
        All zeros if the input is degenerate.

    Raises:
        ValueError: if the input is not 21 points of 3 coordinates. This is
            deliberately strict — silently padding a malformed frame would let
            corrupt data reach the model.
    """
    points = np.asarray(landmarks, dtype=np.float32)

    if points.shape != (NUM_LANDMARKS, COORDS_PER_LANDMARK):
        raise ValueError(
            f"Expected {NUM_LANDMARKS} landmarks of {COORDS_PER_LANDMARK} coordinates, "
            f"got array of shape {points.shape}"
        )

    # --- 1. Translate: put the wrist at the origin --------------------------
    wrist = points[0]
    centred = points - wrist

    # --- 2. Scale: largest distance from the wrist becomes 1.0 --------------
    # np.linalg.norm along axis 1 gives the distance of each landmark from the
    # (now origin) wrist. The maximum is the hand's "radius".
    distances = np.linalg.norm(centred, axis=1)
    scale = float(distances.max())

    if scale < _MIN_SCALE:
        # Every landmark is on top of the wrist — not a real hand.
        return np.zeros(SINGLE_HAND_FEATURES, dtype=np.float32)

    normalised = centred / scale

    # --- 3. Flatten in fixed order ------------------------------------------
    # ravel() preserves row-major order, giving x0,y0,z0,x1,y1,z1,… The order
    # is fixed by MediaPipe's landmark indexing and must never be re-sorted.
    return normalised.ravel().astype(np.float32)


def normalize_hands(hands: Iterable[dict[str, Any]] | None) -> np.ndarray:
    """Normalise a frame that may contain zero, one or two hands.

    Args:
        hands: an iterable of dicts shaped like the WebSocket contract::

            {"handedness": "Left" | "Right", "landmarks": [[x, y, z], … 21]}

    Returns:
        float32 array of shape (126,), laid out as [left_hand(63), right_hand(63)].
        A hand that is not present is zero-filled.

    Fixing the slot order by handedness rather than by detection order is what
    makes two-handed signs learnable. MediaPipe returns hands in whatever order
    it found them, so without this the same sign would land in different halves
    of the feature vector from frame to frame, and the model would have to
    learn both arrangements separately.
    """
    features = np.zeros(TWO_HAND_FEATURES, dtype=np.float32)

    if not hands:
        return features

    for hand in hands:
        landmarks = hand.get("landmarks")
        if not landmarks:
            continue

        # MediaPipe reports "Left"/"Right"; be forgiving about case and
        # whitespace, since this value crosses the network from the browser.
        handedness = str(hand.get("handedness", "")).strip().lower()
        offset = 0 if handedness.startswith("l") else SINGLE_HAND_FEATURES

        # If two hands arrive with the same handedness — which MediaPipe does
        # occasionally report — the second overwrites the first rather than
        # corrupting the other slot. One duplicated hand is recoverable; a
        # right hand sitting in the left slot is not.
        features[offset : offset + SINGLE_HAND_FEATURES] = normalize_hand(landmarks)

    return features


def normalize_primary_hand(hands: Iterable[dict[str, Any]] | None) -> np.ndarray:
    """Normalise the single most relevant hand, for the static model.

    Model A is trained on ASL fingerspelling, which is one-handed, so it takes
    63 features rather than 126. When two hands are visible we keep the right
    one, falling back to whatever is present. That matches the ASL Alphabet
    dataset, which is overwhelmingly right-handed.

    Returns:
        float32 array of shape (63,), all zeros if no hand is present.
    """
    hand_list = list(hands) if hands else []
    if not hand_list:
        return np.zeros(SINGLE_HAND_FEATURES, dtype=np.float32)

    chosen = next(
        (
            hand
            for hand in hand_list
            if str(hand.get("handedness", "")).strip().lower().startswith("r")
        ),
        hand_list[0],
    )

    landmarks = chosen.get("landmarks")
    if not landmarks:
        return np.zeros(SINGLE_HAND_FEATURES, dtype=np.float32)

    return normalize_hand(landmarks)
