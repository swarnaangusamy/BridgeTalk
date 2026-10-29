"""Derive a NumPy-servable `.npz` from each trained `.keras` model.

    python ml/scripts/export_numpy_weights.py

WHY
---
TensorFlow needs 523 MB of resident memory just to import, measured on this
project. The models are 38 MB between them. Serving them with NumPy instead
(26 MB) is the difference between fitting a 512 MB instance and being killed
during boot. See `backend/app/ml/numpy_model.py`.

The `.keras` files stay the source of truth — this reads them and writes a
sidecar. Re-run it after any retrain, or the sidecar silently serves the old
weights while the `.keras` file holds the new ones.

Every export is verified against Keras before it is written: if the two
disagree by more than 1e-5 on random inputs, nothing is saved.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from app.config import settings  # noqa: E402

TOLERANCE = 1e-5


def build_spec(model) -> tuple[list[dict], dict[str, np.ndarray]]:
    spec: list[dict] = []
    arrays: dict[str, np.ndarray] = {}

    for index, layer in enumerate(model.layers):
        kind = layer.__class__.__name__
        config = layer.get_config()

        if kind == "Dense":
            weight, bias = (w.numpy() for w in layer.weights)
            arrays[f"l{index}_W"] = weight
            arrays[f"l{index}_b"] = bias
            spec.append({
                "kind": "dense", "act": config["activation"],
                "W": f"l{index}_W", "b": f"l{index}_b",
                "units": int(config["units"]),
            })

        elif kind == "BatchNormalization":
            gamma, beta, mean, var = (w.numpy() for w in layer.weights)
            for name, value in (("gamma", gamma), ("beta", beta),
                                ("mean", mean), ("var", var)):
                arrays[f"l{index}_{name}"] = value
            spec.append({
                "kind": "batchnorm", "eps": float(config["epsilon"]),
                "gamma": f"l{index}_gamma", "beta": f"l{index}_beta",
                "mean": f"l{index}_mean", "var": f"l{index}_var",
            })

        elif kind == "Masking":
            spec.append({"kind": "masking", "value": float(config["mask_value"])})

        elif kind == "Dropout":
            spec.append({"kind": "dropout"})

        elif kind == "Bidirectional":
            inner = config["layer"]["config"]
            if config["layer"]["class_name"] != "LSTM":
                raise SystemExit(f"Only LSTM is supported inside Bidirectional, got "
                                 f"{config['layer']['class_name']}")
            if config["merge_mode"] != "concat":
                raise SystemExit(f"Only merge_mode='concat' is supported, got "
                                 f"{config['merge_mode']}")
            entry = {"kind": "bidirectional",
                     "return_sequences": bool(inner["return_sequences"])}
            for side, sub in (("fw", layer.forward_layer), ("bw", layer.backward_layer)):
                kernel, recurrent, bias = (w.numpy() for w in sub.weights)
                arrays[f"l{index}_{side}_W"] = kernel
                arrays[f"l{index}_{side}_U"] = recurrent
                arrays[f"l{index}_{side}_b"] = bias
                entry[side] = {"W": f"l{index}_{side}_W",
                               "U": f"l{index}_{side}_U",
                               "b": f"l{index}_{side}_b"}
            spec.append(entry)

        elif kind in ("InputLayer",):
            continue

        else:
            raise SystemExit(f"Unsupported layer {kind!r} in {model.name}")

    return spec, arrays


def main() -> int:
    import keras

    from app.ml.numpy_model import NumpyModel

    targets = [
        ("static", settings.static_model_path, (63,)),
        ("isl", settings.isl_model_path, (126,)),
        ("dynamic", settings.dynamic_model_path, (30, 132)),
    ]

    failures = 0
    for name, relative, shape in targets:
        source = settings.resolve_path(relative)
        if not source.exists():
            print(f"  {name:8s} SKIP — {source} not found")
            continue

        model = keras.saving.load_model(source)
        model(np.zeros((1, *shape), dtype="float32"))
        spec, arrays = build_spec(model)

        destination = source.with_suffix(".npz")
        np.savez_compressed(destination, spec=json.dumps(spec),
                            input_shape=np.array(shape, dtype=np.int64), **arrays)

        # Verify BEFORE trusting it. A reimplementation that is subtly wrong
        # still returns a tidy probability vector, so only a comparison finds it.
        rng = np.random.default_rng(0)
        probe = rng.standard_normal((8, *shape)).astype("float32")
        expected = model.predict(probe, verbose=0)
        actual = NumpyModel.load(destination)(probe).numpy()
        difference = float(np.abs(actual - expected).max())

        if difference > TOLERANCE:
            destination.unlink(missing_ok=True)
            print(f"  {name:8s} FAILED — max|diff| {difference:.2e} exceeds {TOLERANCE}")
            failures += 1
        else:
            size = destination.stat().st_size / 1024
            print(f"  {name:8s} ok — max|diff| {difference:.2e}, {size:.0f} KB "
                  f"-> {destination.relative_to(ROOT)}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
