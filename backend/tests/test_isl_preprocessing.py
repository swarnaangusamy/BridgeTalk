"""Tests for the two-handed (ISL) preprocessing path.

ISL fingerspelling is two-handed, which turns three things in preprocess.py
from trivial into easy-to-get-silently-wrong:

1. **Normalisation is per hand.** Each hand has its own wrist and its own
   scale. Treating the 42 points as one hand would subtract the left wrist
   from the right hand's landmarks and quietly corrupt every sample.
2. **Mirroring must swap the hand slots.** The vector is [left(63), right(63)]
   by handedness; negating x without swapping claims the left hand performed
   the right hand's shape.
3. **An absent hand must stay exactly zero.** Several ISL letters are
   one-handed, and MediaPipe loses a hand to occlusion constantly. Noise added
   to a zero slot invents a hand that was never there.

None of the three would raise. All three would train.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from app.ml.normalization import (
    NUM_LANDMARKS,
    SINGLE_HAND_FEATURES,
    TWO_HAND_FEATURES,
    normalize_hand,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ml" / "scripts" / "preprocess.py"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="preprocess.py missing")


@pytest.fixture(scope="module")
def pre():
    spec = importlib.util.spec_from_file_location("preprocess_mod", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["preprocess_mod"] = module
    spec.loader.exec_module(module)
    return module


def a_hand(seed: int, offset: float = 0.0, scale: float = 1.0) -> np.ndarray:
    """A normalised single hand, optionally moved and resized."""
    rng = np.random.default_rng(seed)
    points = rng.normal(0, 1, (NUM_LANDMARKS, 3)).astype(np.float32)
    points[0] = 0.0  # wrist at origin
    normalised = normalize_hand(points).reshape(NUM_LANDMARKS, 3)
    return (normalised * scale + offset).ravel()


def two_hands(left: np.ndarray | None, right: np.ndarray | None) -> np.ndarray:
    out = np.zeros(TWO_HAND_FEATURES, dtype=np.float32)
    if left is not None:
        out[:SINGLE_HAND_FEATURES] = left
    if right is not None:
        out[SINGLE_HAND_FEATURES:] = right
    return out


# --------------------------------------------------------------------------- #
# Per-hand normalisation
# --------------------------------------------------------------------------- #


def test_renormalize_treats_each_hand_independently(pre):
    """Two hands at different places and sizes must BOTH end up canonical.

    This is the test that would fail if the 42 points were treated as one hand:
    the right hand would be centred on the left hand's wrist.
    """
    sample = two_hands(a_hand(1, offset=5.0, scale=3.0), a_hand(2, offset=-2.0, scale=0.5))

    result = pre.renormalize(sample[None, :], hands=2)[0]

    for slot in range(2):
        block = result[slot * SINGLE_HAND_FEATURES : (slot + 1) * SINGLE_HAND_FEATURES]
        points = block.reshape(NUM_LANDMARKS, 3)

        # Wrist at the origin.
        np.testing.assert_allclose(points[0], np.zeros(3), atol=1e-5)
        # Furthest landmark at distance 1.
        assert np.linalg.norm(points, axis=1).max() == pytest.approx(1.0, abs=1e-5)


def test_renormalize_leaves_an_absent_hand_at_zero(pre):
    sample = two_hands(None, a_hand(3, offset=4.0))

    result = pre.renormalize(sample[None, :], hands=2)[0]

    assert np.all(result[:SINGLE_HAND_FEATURES] == 0.0)
    assert not np.all(result[SINGLE_HAND_FEATURES:] == 0.0)


def test_renormalize_one_hand_is_unchanged_behaviour(pre):
    """Regression guard: the ASL path must be untouched by the ISL work."""
    sample = (a_hand(4) * 2.5 + 1.0)[None, :]

    result = pre.renormalize(sample, hands=1)[0].reshape(NUM_LANDMARKS, 3)

    np.testing.assert_allclose(result[0], np.zeros(3), atol=1e-5)
    assert np.linalg.norm(result, axis=1).max() == pytest.approx(1.0, abs=1e-5)


# --------------------------------------------------------------------------- #
# Mirroring
# --------------------------------------------------------------------------- #


def test_mirroring_swaps_the_hand_slots(pre):
    """The left hand's data must land in the right hand's slot."""
    left, right = a_hand(5), a_hand(6)
    sample = two_hands(left, right)[None, :]

    mirrored = pre.mirror(sample, hands=2)[0]

    is_x = np.zeros(SINGLE_HAND_FEATURES, dtype=bool)
    is_x[0::3] = True

    got_right = mirrored[SINGLE_HAND_FEATURES:]
    np.testing.assert_allclose(got_right[~is_x], left[~is_x], atol=1e-6)
    np.testing.assert_allclose(got_right[is_x], -left[is_x], atol=1e-6)


def test_mirroring_twice_is_the_identity(pre):
    sample = two_hands(a_hand(7), a_hand(8))[None, :]
    np.testing.assert_allclose(
        pre.mirror(pre.mirror(sample, hands=2), hands=2), sample, atol=1e-6
    )


def test_mirroring_moves_a_one_handed_letter_to_the_other_slot(pre):
    """A right-handed-only ISL letter mirrors into a left-handed one.

    That is the whole accessibility point of mirroring, and it only works if
    the slots swap.
    """
    sample = two_hands(None, a_hand(9))[None, :]

    mirrored = pre.mirror(sample, hands=2)[0]

    assert np.all(mirrored[SINGLE_HAND_FEATURES:] == 0.0), "right slot should now be empty"
    assert not np.all(mirrored[:SINGLE_HAND_FEATURES] == 0.0), "left slot should be filled"


def test_mirroring_one_hand_does_not_swap_anything(pre):
    """Regression guard for ASL: negate x, keep the single slot."""
    sample = a_hand(10)[None, :]

    mirrored = pre.mirror(sample, hands=1)[0]

    is_x = np.zeros(SINGLE_HAND_FEATURES, dtype=bool)
    is_x[0::3] = True
    np.testing.assert_allclose(mirrored[~is_x], sample[0][~is_x], atol=1e-6)
    np.testing.assert_allclose(mirrored[is_x], -sample[0][is_x], atol=1e-6)


def test_mirroring_leaves_no_negative_zeros(pre):
    """-0.0 is not `== 0.0`-safe to reason about downstream."""
    sample = two_hands(None, a_hand(11))[None, :]
    mirrored = pre.mirror(sample, hands=2)[0]
    assert np.signbit(mirrored[SINGLE_HAND_FEATURES:]).sum() == 0


# --------------------------------------------------------------------------- #
# Augmentation as a whole
# --------------------------------------------------------------------------- #


def test_noise_never_invents_a_second_hand(pre):
    """A one-handed letter must not gain a faint hand made of noise."""
    rng = np.random.default_rng(0)
    samples = np.stack([two_hands(None, a_hand(12 + i)) for i in range(4)])
    labels = np.zeros(4, dtype=np.int64)

    grown, _ = pre.augment(
        samples, labels, rounds=2, max_rotation_degrees=12.0,
        noise_std=0.015, mirror_enabled=False, rng=rng, hands=2,
    )

    # Every sample must still have exactly one populated hand slot.
    for row in grown:
        left_empty = np.all(row[:SINGLE_HAND_FEATURES] == 0.0)
        right_empty = np.all(row[SINGLE_HAND_FEATURES:] == 0.0)
        assert left_empty != right_empty, "a hand was invented or destroyed"


def test_augmentation_keeps_labels_aligned(pre):
    rng = np.random.default_rng(1)
    samples = np.stack([two_hands(a_hand(20 + i), a_hand(30 + i)) for i in range(5)])
    labels = np.arange(5, dtype=np.int64)

    grown, grown_labels = pre.augment(
        samples, labels, rounds=2, max_rotation_degrees=12.0,
        noise_std=0.015, mirror_enabled=True, rng=rng, hands=2,
    )

    # original + 2 rounds + mirror = 4 blocks
    assert len(grown) == len(samples) * 4
    assert len(grown_labels) == len(grown)
    for block in range(4):
        np.testing.assert_array_equal(grown_labels[block * 5 : (block + 1) * 5], labels)


def test_rotation_preserves_each_hand_size(pre):
    """Rotation must not resize either hand — that is what keeps it label-safe."""
    sample = two_hands(a_hand(40), a_hand(41))[None, :]

    rotated = pre.rotate_2d(sample, np.radians(20.0), hands=2)[0]

    for slot in range(2):
        original = sample[0][slot * SINGLE_HAND_FEATURES : (slot + 1) * SINGLE_HAND_FEATURES]
        turned = rotated[slot * SINGLE_HAND_FEATURES : (slot + 1) * SINGLE_HAND_FEATURES]

        o = original.reshape(NUM_LANDMARKS, 3)
        t = turned.reshape(NUM_LANDMARKS, 3)
        np.testing.assert_allclose(
            np.linalg.norm(o[:, :2], axis=1), np.linalg.norm(t[:, :2], axis=1), atol=1e-5
        )
        np.testing.assert_allclose(o[:, 2], t[:, 2], atol=1e-6)
