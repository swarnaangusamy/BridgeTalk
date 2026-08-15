# BridgeTalk — Machine Learning

> **Phase 0 skeleton.** Everything here that describes a *decision* is final;
> everything that describes a *result* arrives in Phases 3 and 4.

This directory holds everything that happens **before** the application runs:
downloading public datasets, turning images and videos into landmark vectors,
training models, and evaluating them.

---

## The hard constraint

**All training data comes from publicly available datasets.** No one on this
team recorded gestures to train a model, and no script in this repository
collects training data.

Two scripts use the webcam. Neither writes training samples:

| Script | What it does | What it is not |
|---|---|---|
| `scripts/test_realtime.py` | Opens an OpenCV window and runs the **already-trained** model live | Not a data collector |
| `scripts/record_eval_clip.py` | Records a short clip to **evaluate** the trained model against | Not a data collector |

Why this matters: a model trained on data we recorded ourselves would be tested
on hands, lighting and a camera it had already seen, and the accuracy number
would be meaningless. Training on public data and testing on our own webcam is
harder, produces a lower number, and is the honest measurement.

---

## Pipeline

```
Kaggle
  │  download_datasets.py          fetch + verify, with human-readable errors
  ▼
ml/data/raw/                       images and videos              (gitignored)
  │  extract_landmarks_images.py   OpenCV + MediaPipe IMAGE mode → 21×3 points
  │  extract_landmarks_video.py    MediaPipe VIDEO mode → (30, 126) sequences
  ▼
ml/data/processed/                 landmark CSV / NPY             (gitignored)
  │  preprocess.py                 normalise · augment · split by source file
  ▼
  │  train_static.py               MLP     (63,)      → 29 classes
  │  train_dynamic.py              LSTM    (30, 126)  → 20 classes
  ▼
ml/models/                         .keras + labels.json + metadata.json
  │  evaluate.py                   classification report + confusion matrix
  ▼
docs/images/                       plots committed to the repo
```

---

## Model A — static fingerspelling (primary deliverable)

**Dataset:** ASL Alphabet — Kaggle `grassknoted/asl-alphabet`
(~87,000 images, 200×200 px, 29 classes: A–Z plus `space`, `delete`, `nothing`)

**Why a single-frame MLP:** these are *static* handshapes. The letter A is fully
determined by one frame — there is no motion to model — so a recurrent network
would add parameters and training time for no benefit.

```
Input (63,)  →  Dense 256 ReLU → BatchNorm → Dropout 0.3
             →  Dense 128 ReLU → BatchNorm → Dropout 0.3
             →  Dense  64 ReLU
             →  Dense  n_classes Softmax
```

Adam (lr 1e-3), sparse categorical crossentropy, EarlyStopping (patience 10,
restore best weights), ReduceLROnPlateau, batch 64, up to 100 epochs.

**Expected:** 92–98% validation accuracy. _(Actual: Phase 4.)_

**Why the `nothing` class is kept:** without a neutral class the model has no way
to say "that is not a letter", so it confidently classifies a hand scratching a
nose as a `C`. The neutral class is also what drives the word-boundary reset in
the smoothing algorithm.

---

## Model B — dynamic word signs (stretch goal)

**Dataset (preferred):** WLASL processed — Kaggle `risangbaskoro/wlasl-processed`,
restricted to the 20 glosses with the most video samples.

```
Input (30, 126) →  Masking
                →  LSTM 128 return_sequences → Dropout 0.3
                →  LSTM  64                  → Dropout 0.3
                →  Dense 64 ReLU → Dense n_classes Softmax
```

**Be upfront about the expected result:** on CPU, with 20 WLASL glosses,
realistic validation accuracy is roughly **55–80%**, and live webcam performance
will be *worse* than that, because the dataset's lighting, cameras and framing
differ from ours. That domain gap is a well-known and publishable limitation,
not a project failure — it belongs in the failure-analysis section, not hidden.

_(Result and recommendation: Phase 4.)_

---

## Landmark normalisation — the critical detail

Raw MediaPipe coordinates depend on where the hand is in the frame and how far
it is from the camera. Two people signing the identical letter produce different
numbers. Normalisation removes both effects:

1. **Translate** — subtract the wrist landmark (index 0) from all 21 points.
   The hand's position in the frame no longer matters.
2. **Scale** — divide by the maximum Euclidean distance from the wrist.
   The hand's distance from the camera no longer matters.
3. **Flatten** to 63 floats in fixed landmark order.
4. **Two hands** — order as `[left(63), right(63)]` using MediaPipe's handedness
   output; zero-fill a hand that is not present.

This is implemented three times — here, in `backend/app/ml/normalization.py`,
and in `frontend/src/utils/landmarkUtils.js` — and a parity test in
`backend/tests/` asserts all implementations agree to `1e-6`.

`metadata.json` records `"normalization_version": 1`. The backend refuses to
load a model whose version does not match the running code, which turns a stale
model file into a loud startup error rather than a silent accuracy collapse.

---

## Data hygiene rules (enforced in code)

- **Split by source file / signer, never by frame.** Frames from one image
  folder or one video must not appear in both train and test — otherwise the
  model is graded on data it has effectively already seen. 70/15/15, stratified.
- **Augment landmark vectors, not images**: small random rotation, scale jitter,
  Gaussian coordinate noise, horizontal mirroring with handedness swapped.
  Augmenting the images instead would mean re-running MediaPipe on every
  variant — hours of CPU for the same effect.
- **Write `dataset_manifest.json`** recording source dataset, version, class
  counts, split sizes, augmentation settings and extraction date.

---

## Running the pipeline

_(Phase 3 — exact commands with expected output and runtimes.)_
