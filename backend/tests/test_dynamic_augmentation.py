"""Tests for Model B's sequence augmentation.

Two properties here are worth guarding, because getting either wrong produces a
model that trains fine and is quietly wrong:

1. **Mirroring must swap the hand slots.** The feature vector is laid out
   [left_hand, right_hand] by handedness. Negating x without swapping the slots
   claims a left hand performed the right hand's trajectory — a sign that does
   not exist. Nothing downstream would complain.

2. **Masked frames must stay exactly zero.** An all-zero timestep means "no
   hands visible", and the LSTM's Masking layer skips exactly those. Adding
   noise to one un-masks it, teaching the network that empty frames contain
   faint hand-shaped noise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from app.ml.normalization import SINGLE_HAND_FEATURES, TWO_HAND_FEATURES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ml" / "scripts" / "preprocess_dynamic.py"


def load_module():
    """Import preprocess_dynamic.py by path — ml/scripts is not a package."""
    spec = importlib.util.spec_from_file_location("preprocess_dynamic", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["preprocess_dynamic"] = module
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="preprocess_dynamic.py missing")


@pytest.fixture(scope="module")
def dyn():
    return load_module()


def make_sequence(length: int = 6, empty_at: tuple[int, ...] = ()) -> np.ndarray:
    """A sequence with distinguishable left and right hands."""
    rng = np.random.default_rng(0)
    sequence = np.zeros((length, TWO_HAND_FEATURES), dtype=np.float32)

    for index in range(length):
        if index in empty_at:
            continue
        # Left hand positive, right hand negative, so a slot swap is obvious.
        sequence[index, :SINGLE_HAND_FEATURES] = rng.uniform(0.1, 1.0, SINGLE_HAND_FEATURES)
        sequence[index, SINGLE_HAND_FEATURES:] = -rng.uniform(0.1, 1.0, SINGLE_HAND_FEATURES)

    return sequence


# --------------------------------------------------------------------------- #
# Mirroring
# --------------------------------------------------------------------------- #


def test_mirroring_swaps_the_hand_slots(dyn):
    """The left hand's data must end up in the right hand's slot."""
    sequence = make_sequence()
    mirrored = dyn.mirror_sequence(sequence)

    original_left = sequence[:, :SINGLE_HAND_FEATURES]
    mirrored_right = mirrored[:, SINGLE_HAND_FEATURES:]

    # Every coordinate should match except x, which is negated. Landmark layout
    # is x,y,z repeating, so x sits at indices 0, 3, 6, ...
    is_x = np.zeros(SINGLE_HAND_FEATURES, dtype=bool)
    is_x[0::3] = True

    np.testing.assert_allclose(mirrored_right[:, ~is_x], original_left[:, ~is_x], atol=1e-6)
    np.testing.assert_allclose(mirrored_right[:, is_x], -original_left[:, is_x], atol=1e-6)


def test_mirroring_twice_is_the_identity(dyn):
    """A property that would fail loudly if the swap were one-directional."""
    sequence = make_sequence()
    np.testing.assert_allclose(
        dyn.mirror_sequence(dyn.mirror_sequence(sequence)), sequence, atol=1e-6
    )


def test_mirroring_preserves_masked_frames(dyn):
    sequence = make_sequence(empty_at=(0, 4))
    mirrored = dyn.mirror_sequence(sequence)

    # Exactly zero, not -0.0 and not near-zero: the Masking layer compares
    # against 0.0 across the whole feature axis.
    assert np.all(mirrored[0] == 0.0)
    assert np.all(mirrored[4] == 0.0)
    assert np.signbit(mirrored[0]).sum() == 0, "negated zeros left as -0.0"


# --------------------------------------------------------------------------- #
# Noise
# --------------------------------------------------------------------------- #


def test_noise_never_un_masks_an_empty_frame(dyn):
    """The bug this test exists for would be invisible in training output."""
    rng = np.random.default_rng(1)
    sequence = make_sequence(empty_at=(1, 3, 5))

    noised = dyn.jitter_sequence(sequence, 0.015, rng)

    for index in (1, 3, 5):
        assert np.all(noised[index] == 0.0), f"frame {index} was un-masked by noise"


def test_noise_actually_perturbs_real_frames(dyn):
    """The complement of the test above — masking must not silence everything."""
    rng = np.random.default_rng(1)
    sequence = make_sequence()

    noised = dyn.jitter_sequence(sequence, 0.015, rng)

    assert not np.allclose(noised, sequence), "noise had no effect at all"
    # But it should be small: this is jitter, not a different sample.
    assert np.abs(noised - sequence).max() < 0.15


def test_noise_leaves_an_absent_hand_slot_at_zero(dyn):
    """One hand missing while the other is visible is a normal, valid frame."""
    rng = np.random.default_rng(2)
    sequence = np.zeros((4, TWO_HAND_FEATURES), dtype=np.float32)
    sequence[:, SINGLE_HAND_FEATURES:] = 0.5  # right hand only

    noised = dyn.jitter_sequence(sequence, 0.015, rng)

    assert np.all(noised[:, :SINGLE_HAND_FEATURES] == 0.0)
    assert not np.allclose(noised[:, SINGLE_HAND_FEATURES:], 0.5)


# --------------------------------------------------------------------------- #
# Rotation
# --------------------------------------------------------------------------- #


def test_rotation_preserves_masked_frames(dyn):
    sequence = make_sequence(empty_at=(2,))
    rotated = dyn.rotate_sequence(sequence, 12.0)
    assert np.all(rotated[2] == 0.0)


def test_rotation_preserves_distances_from_the_origin(dyn):
    """Rotation must not change hand size — that is what makes it label-safe."""
    sequence = make_sequence()
    rotated = dyn.rotate_sequence(sequence, 25.0)

    original = sequence[:, :SINGLE_HAND_FEATURES].reshape(len(sequence), -1, 3)
    turned = rotated[:, :SINGLE_HAND_FEATURES].reshape(len(sequence), -1, 3)

    # Only x and y are rotated, so the in-plane radius is what must be preserved.
    np.testing.assert_allclose(
        np.linalg.norm(original[..., :2], axis=-1),
        np.linalg.norm(turned[..., :2], axis=-1),
        atol=1e-5,
    )
    np.testing.assert_allclose(original[..., 2], turned[..., 2], atol=1e-6)


def test_rotation_by_zero_changes_nothing(dyn):
    sequence = make_sequence()
    np.testing.assert_allclose(dyn.rotate_sequence(sequence, 0.0), sequence, atol=1e-6)


def test_rotation_is_constant_across_the_sequence(dyn):
    """One angle per clip, not one per frame.

    A per-frame angle would add rotational jitter between timesteps and teach
    the recurrent layers a wobble that no signer produces.
    """
    sequence = np.tile(make_sequence(length=1), (5, 1))
    rotated = dyn.rotate_sequence(sequence, 15.0)

    for index in range(1, len(rotated)):
        np.testing.assert_allclose(rotated[index], rotated[0], atol=1e-6)


# --------------------------------------------------------------------------- #
# The whole augmentation pass
# --------------------------------------------------------------------------- #


def test_augmentation_quadruples_the_training_set_and_keeps_labels_aligned(dyn):
    sequences = np.stack([make_sequence() for _ in range(5)])
    targets = np.array([0, 1, 2, 3, 4], dtype=np.int64)

    grown, labels = dyn.augment_training_set(sequences, targets, seed=42)

    assert len(grown) == len(sequences) * 4
    assert len(labels) == len(grown)
    # Original, rotated, noised, mirrored — each block carries the same labels
    # in the same order. A shuffle here would silently mislabel everything.
    for block in range(4):
        np.testing.assert_array_equal(labels[block * 5 : (block + 1) * 5], targets)


def test_augmentation_is_deterministic_for_a_given_seed(dyn):
    sequences = np.stack([make_sequence() for _ in range(3)])
    targets = np.array([0, 1, 2], dtype=np.int64)

    first, _ = dyn.augment_training_set(sequences, targets, seed=7)
    second, _ = dyn.augment_training_set(sequences, targets, seed=7)

    np.testing.assert_allclose(first, second)
