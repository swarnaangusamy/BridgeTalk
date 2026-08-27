"""Machine learning: normalisation, model loading, and prediction smoothing.

Written as pure functions wherever possible so the logic can be unit-tested
without a running server or a loaded model.
"""

from app.ml.normalization import (
    NORMALIZATION_VERSION,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
    normalize_hand,
    normalize_hands,
    normalize_primary_hand,
)

__all__ = [
    "NORMALIZATION_VERSION",
    "SINGLE_HAND_FEATURES",
    "TWO_HAND_FEATURES",
    "normalize_hand",
    "normalize_hands",
    "normalize_primary_hand",
]
