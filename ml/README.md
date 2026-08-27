# BridgeTalk — Machine Learning

> Results below are real and reproducible: `extract_landmarks_images.py`,
> `preprocess.py`, `train_static.py` and `evaluate.py` produce them from the
> public dataset in about 15 minutes on a CPU.

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
  │                                 --dataset include (ISL) | wlasl (ASL)
  ▼
ml/data/processed/                 landmark CSV / NPZ             (gitignored)
  │  preprocess.py                 balance · augment · split by capture order
  │  preprocess_dynamic.py         augment · split by SIGNER (holds out people)
  ▼
  │  train_static.py               MLP     (63,)      → 28 classes
  │  train_dynamic.py              LSTM    (30, 126)  → 20 glosses
  ▼
ml/models/                         .keras + labels.json + metadata.json
  │  evaluate.py                   classification report + confusion matrix
  ▼                                (one script, both models — see --prefix)
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

**Actual:** 94.0% validation, **90.5% top-1** and 96.9% top-3 on a held-out
test split of 6,440 samples. Trained in **62 seconds on a CPU**, 60,892
parameters, early stopping at epoch 18 of 100. Full analysis in the
[README](../README.md#10-model-results).

**What happened to the `nothing` class — a finding, not an omission.**

The plan was to keep `nothing` as a neutral class, on solid reasoning: without
one, the model has no way to say "that is not a letter" and will confidently
classify a hand scratching a nose as a `C`.

Extraction made that impossible. The `nothing` folder discarded at **99.5%**,
because those images contain no hand, so MediaPipe returns no landmarks, so
there is nothing to classify. The 14 rows that survived are false detections.
This is a structural consequence of classifying landmarks rather than pixels —
it would not have affected a pixel-based CNN at all.

So the neutral state moved out of the model and into the pipeline: **when no
hand is detected, the backend emits `nothing` without consulting the model.**
That is deterministic, costs no inference, and is more reliable than a learned
class would have been. It is also why `labels.json` lists 28 classes, not 29,
and the reason is recorded in `dataset_manifest.json` rather than left implicit.

---

## Model C — Indian Sign Language alphabet

**This is the alphabet BridgeTalk is being demonstrated with.** The demo signer
signs ISL, so an ASL model would produce nonsense for them — not slightly worse
output, but unrelated output.

**Dataset:** chosen manually. `download_datasets.py` deliberately does **not**
name one:

    python ml/scripts/download_datasets.py --dataset isl --verify

Several ISL alphabet datasets exist on Kaggle with different class sets and
very different quality, and none has been verified here. Naming a slug we have
not checked would be inventing a path. The verifier instead states the
requirements, discovers whatever class folders are present, and reports whether
the result is usable.

### Why this is a separate model and not a retrained one

**ISL fingerspells with two hands. ASL uses one.**

That single fact propagates through the entire pipeline:

| | ASL (Model A) | ISL (Model C) |
|---|---|---|
| Hands tracked | 1 | 2 |
| Feature vector | 63 floats | **126 floats** |
| Normalisation | `normalize_primary_hand` | `normalize_hands` (slotted by handedness) |
| Mirroring | negate x | negate x **and swap hand slots** |
| WebSocket mode | `static` | `isl` |

Model A's weights are not merely less accurate on ISL data — they are the
wrong shape. The backend's input-shape guard refuses to load one into the
other's slot rather than failing later with a confusing TensorFlow error.

Three things in the shared code needed care, and each would have trained
happily while being wrong:

- **Normalisation is per hand.** Each hand is centred on its own wrist and
  scaled by its own furthest landmark. Treating the 42 points as one hand
  would subtract the left wrist from the right hand's landmarks.
- **Mirroring swaps the slots.** The vector is `[left(63), right(63)]` by
  handedness. Negating x without swapping claims the left hand performed the
  right hand's shape — a letter that exists in no alphabet.
- **An absent hand stays exactly zero.** Several ISL letters are one-handed,
  and MediaPipe loses a hand to occlusion constantly. Noise added to a zero
  slot invents a hand that was never there.

`backend/tests/test_isl_preprocessing.py` guards all three, and each test was
verified to fail when its fix is removed.

### Expect a higher discard rate than ASL

Two hands in frame occlude one another, and MediaPipe loses landmarks it would
have found on a single hand. ASL Alphabet — clean, studio-lit, one hand —
already discarded 23.2% overall and 49% for N. ISL will be worse. Extraction
reports the rate per class, and that number is worth reading before training:
if it is very high, hand detection rather than the classifier is the limit.

### Running it

```bash
python ml/scripts/download_datasets.py --dataset isl --verify
python ml/scripts/extract_landmarks_images.py --dataset isl --limit-per-class 1500
python ml/scripts/preprocess.py --dataset isl
python ml/scripts/train_static.py --dataset isl
python ml/scripts/evaluate.py \
    --model ml/models/isl_model.keras --labels ml/models/labels_isl.json \
    --prefix isl_ --report isl_evaluation_report.json \
    --history isl_training_history.json --image-tag _isl
```

ISL arrays are written beside the ASL ones (`X_isl_train.npy` next to
`X_train.npy`), so both models stay reproducible from one extraction run each
and neither overwrites the other.

**No accuracy is claimed here.** The pipeline has been smoke-tested end to end
on synthetic two-handed landmarks — CSV → preprocess → train → the backend
loading and predicting — but no ISL dataset has been trained on. Whatever
number comes out of the run above is the first real one.

---

## Model B — word-level signs (ISL via INCLUDE, or ASL via WLASL)

**This is what "real-time sign language translation" actually needs.** A fluent
deaf signer signs *words*, not letters — fingerspelling is reserved mostly for
proper nouns. An alphabet model watching natural signing produces unrelated
output, not merely worse output.

```bash
python ml/scripts/extract_landmarks_video.py --dataset include   # default
python ml/scripts/preprocess_dynamic.py
python ml/scripts/train_dynamic.py
```

**Dataset (ISL): INCLUDE** — Sridhar et al., ACM Multimedia 2020. ~4,200
clips, 263 words, recorded with deaf students. Academically hosted (Zenodo);
search "INCLUDE Indian Sign Language dataset" rather than trusting a link
copied from here, since these move. `--dataset include` is the default;
`--dataset wlasl` selects the American dataset instead.

### Check a download before committing to it

```bash
python ml/scripts/extract_landmarks_video.py --inspect --raw-dir <your folder>
```

Word-level sign datasets ship in wildly different shapes and the download page
rarely says which. This walks the tree in seconds and reports what is actually
there, so nobody discovers the layout was wrong after a three-hour extraction:

| What it finds | Verdict |
|---|---|
| One folder per word | `--dataset include --raw-dir <folder>` |
| A WLASL-style metadata JSON | `--dataset wlasl` |
| All videos in one folder | Unusable as-is — the word is in the filename, and that scheme has to be added |
| Image frames, not video | Probably an alphabet dataset — use the Model C pipeline instead |

`--raw-dir` also works for real extraction, so a dataset can live anywhere
rather than having to be named `include/`.

**Any folder-per-word video tree works**, not only INCLUDE. Folder names are
cleaned (numbering stripped, lowercased) before becoming labels.

The two datasets are laid out completely differently, so discovery is the only
part that forks:

| | WLASL (ASL) | INCLUDE (ISL) |
|---|---|---|
| Classes from | `WLASL_v0.3.json` | folder names |
| Clip trimming | `frame_start` / `frame_end` | already trimmed |
| Signer identity | **recorded** | **not recorded** |
| Split | signer-disjoint | stratified random (see below) |

Folder names are cleaned before use: INCLUDE numbers its word folders per
category, so `1. hello` and `9. hello` are the same word listed twice, and
keeping the numbers would train two classes nothing could tell apart.

### Word signs need position; letters must not have it

The most instructive bug in this project. Model B was first trained on the same
features the alphabet models use, and scored **79.75%** on 20 ISL words. Its top
confusions were the tell:

| Confusion | Handshape | What actually differs |
|---|---|---|
| bad → good | near-identical | movement direction |
| big large → small little | near-identical | how far the hands travel |
| dry → wet | near-identical | movement |
| they → you (plural) | both pointing | direction |

Every one is a movement pair. The cause was visible in the data itself: the
right-hand wrist read `[0, 0, 0]` in all thirty timesteps, because
`normalize_hands` puts every wrist at the origin. **The feature vector was
literally identical for a hand held still and a hand sweeping across the body.**

That behaviour is correct for fingerspelling and is why the alphabet models
generalise — the letter A is the letter A wherever it is signed. For word signs
it throws away most of the meaning.

`sequence_frame_features` therefore appends each wrist's position, making a
frame **132** floats rather than 126, and `center_sequence_positions` centres
those over the window so that movement survives while where the signer stood
does not. Only word signs use it.

| | Shape only | **+ position** |
|---|---|---|
| Top-1 | 79.75% | **84.81%** |
| Top-3 | 96.20% | **98.73%** |

`big/small`, `they/you` and `dry/wet` disappeared entirely; `bad/good` halved.
The fix was chosen from the confusion table, not guessed at, and the table is
the evidence that it worked.

### Vocabulary size: 40 is a peak, not a ceiling reached

The obvious assumption is that more classes always means lower accuracy. It did
not hold here, and the shape of the curve is the interesting part:

| Vocabulary | Train sequences | Top-1 | Top-3 |
|---|---|---|---|
| 20 words | 1,120 | 84.81% | **98.73%** |
| **40 words** | **2,236** | **89.93%** | 95.97% |
| 70 words | 3,504 | 78.99% | 92.02% |

Going from 20 to 40 words **raised** top-1 by five points. The model was
data-starved, and doubling the vocabulary doubled the training data; that
mattered more than the extra classes cost.

Going from 40 to 70 lost eleven points, and the reason is in the dataset rather
than the model. INCLUDE's clip counts are very uneven: 48 words have 20-21
clips, then it falls off a cliff to 14 and then 8. Words past the fortieth bring
too few examples to learn from while still competing for probability mass, so
they dilute the model instead of enriching it.

**Choose the vocabulary by where the clip counts fall off, not by how many words
sound impressive.** For this dataset that boundary is around 40.

### Bidirectional, chosen on validation

Reading each clip forwards *and* backwards is legitimate here and would not be
for open-ended captioning: by the time a window reaches the model it is a
complete segmented gesture, so nothing waits on future frames.

With only 60 validation samples, one run proves nothing, so the choice was made
on mean validation accuracy across three seeds — then test was measured **once**,
after the decision:

| seed | unidirectional | bidirectional |
|---|---|---|
| 1 | 80.00% | 85.00% |
| 2 | 78.33% | 81.67% |
| 3 | 80.00% | 83.33% |
| **mean** | **79.44%** | **83.33%** |

### A full second of latency, hiding in plain sight

Replaying real test clips through the live path gave correct predictions — at
**965 ms each**. Wrapping an LSTM in a `Masking` layer forces Keras onto its
generic per-timestep path, and eagerly that is one op dispatch per timestep.

| | word model (BiLSTM) | letter model (MLP) |
|---|---|---|
| eager `model(x)` | 1373 ms | 6.2 ms |
| `model.predict()` | 218 ms | 53 ms |
| **`tf.function` compiled** | **18 ms** | **1.74 ms** |

The predictor now compiles one traced graph at load time. This supersedes the
earlier "call the model directly, never `predict()`" rule: that was right for
the MLPs, but only compilation is fast for both.

Nothing in the output would have revealed this. The predictions were correct —
just a second too late to caption anything.

### INCLUDE cannot support a signer-disjoint split, and says so

Model B's strongest claim on WLASL is that its test set holds out entire
*people*. **INCLUDE does not record who signed each clip**, so extraction
stores `signer_id: -1` rather than inventing one, and `preprocess_dynamic.py`
detects that and falls back to a stratified random split — loudly, and with
`signer_disjoint: false` written into the manifest, the model metadata and the
`/health` response.

That flag is the point. Without the fallback the split silently collapses into
a single bucket while every downstream document goes on claiming the strongest
evaluation the project offers. A test guards this: it asserts that unknown
signers *do* collapse, so the day that stops being true the guard is revisited
rather than quietly kept.

### The honest limit for a live demo

Model B is trained on clips **trimmed to one sign**. Live, landmarks arrive as
an unbroken stream and nothing announces where a sign starts. `sequence.py`
applies two heuristics — a run of hand-free frames ends a sign, and a
mostly-empty window is never classified — and neither helps a signer who moves
continuously from one sign into the next.

**For a demo this means: sign one word, drop the hands, sign the next.** That
is a real constraint, not a polish item, and continuous sign segmentation is an
open research problem rather than something to fix before a review.

---

## Model B architecture

Identical for both languages — only the training data and the label list
change, which is the direct benefit of classifying landmarks rather than pixels.

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

### Status: pipeline complete, model not yet trained

Every piece of Model B is written, tested and wired end to end:

| | |
|---|---|
| `extract_landmarks_video.py` | WLASL clips → `(30, 126)` sequences |
| `preprocess_dynamic.py` | signer-disjoint split + sequence augmentation |
| `train_dynamic.py` | the LSTM above, with class weighting |
| `evaluate.py --prefix dyn_` | same metrics and confusion analysis as Model A |
| `backend/app/ml/sequence.py` | live sliding-window buffer |
| `backend/app/ml/predictor.py` | second model instance, same version guard |
| `/ws/predict` `mode: "dynamic"` | routed, with buffering progress reported |
| `RecognitionModeToggle.jsx` | UI switch, disabled when no model is loaded |

**What is missing is the dataset, not the code.** For ISL that is INCLUDE
(<https://zenodo.org/record/4010759>); for ASL, WLASL processed is several
gigabytes and the build brief requires asking before a download that size, so
it has not been fetched. Once it is present, the four commands under "Running
the pipeline" below produce a trained Model B with no further changes.

**No accuracy is reported here, because none has been measured.** The 55–80%
figure above is what the literature reports for comparable WLASL-20 setups, not
a result from this repository. It is an expectation to test, and quoting it as
though it were our own number would be exactly the kind of claim this project
has otherwise avoided.

**The recommendation still stands: demo Model A.** It reaches 90.5% on held-out
data and its live behaviour is good. Model B is the more interesting engineering
story — sequences, masking, signer-disjoint evaluation — and it is worth
presenting as built-and-ready, but a live demo of a 60%-accurate model beside a
90%-accurate one weakens the presentation rather than strengthening it.

### The one thing Model B does better than Model A — on WLASL only

Model A's honest limitation is that ASL Alphabet carries no signer metadata, so
its test split measures "the same hands, later frames".

**WLASL records `signer_id`,** so `preprocess_dynamic.py` splits by holding out
entire people. Its test accuracy therefore answers "will this work for someone
new?" — the question a reviewer actually cares about — rather than "can it
recognise frames near ones it memorised?". Expect a lower number than a random
split would give, and expect the gap to be large. That gap is the measurement
working, not a bug to tune away.

`--split-strategy official` and `--split-strategy random` are provided for
comparison, and the random one is explicitly labelled as leaky.

**None of this applies to INCLUDE**, which records no signer identity — see
"INCLUDE cannot support a signer-disjoint split" above. On ISL data the split
falls back to stratified random and the manifest says so.

### Live inference is harder than the test split, for a structural reason

Model B is trained on **segmented** clips — each one trimmed to a single sign by
WLASL's own frame metadata. Live, landmarks arrive as an unbroken stream and
nothing announces where a sign starts. A sliding window can straddle two signs,
or land on the rest position between them, and the model was shown neither
during training.

Continuous sign segmentation is an open research problem. `sequence.py` applies
the two cheap heuristics that recover most of the benefit — a run of hand-free
frames is treated as a boundary, and a window that is mostly empty is never
classified — and neither helps a signer who moves continuously without pausing.
That limitation is stated rather than papered over.

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

This is implemented **twice**, and that is a deliberate departure from the
original specification, which asked for three implementations (the training
scripts, the backend, and the browser).

Writing the same arithmetic twice in Python would manufacture exactly the drift
the requirement exists to prevent. Instead there is one Python implementation,
`backend/app/ml/normalization.py`, and the training scripts import it. Training
and inference are then identical *by construction* rather than by discipline.

The browser genuinely needs its own copy, in
`frontend/src/utils/landmarkUtils.js`, so that is the one boundary that can
diverge — and it is exactly what
`backend/tests/test_normalization_parity.py` guards, asserting agreement to
`1e-6`. That test was verified to fail: injecting a 0.001% divergence into the
JavaScript makes it fail with a message naming the cause.

`metadata.json` records `"normalization_version": 1`. The backend refuses to
load a model whose version does not match the running code, which turns a stale
model file into a loud startup error rather than a silent accuracy collapse.

---

## Data hygiene rules (enforced in code)

- **Contiguous splits by capture order, never random.** ASL Alphabet images are
  consecutive video frames, so `A1.jpg` and `A2.jpg` are near-identical. A
  random split puts one in train and the other in test and grades the model on
  frames it has effectively memorised. We sort by the number in the filename and
  cut contiguous 70/15/15 blocks, so neighbouring frames stay on the same side.

  The honest limit: the dataset carries no signer metadata, so **no split can
  guarantee an unseen signer in the test set**. Our test accuracy measures "same
  hands, later frames", not "a stranger's hands". `test_realtime.py` is what
  measures the latter.

- **Balance every class down to the smallest.** Classes do not survive
  extraction equally — N loses 49%, F loses 3%. Left alone, the model sees far
  more F than N and its prior tilts accordingly, making the already-hard classes
  harder. Subsampling uses an even stride across capture order rather than the
  first N rows, which would keep only the earliest frames and discard whatever
  variation appeared later.

- **Augment landmark vectors, not images**: rotation (±12°), Gaussian
  coordinate noise (σ=0.015), and horizontal mirroring. Augmenting the images
  instead would mean re-running MediaPipe on every variant — hours of CPU for
  the same effect. Applied to the **training split only**; augmenting validation
  or test data would mean grading the model on data we invented.

- **Scale jitter is deliberately NOT applied.** It would be a mathematical
  no-op: normalisation already divides by the largest distance from the wrist,
  so scaling a sample and re-normalising returns the original vector exactly.
  Scale invariance is guaranteed by the representation, so jittering it teaches
  nothing. Including it would have *looked* like augmentation while doing
  nothing at all.

- **Mirroring is an accessibility feature, not an accuracy trick.** The dataset
  is almost entirely right-handed; mirroring teaches the model left-handed
  signing it would otherwise never see.

- **Write `dataset_manifest.json`** recording source dataset, version, class
  counts, split sizes, augmentation settings, balancing, and extraction date.

---

## Running the pipeline

```bash
source .venv/bin/activate

python ml/scripts/download_datasets.py --verify          # PASS/FAIL per class
python ml/scripts/extract_landmarks_images.py \
       --limit-per-class 3000 --workers 10               # ~13 min, 87k images
python ml/scripts/preprocess.py                          # ~15 s
python ml/scripts/train_static.py                        # ~62 s
python ml/scripts/evaluate.py                            # ~10 s
python ml/scripts/test_realtime.py                       # live webcam check
```

Use `--limit-per-class 500` for a fast pipeline test at lower accuracy.

### Model B (once WLASL is downloaded)

```bash
python ml/scripts/download_datasets.py --dataset dynamic --verify
python ml/scripts/extract_landmarks_video.py --num-glosses 20   # video decode, slow
python ml/scripts/preprocess_dynamic.py                        # signer-disjoint split
python ml/scripts/train_dynamic.py
python ml/scripts/evaluate.py \
    --model ml/models/dynamic_model.keras \
    --labels ml/models/labels_dynamic.json \
    --prefix dyn_ --report dynamic_evaluation_report.json \
    --history dynamic_training_history.json --image-tag _dynamic
```

`extract_landmarks_video.py --dry-run` processes three clips per gloss and
writes nothing, which is the fast way to confirm the dataset is laid out
correctly before committing to a full extraction run.

Note that `evaluate.py` serves both models rather than there being a second
copy of it. The metrics, confusion matrix and failure analysis are identical
between them; only the arrays, labels and output filenames differ, and a
duplicate script would have been a guarantee that the two drift apart.

### What extraction reports, and why it matters

The discard rate — images where MediaPipe found no hand — is a genuine finding,
not an inconvenience:

| | |
|---|---|
| Images processed | 87,000 |
| Landmarks extracted | 66,858 |
| Discarded | 20,142 (**23.2%**) |
| Worst classes | N 49.0%, M 34.8%, `space` 33.9%, `del` 31.9% |
| Best classes | F 3.1%, K 8.6%, J 11.8% |
| `nothing` | **99.5%** — those images contain no hand at all |

Two things fall out of this table. First, `nothing` cannot be a trained class
in a landmark-based system, so the neutral state moved into the pipeline
instead. Second, M and N — the letters the model later confuses most — are
*already* the hardest to extract. The ambiguity is visible in the raw data
before any model sees it.

A separate observation from extracting everything rather than the first 1,500
per class: the discard rate rose from 14.0% to 23.2%. The later images in each
folder are systematically harder, which suggests hand position drifts or blur
increases through each capture session. More data was not uniformly better
data.
