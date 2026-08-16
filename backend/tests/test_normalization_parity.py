"""Cross-language parity test for landmark normalisation.

THE BUG THIS EXISTS TO PREVENT
------------------------------
The same normalisation maths runs in two languages: Python (training and
backend inference) and JavaScript (the browser). If they ever disagree, the
model is fed subtly different numbers at inference time than it saw during
training. The result is a 97% validation accuracy and live predictions that are
noise — with nothing in any log to explain it. Every hour spent debugging that
is spent looking in the wrong place, because the model *is* fine.

This test runs identical raw landmark arrays through
`backend/app/ml/normalization.py` and
`frontend/src/utils/landmarkUtils.js` and asserts the outputs match to 1e-6.

It needs Node.js, which the project already requires for the frontend. If Node
is genuinely unavailable the test skips rather than fails, and the pure-Python
tests below still run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.ml.normalization import (
    NORMALIZATION_VERSION,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
    normalize_hand,
    normalize_hands,
    normalize_primary_hand,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_MODULE = REPO_ROOT / "frontend" / "src" / "utils" / "landmarkUtils.js"

TOLERANCE = 1e-6

# float32 has ~7 decimal digits of precision, while JavaScript numbers are
# float64. Feeding both sides values with more precision than float32 can hold
# would make them disagree for reasons that have nothing to do with the maths,
# so the fixtures are rounded to 6 decimals — which is also what the extraction
# script writes to CSV.
def _make_hand(seed: int) -> list[list[float]]:
    """Deterministic pseudo-random but plausible hand landmarks."""
    rng = np.random.default_rng(seed)
    # MediaPipe normalises x and y to [0, 1] image space; z is roughly centred
    # on zero and much smaller in magnitude.
    xy = rng.uniform(0.15, 0.85, size=(21, 2))
    z = rng.uniform(-0.12, 0.12, size=(21, 1))
    return np.round(np.hstack([xy, z]), 6).tolist()


HAND_A = _make_hand(11)
HAND_B = _make_hand(29)

# A hand where every landmark sits on the wrist — the degenerate case both
# implementations must handle by returning zeros rather than dividing by zero.
DEGENERATE_HAND = [[0.5, 0.5, 0.0] for _ in range(21)]


# ---------------------------------------------------------------------------
# Python-side properties (run with or without Node)
# ---------------------------------------------------------------------------


def test_output_shape_is_63():
    assert normalize_hand(HAND_A).shape == (SINGLE_HAND_FEATURES,)


def test_wrist_lands_at_the_origin():
    """Step 1 of the procedure: translation must zero out the wrist."""
    features = normalize_hand(HAND_A)
    assert features[0] == pytest.approx(0.0, abs=1e-7)
    assert features[1] == pytest.approx(0.0, abs=1e-7)
    assert features[2] == pytest.approx(0.0, abs=1e-7)


def test_furthest_landmark_is_at_distance_one():
    """Step 2: scaling must put the furthest point exactly one unit out."""
    features = normalize_hand(HAND_A).reshape(21, 3)
    distances = np.linalg.norm(features, axis=1)
    assert distances.max() == pytest.approx(1.0, abs=1e-6)


def test_translation_invariance():
    """The whole point: moving the hand across the frame must change nothing."""
    shifted = [[x + 0.2, y - 0.15, z] for x, y, z in HAND_A]
    np.testing.assert_allclose(normalize_hand(HAND_A), normalize_hand(shifted), atol=1e-6)


def test_scale_invariance():
    """Leaning towards the camera must change nothing either."""
    wrist = HAND_A[0]
    # Scale about the wrist, which is what moving closer to the camera
    # approximates once the hand is re-centred.
    scaled = [
        [wrist[0] + (x - wrist[0]) * 2.5,
         wrist[1] + (y - wrist[1]) * 2.5,
         wrist[2] + (z - wrist[2]) * 2.5]
        for x, y, z in HAND_A
    ]
    np.testing.assert_allclose(normalize_hand(HAND_A), normalize_hand(scaled), atol=1e-6)


def test_degenerate_hand_returns_zeros_not_nan():
    """A collapsed detection must not produce NaN or Infinity."""
    features = normalize_hand(DEGENERATE_HAND)
    assert np.all(features == 0.0)
    assert not np.isnan(features).any()


def test_wrong_landmark_count_raises():
    """Silently padding a malformed frame would let corrupt data reach the model."""
    with pytest.raises(ValueError):
        normalize_hand(HAND_A[:20])


def test_hands_are_slotted_by_handedness_not_arrival_order():
    """The same two hands in either order must produce the same vector.

    MediaPipe returns hands in whatever order it detected them. Without
    handedness-based slotting, the same two-handed sign would land in different
    halves of the feature vector from frame to frame, and the model would have
    to learn both arrangements separately.
    """
    forward = normalize_hands(
        [
            {"handedness": "Left", "landmarks": HAND_A},
            {"handedness": "Right", "landmarks": HAND_B},
        ]
    )
    reversed_order = normalize_hands(
        [
            {"handedness": "Right", "landmarks": HAND_B},
            {"handedness": "Left", "landmarks": HAND_A},
        ]
    )
    np.testing.assert_allclose(forward, reversed_order, atol=1e-9)

    # And the halves really do hold what they claim to.
    np.testing.assert_allclose(forward[:SINGLE_HAND_FEATURES], normalize_hand(HAND_A), atol=1e-6)
    np.testing.assert_allclose(forward[SINGLE_HAND_FEATURES:], normalize_hand(HAND_B), atol=1e-6)


def test_missing_hand_is_zero_filled():
    features = normalize_hands([{"handedness": "Right", "landmarks": HAND_A}])
    assert features.shape == (TWO_HAND_FEATURES,)
    assert np.all(features[:SINGLE_HAND_FEATURES] == 0.0)  # left slot empty
    assert np.any(features[SINGLE_HAND_FEATURES:] != 0.0)


def test_no_hands_gives_all_zeros():
    assert np.all(normalize_hands([]) == 0.0)
    assert np.all(normalize_hands(None) == 0.0)


def test_primary_hand_prefers_the_right():
    """Model A is trained on a right-handed dataset."""
    features = normalize_primary_hand(
        [
            {"handedness": "Left", "landmarks": HAND_A},
            {"handedness": "Right", "landmarks": HAND_B},
        ]
    )
    np.testing.assert_allclose(features, normalize_hand(HAND_B), atol=1e-6)


def test_primary_hand_falls_back_to_whatever_is_present():
    features = normalize_primary_hand([{"handedness": "Left", "landmarks": HAND_A}])
    np.testing.assert_allclose(features, normalize_hand(HAND_A), atol=1e-6)


# ---------------------------------------------------------------------------
# The cross-language parity check
# ---------------------------------------------------------------------------

NODE = shutil.which("node")

pytestmark_node = pytest.mark.skipif(
    NODE is None, reason="Node.js not installed — cannot run the JavaScript implementation"
)


def _run_js(script: str) -> object:
    """Execute a snippet against landmarkUtils.js and parse its JSON output."""
    # The module uses ESM `export`, so it is run as an .mjs-style module via
    # --input-type=module and imported by absolute file URL.
    program = f"import {{ normalizeHand, normalizeHands, normalizePrimaryHand, NORMALIZATION_VERSION }} from {json.dumps(JS_MODULE.as_uri())};\n{script}"

    completed = subprocess.run(
        [NODE, "--input-type=module", "-e", program],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if completed.returncode != 0:
        raise AssertionError(f"Node failed:\n{completed.stderr}")

    return json.loads(completed.stdout)


@pytestmark_node
def test_js_module_exists():
    assert JS_MODULE.is_file(), f"Missing {JS_MODULE}"


@pytestmark_node
def test_normalization_version_matches_across_languages():
    """A version bump in one language and not the other is its own silent bug."""
    js_version = _run_js("console.log(JSON.stringify(NORMALIZATION_VERSION));")
    assert js_version == NORMALIZATION_VERSION


@pytestmark_node
@pytest.mark.parametrize("hand,name", [(HAND_A, "hand_a"), (HAND_B, "hand_b")])
def test_single_hand_parity(hand, name):
    """THE test. Python and JavaScript must agree to 1e-6 on real input."""
    js_output = _run_js(
        f"console.log(JSON.stringify(Array.from(normalizeHand({json.dumps(hand)}))));"
    )
    python_output = normalize_hand(hand)

    assert len(js_output) == SINGLE_HAND_FEATURES

    np.testing.assert_allclose(
        np.array(js_output, dtype=np.float64),
        python_output.astype(np.float64),
        atol=TOLERANCE,
        err_msg=(
            f"Python and JavaScript normalisation disagree on {name}. "
            "This is the bug that makes training accuracy meaningless — fix it "
            "before touching anything else."
        ),
    )


@pytestmark_node
def test_two_hand_parity():
    hands = [
        {"handedness": "Left", "landmarks": HAND_A},
        {"handedness": "Right", "landmarks": HAND_B},
    ]
    js_output = _run_js(
        f"console.log(JSON.stringify(Array.from(normalizeHands({json.dumps(hands)}))));"
    )

    assert len(js_output) == TWO_HAND_FEATURES
    np.testing.assert_allclose(
        np.array(js_output, dtype=np.float64),
        normalize_hands(hands).astype(np.float64),
        atol=TOLERANCE,
    )


@pytestmark_node
def test_primary_hand_parity():
    hands = [
        {"handedness": "Left", "landmarks": HAND_A},
        {"handedness": "Right", "landmarks": HAND_B},
    ]
    js_output = _run_js(
        f"console.log(JSON.stringify(Array.from(normalizePrimaryHand({json.dumps(hands)}))));"
    )
    np.testing.assert_allclose(
        np.array(js_output, dtype=np.float64),
        normalize_primary_hand(hands).astype(np.float64),
        atol=TOLERANCE,
    )


@pytestmark_node
def test_degenerate_hand_parity():
    """Both implementations must return zeros, not NaN, for a collapsed hand."""
    js_output = _run_js(
        f"console.log(JSON.stringify(Array.from(normalizeHand({json.dumps(DEGENERATE_HAND)}))));"
    )
    assert all(value == 0 for value in js_output)
    np.testing.assert_allclose(
        np.array(js_output, dtype=np.float64),
        normalize_hand(DEGENERATE_HAND).astype(np.float64),
        atol=TOLERANCE,
    )


@pytestmark_node
def test_empty_hands_parity():
    js_output = _run_js("console.log(JSON.stringify(Array.from(normalizeHands([]))));")
    assert len(js_output) == TWO_HAND_FEATURES
    assert all(value == 0 for value in js_output)
