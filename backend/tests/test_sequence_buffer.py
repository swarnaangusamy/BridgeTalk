"""Tests for the sliding-window buffer that feeds Model B.

This buffer is where the mismatch between how Model B is trained (segmented
clips) and how it is used (a continuous stream) is actually managed, so the
behaviour worth testing is not "does it collect 30 frames" but the two
heuristics that decide *which* 30 frames are worth classifying at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.normalization import TWO_HAND_FEATURES
from app.ml.sequence import SequenceBuffer


def a_hand(value: float = 0.5) -> np.ndarray:
    """A frame containing a detectable (non-zero) hand."""
    return np.full(TWO_HAND_FEATURES, value, dtype=np.float32)


def buffer(**overrides) -> SequenceBuffer:
    defaults = {
        "length": 10,
        "stride": 1,
        "min_detection_rate": 0.3,
        "reset_after_empty": 5,
    }
    defaults.update(overrides)
    return SequenceBuffer(**defaults)


# --------------------------------------------------------------------------- #
# Filling
# --------------------------------------------------------------------------- #


def test_no_window_until_the_buffer_is_full():
    """A partial window is never classified.

    Feeding the LSTM a half-filled window would ask it about a fragment of a
    gesture, which is not something it was ever trained on.
    """
    sequence = buffer()

    for index in range(9):
        assert sequence.push(a_hand()) is None, f"emitted a window after {index + 1} frames"

    window = sequence.push(a_hand())
    assert window is not None
    assert window.shape == (10, TWO_HAND_FEATURES)


def test_window_slides_and_keeps_the_most_recent_frames():
    sequence = buffer()

    for index in range(10):
        sequence.push(a_hand(index / 100))

    window = sequence.push(a_hand(0.99))
    assert window is not None
    # Oldest frame dropped, newest frame at the end.
    assert window[-1][0] == pytest.approx(0.99)
    assert window[0][0] == pytest.approx(0.01)


def test_stride_skips_predictions_without_dropping_frames():
    """Stride controls how often we classify, not what the window contains."""
    sequence = buffer(stride=3)

    for _ in range(10):
        sequence.push(a_hand())

    # Window is full; the 10th push satisfied the stride, so the next two
    # frames should be buffered silently and the third should classify.
    emitted = [sequence.push(a_hand()) is not None for _ in range(6)]
    assert emitted == [False, False, True, False, False, True]


# --------------------------------------------------------------------------- #
# Heuristic 1 — a run of empty frames is a sign boundary
# --------------------------------------------------------------------------- #


def test_sustained_absence_of_hands_clears_the_buffer():
    """Dropping your hands ends the sign.

    Without this, the window would straddle the gap and contain the end of one
    sign followed by the start of the next — a sequence belonging to no class.
    """
    sequence = buffer(reset_after_empty=5)

    for _ in range(9):
        sequence.push(a_hand())
    assert sequence.filled == 9

    for _ in range(5):
        sequence.push(None)

    assert sequence.filled == 0, "buffer should have been cleared at the boundary"


def test_brief_gaps_do_not_clear_the_buffer():
    """A single dropped detection is noise, not a sign boundary.

    MediaPipe loses the hand for a frame regularly — mid-movement, or when it
    passes in front of the face. Treating that as the end of a sign would make
    the buffer almost never fill.
    """
    sequence = buffer(reset_after_empty=5)

    for _ in range(5):
        sequence.push(a_hand())
    for _ in range(2):
        sequence.push(None)
    for _ in range(3):
        sequence.push(a_hand())

    assert sequence.filled == 10


def test_empty_frames_are_stored_as_zeros_not_skipped():
    """Gaps stay in the timeline, and are what the model's Masking layer skips."""
    sequence = buffer(reset_after_empty=99, min_detection_rate=0.0)

    for _ in range(5):
        sequence.push(a_hand())
    for _ in range(3):
        sequence.push(None)
    for _ in range(2):
        window = sequence.push(a_hand())

    assert window is not None
    empty_rows = np.all(window == 0.0, axis=-1)
    assert empty_rows.sum() == 3, "the gap should be preserved as three masked frames"


# --------------------------------------------------------------------------- #
# Heuristic 2 — mostly-empty windows are not classified
# --------------------------------------------------------------------------- #


def test_window_below_the_detection_threshold_is_not_classified():
    """A window that is mostly empty gets no prediction.

    The model has to answer with one of its N glosses whatever it is shown, so
    asking it about a window containing two frames of hand and eight of nothing
    produces a confident answer with no basis. Refusing to ask is the fix.
    """
    sequence = buffer(reset_after_empty=99, min_detection_rate=0.5)

    # 2 frames with hands, 8 without = 20% detection, below the 50% threshold.
    for _ in range(2):
        sequence.push(a_hand())
    result = None
    for _ in range(8):
        result = sequence.push(None)

    assert sequence.filled == 10, "the window filled"
    assert result is None, "but it should not have been classified"


def test_window_recovers_immediately_once_hands_return():
    """After a sparse window is refused, the next good frame is reconsidered.

    The stride counter is deliberately not reset when a window is rejected for
    sparsity. If it were, a returning hand would have to wait out another full
    stride before anything happened.
    """
    sequence = buffer(stride=4, reset_after_empty=99, min_detection_rate=0.5)

    for _ in range(2):
        sequence.push(a_hand())
    for _ in range(8):
        sequence.push(None)

    # Six good frames brings detection to 8/10 = 80%, over the threshold. The
    # very next qualifying frame should classify rather than waiting for the
    # stride to come round again.
    outcomes = [sequence.push(a_hand()) for _ in range(6)]
    assert any(window is not None for window in outcomes)


# --------------------------------------------------------------------------- #
# Validation and state
# --------------------------------------------------------------------------- #


def test_wrong_feature_width_is_rejected():
    """126 features, not 63. Sending Model A's vector here must not silently pad."""
    sequence = buffer()

    with pytest.raises(ValueError, match="126"):
        sequence.push(np.zeros(63, dtype=np.float32))


def test_reset_clears_everything():
    sequence = buffer()

    for _ in range(7):
        sequence.push(a_hand())

    sequence.reset()

    assert sequence.filled == 0
    assert not sequence.is_ready
    # And a full window is required again from scratch.
    for _ in range(9):
        assert sequence.push(a_hand()) is None
    assert sequence.push(a_hand()) is not None


def test_invalid_configuration_fails_at_construction():
    """A stride of zero would divide the world by nothing; catch it early."""
    with pytest.raises(ValueError):
        SequenceBuffer(length=10, stride=0)

    with pytest.raises(ValueError):
        SequenceBuffer(length=1, stride=1)
