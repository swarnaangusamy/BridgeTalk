"""Run the trained Keras models with NumPy alone, for memory-constrained hosts.

WHY THIS EXISTS
---------------
TensorFlow costs **523 MB of resident memory just to import** — measured on
this project, before a single model is loaded. The three models themselves are
38 MB between them. A 512 MB instance is therefore killed by the OOM reaper
part-way through boot, and no amount of configuration changes that: the weights
are not the problem, the framework is.

NumPy is 26 MB. These models are small enough that running them by hand is
straightforward and exact:

    static   Dense(relu) BN Dropout Dense(relu) BN Dropout Dense(relu) Dense(softmax)
    isl      the same shape, 126 inputs and 35 classes
    dynamic  Masking -> BiLSTM(128, seq) -> BiLSTM(64) -> Dense(relu) Dense(softmax)

TRAINING IS UNCHANGED. Keras still trains and still writes the `.keras` files,
which remain the source of truth; `ml/scripts/export_numpy_weights.py` derives
the `.npz` from them. This module only *serves*.

EXACTNESS IS CHECKED, NOT ASSUMED
---------------------------------
Reimplementing a model is precisely the kind of change that produces confident
nonsense: the shapes all fit, the softmax still sums to 1, and the predictions
are quietly wrong. `backend/tests/test_numpy_model_parity.py` runs both
implementations over the same inputs and fails if they diverge. Measured at
export time, the largest disagreement across all three models is 4.8e-07.

The LSTM follows Keras' own conventions, which the parity test is what proves:
gates are ordered i, f, c, o in the kernel; a masked timestep leaves both the
hidden and cell state untouched; and the backward direction walks the sequence
in reverse before the two halves are concatenated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    # Written in the stable form: exp() of a large positive number overflows,
    # and a logistic saturating to 1.0 is not an error worth a RuntimeWarning.
    out = np.empty_like(x)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def _activate(x: np.ndarray, name: str) -> np.ndarray:
    if name == "relu":
        return np.maximum(x, 0.0)
    if name == "softmax":
        shifted = x - x.max(axis=-1, keepdims=True)
        e = np.exp(shifted)
        return e / e.sum(axis=-1, keepdims=True)
    if name == "tanh":
        return np.tanh(x)
    if name in ("linear", None):
        return x
    raise ValueError(f"Unsupported activation {name!r}")


class _Result:
    """Mimics the TensorFlow tensor `predict()` expects, so it needs no branch."""

    __slots__ = ("_value",)

    def __init__(self, value: np.ndarray) -> None:
        self._value = value

    def numpy(self) -> np.ndarray:
        return self._value


class NumpyModel:
    """A loaded `.npz`, callable exactly like the compiled Keras graph it replaces."""

    def __init__(self, spec: list[dict[str, Any]], arrays: dict[str, np.ndarray],
                 input_shape: tuple[int, ...]) -> None:
        self._spec = spec
        self._a = arrays
        self._classes = int(spec[-1]["units"])
        self._input_shape = tuple(int(d) for d in input_shape)

    @classmethod
    def load(cls, path: Path) -> "NumpyModel":
        with np.load(path, allow_pickle=False) as data:
            spec = json.loads(str(data["spec"]))
            input_shape = tuple(data["input_shape"].tolist())
            arrays = {k: data[k] for k in data.files
                      if k not in ("spec", "input_shape")}
        return cls(spec, arrays, input_shape)

    @property
    def output_shape(self) -> tuple[Any, int]:
        """Shaped like Keras', because the loader sanity-checks it against labels."""
        return (None, self._classes)

    @property
    def input_shape(self) -> tuple[Any, ...]:
        """Also Keras-shaped: the loader compares it against the pipeline's."""
        return (None, *self._input_shape)

    # -- the layers ---------------------------------------------------------

    def _lstm(self, x: np.ndarray, w: dict[str, str], mask: np.ndarray,
              backwards: bool) -> tuple[np.ndarray, np.ndarray]:
        kernel = self._a[w["W"]]
        recurrent = self._a[w["U"]]
        bias = self._a[w["b"]]

        batch, steps, _ = x.shape
        units = recurrent.shape[0]
        h = np.zeros((batch, units), dtype=np.float32)
        c = np.zeros((batch, units), dtype=np.float32)
        out = np.zeros((batch, steps, units), dtype=np.float32)

        order = range(steps - 1, -1, -1) if backwards else range(steps)
        for t in order:
            z = x[:, t] @ kernel + h @ recurrent + bias
            i = _sigmoid(z[:, :units])
            f = _sigmoid(z[:, units:2 * units])
            g = np.tanh(z[:, 2 * units:3 * units])
            o = _sigmoid(z[:, 3 * units:4 * units])
            c_next = f * c + i * g
            h_next = o * np.tanh(c_next)

            # A masked timestep carries the state forward untouched. Keras does
            # the same, and getting it wrong would quietly change every
            # prediction made on a short sequence — which is most of them.
            keep = mask[:, t][:, None]
            h = np.where(keep, h_next, h)
            c = np.where(keep, c_next, c)
            out[:, t] = h
        return out, h

    def __call__(self, batch: np.ndarray) -> _Result:
        x = np.asarray(batch, dtype=np.float32)
        mask: np.ndarray | None = None

        for layer in self._spec:
            kind = layer["kind"]

            if kind == "masking":
                mask = ~np.all(x == layer["value"], axis=-1)

            elif kind == "dense":
                x = _activate(x @ self._a[layer["W"]] + self._a[layer["b"]], layer["act"])

            elif kind == "batchnorm":
                gamma = self._a[layer["gamma"]]
                beta = self._a[layer["beta"]]
                mean = self._a[layer["mean"]]
                var = self._a[layer["var"]]
                x = gamma * (x - mean) / np.sqrt(var + layer["eps"]) + beta

            elif kind == "bidirectional":
                if mask is None:
                    mask = np.ones(x.shape[:2], dtype=bool)
                forward, last_f = self._lstm(x, layer["fw"], mask, False)
                backward, last_b = self._lstm(x, layer["bw"], mask, True)
                x = (
                    np.concatenate([forward, backward], axis=-1)
                    if layer["return_sequences"]
                    else np.concatenate([last_f, last_b], axis=-1)
                )

            elif kind == "dropout":
                # Identity at inference. Listed in the spec rather than dropped
                # so the file still describes the architecture it came from.
                continue

            else:
                raise ValueError(f"Unsupported layer {kind!r}")

        return _Result(x)
