# BridgeTalk — PROGRESS

> **Purpose.** A new session must be able to resume from this file alone.
> Status is assigned by **running the code**, not by reading the README.
> Last updated: Phase 0 audit, 2026-10-04.

---

## Detected stack

| Layer | Detected | Version |
|---|---|---|
| Frontend | React + Vite + Tailwind | React 18, Vite 7.3.6 |
| Backend | FastAPI + Uvicorn | Python 3.11 |
| Hand tracking | `@mediapipe/tasks-vision` HandLandmarker (browser, WASM) | — |
| ML | TensorFlow / Keras | TF 2.16.2, numpy 1.26.4 |
| Speech (primary) | Web Speech API | browser |
| Speech (fallback) | faster-whisper `base`, int8, CPU | 1.0.3 / ctranslate2 4.8.1 |
| Audio decode | ffmpeg | 9.0.1 |
| Database | MySQL 8 via SQLAlchemy 2.0.36 | **Unix socket, not TCP 3306** |
| Auth | JWT (python-jose) + passlib/bcrypt | — |
| Ports | backend `:8000`, frontend `:5173` | both verified up |

Repo: 28 commits, branch `client`, remote `origin` → `github.com/swarnaangusamy/BridgeTalk.git`.
Working tree clean. **220 tests pass, 2 skipped** (`pytest backend/tests`).

> **MySQL gotcha:** `mysqladmin ping` and `lsof -iTCP:3306` both return empty
> because MySQL listens on a **Unix socket**. The SQLAlchemy connection the
> backend actually uses was tested and works. Do not read the empty `lsof` as
> "MySQL is down".

---

## Database schema (current)

Five tables in `database/schema.sql`, all present in the live database:

| Table | Key columns |
|---|---|
| `users` | id, name, email (unique), password_hash, role, created_at |
| `meetings` | id, code (unique), title, host_id, **is_interview_mode**, started_at, ended_at, created_at |
| `meeting_participants` | id, meeting_id, user_id, joined_at, left_at — a log, not a set |
| `transcripts` | id, meeting_id, user_id, source (`sign`/`speech`), content, confidence, created_at |
| `focus_events` | id, meeting_id, user_id, event_type (`blur`/`hidden`/`return`), created_at |

**Schema gaps for later phases:** `focus_events` has no `duration_away`
column, and there is no violation-count or removal state.

---

## Trained models on disk

| Model | File | Features | Classes | Measured accuracy | How measured |
|---|---|---|---|---|---|
| **ISL words** (dynamic, BiLSTM) — *the demo model* | `dynamic_model.keras` | `(30, 132)` | 40 + 1 internal | **85.23% top-1**, 94.63% top-3 on 149 held-out clips; **17.5% WER** continuous | `evaluate.py` + `evaluate_continuous.py` on a held-out split |
| ASL letters (static, MLP) — baseline only | `static_model.keras` | `(63,)` | 28 | **90.53% top-1**, 96.91% top-3 on 6,440 held-out samples | `evaluate.py` |
| **ISL fingerspelling** (static, MLP) | — | `(126,)` | — | **NEVER TRAINED** | no dataset was available |
| Whisper | `ml/models/whisper/` (141 MB) | — | — | not an accuracy metric; 1,061 ms for 2.8 s audio | real speech through `/ws/transcribe` |

**Note on the dynamic feature width:** the spec says 126 (2 hands × 63). Our
dynamic model uses **132** = 126 shape + 6 wrist-position values. This was a
measured improvement, not a deviation for its own sake: with 126 the wrist sits
at the origin in every frame, so a hand held still and a hand sweeping across
the body produce an identical vector. Adding position took top-1 from 79.75% to
84.81% and removed every movement-pair confusion (bad/good, big/small,
dry/wet). The **static** ISL model will use 126 exactly as specified.

---

## Status table — Section 4 definition of done

| # | Feature | Status | Detail |
|---|---|---|---|
| 1 | Register and log in | **Working** | `/api/auth/register`, `/login/json`; both demo accounts return HTTP 200 |
| 2 | Home: new meeting, join by code, past meetings | **Working** | `Dashboard.jsx` creates + joins; `History.jsx` lists |
| 3 | Pre-join lobby: camera/mic preview + device selection | **Missing** | no `enumerateDevices` anywhere in `frontend/src` |
| 4 | Both participants see and hear each other | **Working** | `useWebRTC.js`, signalling over `/ws/signal/{code}` |
| 5 | Signing produces live captions, continuously, no button | **Working** | ISL word model, 17.5% WER continuous; `__transition__` class handles boundaries |
| 6 | Speaking produces live captions | **Working** | Web Speech `en-IN` primary; Whisper fallback loaded and verified |
| 7 | Captions labelled by speaker + source, seen by both | **Working** | `SubtitleBar.jsx` 🤟/🎤 badges; broadcast over `/ws/predict` |
| 8 | Transcript saved to MySQL on meeting end | **Working** | rows confirmed in live DB |
| 9 | History shows meeting, opening it shows full transcript | **Partial** | list only. **No detail view, no transcript page, no search.** TXT download works |
| 10 | Interview mode: notify, hold fullscreen, block, report, log | **Partial** | detection + DB logging only. **No** host toggle mid-meeting, blocking dialog, fullscreen, Keyboard Lock, overlay, host alert, violation count, removal, or duration-away |

