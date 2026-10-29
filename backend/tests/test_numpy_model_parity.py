"""The NumPy models must agree with the Keras models they were derived from.

This is the same class of guard as `test_normalization_parity.py`, for the same
reason. Serving the models with NumPy instead of TensorFlow is what makes the
app fit a 512 MB instance — TensorFlow needs 523 MB just to import — but a
reimplementation that is subtly wrong does not announce itself. The shapes
still fit, the softmax still sums to 1, and every prediction is confident and
wrong.

So the two implementations are run over the same inputs and compared. The
export script applies the same check before it writes a file; this re-applies
it to whatever is actually committed, which is the thing that gets served.

Skipped when TensorFlow is absent — which is exactly the case in production,
where there is nothing to compare against and nothing to drift.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.config import settings
from app.ml.numpy_model import NumpyModel

keras = pytest.importorskip("keras", reason="TensorFlow/Keras is not installed")

# Loose enough for float32 accumulated over 30 LSTM timesteps, tight enough
# that a wrong gate order or a mishandled mask cannot slip through: those are
# wrong in the first or second decimal place, not the sixth.
TOLERANCE = 1e-5

CASES = [
    ("static", settings.static_model_path, (63,)),
    ("isl", settings.isl_model_path, (126,)),
    ("dynamic", settings.dynamic_model_path, (30, 132)),
]


@pytest.mark.parametrize("name,relative,shape", CASES)
def test_numpy_matches_keras(name, relative, shape):
    source = settings.resolve_path(relative)
    sidecar = source.with_suffix(".npz")

    if not source.exists() or not sidecar.exists():
        pytest.skip(f"{name}: model or sidecar not present")

    model = keras.saving.load_model(source)
    numpy_model = NumpyModel.load(sidecar)

    rng = np.random.default_rng(1234)
    probe = rng.standard_normal((16, *shape)).astype(np.float32)

    expected = model.predict(probe, verbose=0)
    actual = numpy_model(probe).numpy()

    difference = float(np.abs(actual - expected).max())
    assert difference < TOLERANCE, (
        f"{name}: NumPy and Keras disagree by {difference:.2e}. "
        f"Re-run ml/scripts/export_numpy_weights.py — the sidecar is stale or wrong."
    )

    # The argmax is what actually becomes a caption, so it is asserted in its
    # own right rather than left implied by the tolerance above.
    assert (actual.argmax(-1) == expected.argmax(-1)).all(), (
        f"{name}: the two implementations pick different classes."
    )


@pytest.mark.parametrize("name,relative,shape", CASES)
def test_sidecar_declares_the_right_shapes(name, relative, shape):
    """A sidecar from the wrong run would otherwise load and serve nonsense."""
    sidecar = settings.resolve_path(relative).with_suffix(".npz")
    if not sidecar.exists():
        pytest.skip(f"{name}: sidecar not present")

    numpy_model = NumpyModel.load(sidecar)
    assert tuple(numpy_model.input_shape[1:]) == shape


def test_masked_timesteps_do_not_change_the_result():
    """Padding a sequence must not alter the prediction.

    The dynamic model is fed a fixed 30-frame window that is zero-padded when
    the signer has produced fewer frames, so this is the ordinary case rather
    than an edge one. If masking were ignored, every short sequence would be
    classified from its padding.
    """
    sidecar = settings.resolve_path(settings.dynamic_model_path).with_suffix(".npz")
    if not sidecar.exists():
        pytest.skip("dynamic sidecar not present")

    numpy_model = NumpyModel.load(sidecar)
    rng = np.random.default_rng(7)

    real = rng.standard_normal((1, 12, 132)).astype(np.float32)
    padded = np.zeros((1, 30, 132), dtype=np.float32)
    padded[:, :12] = real

    more_padding = np.zeros((1, 30, 132), dtype=np.float32)
    more_padding[:, :12] = real  # identical content, same padding region

    assert np.abs(numpy_model(padded).numpy() - numpy_model(more_padding).numpy()).max() == 0.0