### Supporting items

| Item | Status | Detail |
|---|---|---|
| Automated tests | **Working** | 220 pass, 2 skipped |
| `/health` endpoint | **Working** | reports DB + all 4 model slots |
| `.env` / `.env.example` / `.gitignore` | **Working** | covers `.env`, `node_modules`, `.venv`, `dist`, `ml/data/raw`, `__pycache__` |
| Models load once at startup | **Working** | 4 `.load()` calls in `main.py` lifespan |
| CORS from env | **Working** | `cors_origins` in `config.py` |
| STUN/TURN from env | **Partial** | **hardcoded** Google STUN in `useWebRTC.js:32`; spec requires env vars |
| `docker-compose.yml` | **Partial** | **MySQL only.** No backend/frontend services |
| `Dockerfile` (backend, frontend) | **Missing** | none exist |
| PDF transcript export | **Missing** | only the word "PDF" in a comment explaining why TXT was chosen |
| Meeting timer, copy-link, caption-size control | **Missing** | no matches in `MeetingRoom.jsx` or components |
| `PROGRESS.md` | **Working** | this file |

---

## Phase 0 blocker: the specified dataset does not exist

The brief names `eraakash/indian-sign-language-hand-landmarks-dataset` on
Hugging Face as the training dataset. **It does not exist.** Verified:

- `GET /api/datasets/eraakash/indian-sign-language-hand-landmarks-dataset`
  → `Invalid username or password` (private, gated, or absent)
- `GET /api/datasets?author=eraakash` → **0 datasets**
- The network and the HF API both work — a public control dataset resolved fine

So the ISL fingerspelling model still has no specified source. Searched HF and
evaluated every ISL candidate:

| Dataset | Contents | Verdict |
|---|---|---|
| `LIGHTscrn/Indian-Sign-language-landmarks-30frames` | **only `.gitattributes`** — empty repo | unusable |
| `ajeet-123/Indian_Sign_Language` | README only, no data | unusable |
| `KRISH09bha/Hindi-Indian-Sign-language-dataset-ISL` | README only, no data | unusable |
| **`Hemg/Indian_sign_language_dataset`** | **42,745 images, 35 classes** (1–9, A–Z), 259 MB | **chosen** |
| `akritRihal/Indian_Sign_Language_dataset` | 9,139 train + 1,613 test, 33 classes, 578 MB | backup |

**Decision: use `Hemg/Indian_sign_language_dataset`.** Reasons: most images per
class (~1,221), smallest download, and 35 classes matches ISL fingerspelling
(9 digits + 26 letters). It is images, not landmarks — which is fine, because
`extract_landmarks_images.py --dataset isl` already converts images to
two-handed 126-feature vectors and that path is covered by 11 tests.

**Honest caveat:** neither usable dataset declares a licence. They are publicly
downloadable, which satisfies the dataset-only rule, but "no licence stated"
must be recorded in the README rather than implying permissive terms.

---

## Ordered plan

1. **Phase 1** — ICE servers to env vars (the one real Phase 1 gap).
2. **Phase 3a** — download `Hemg`, extract 126-feature landmarks, train and
   evaluate the **ISL fingerspelling model**. This completes the two-model
   design and is the largest single gap.
3. **Phase 3b** — movement-based arbitration between static and dynamic models.
4. **Phase 6** — history detail page: transcript view, search, PDF export.
5. **Phase 7** — interview mode in full: toggle, dialog, fullscreen, Keyboard
   Lock, overlay, host alerts, violation count, `duration_away` migration.
6. **Phase 8** — lobby with device selection; timer, copy-link, caption size.
7. **Phase 9** — tests for the new surfaces; held-out inference-path script.
8. **Phase 10** — Dockerfiles, compose with all three services, README.

Phases 2, 4 and 5 are already **Working** and will be left alone.

---

## Decisions made, and why

- **Dynamic model keeps 132 features**, not 126. Position was worth 5 points of
  accuracy and removed the movement-pair confusions. Static ISL uses 126.
- **Vocabulary capped at 40 words.** Measured: 20 → 84.81%, 40 → **89.93%**,
  70 → 78.99%. INCLUDE's clip counts fall off a cliff after ~48 words, so thin
  classes dilute the model. Current 85.23% is after adding the boundary class.
- **Inference is a compiled `tf.function`**, not eager and not `.predict()`.
  Masking around an LSTM forces a per-timestep path: 1,373 ms eager → 18 ms
  compiled. Correct predictions arriving a second late are unusable.
- **`signer_disjoint: false` everywhere.** INCLUDE records no signer identity,
  so the test split holds out *clips*, not *people*. No number here claims
  signer independence.
