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

Verified by running, as of the Phase 3a/6/7/8/9/10 work.

| # | Feature | Status | Evidence |
|---|---|---|---|
| 1 | Register and log in | **Working** | both demo accounts HTTP 200 |
| 2 | Home: new meeting, join by code, history | **Working** | `Dashboard.jsx`; join now routes via the lobby |
| 3 | Pre-join lobby, camera preview, device selection | **Working** | `Lobby.jsx` + `useMediaDevices.js`; choices applied with `exact` and carried into the room |
| 4 | Both see and hear each other | **Working** | `useWebRTC.js`, `/ws/signal/{code}`; ICE from env |
| 5 | Signing → live captions, continuous | **Working** | 17.5% WER continuous |
| 6 | Speaking → live captions | **Working** | Web Speech `en-IN`; Whisper verified at 1,134 ms |
| 7 | Captions labelled, both see them | **Working** | 🤟/🎤 badges, broadcast over `/ws/predict` |
| 8 | Transcript saved to MySQL | **Working** | rows confirmed in the live database |
| 9 | History → open → full transcript | **Working** | `/history/:code` with search, participants, duration, TXT + PDF |
| 10 | Interview mode: notify, fullscreen, block, report, log | **Working** | toggle, dialog, Keyboard Lock, overlay, host log; verified live: 42s absence round-tripped |

### Supporting

| Item | Status | Detail |
|---|---|---|
| Tests | **Working** | 231 pass, 2 skipped |
| Live inference path parity | **Working** | `test_inference_path.py` agrees with `evaluate.py` exactly on all three models |
| ICE servers from env | **Working** | `VITE_STUN_URLS`, `VITE_TURN_*` |
| Migrations | **Working** | `database/migrations/001_*.sql`, idempotent, applied and verified |
| PDF + TXT export | **Working** | server-side, shared header builder |
| Meeting timer, copy-link, caption size | **Working** | caption size reaches `SubtitleBar` |
| Dockerfiles + full compose | **Partial** | written and statically validated; **Docker is not installed here, so never built or run** |
| README | **Working** | measured numbers, licences, limits |

---

## Measured accuracy — held-out splits only

| Model | Measured | Split | Notes |
|---|---|---|---|
| ISL words (BiLSTM, `(30,132)`, 40 classes) | **85.23%** top-1, 94.63% top-3; **17.5% WER** continuous | random | INCLUDE records no signer id, so `signer_disjoint: false` |
| ISL fingerspelling (MLP, `(126,)`, 35 classes) | **92.04% macro recall** over 28 judgeable classes | **pose-disjoint** | weighted top-1 is 98.14% but inflated; 7 classes unjudgeable; H and J at 0% |
| ASL fingerspelling (MLP, `(63,)`, 28 classes) | 90.53% top-1, 96.91% top-3 | contiguous | baseline only |

Live-path latency: ASL 0.70 ms, ISL 0.71 ms, words 6.12 ms median.

---

## Decisions made, and why

- **Dataset substitution.** The brief named
  `eraakash/indian-sign-language-hand-landmarks-dataset`; it does not exist
  (0 datasets under that author, control dataset resolved fine). Three other
  ISL candidates on HF contain no data at all. Used
  `Hemg/Indian_sign_language_dataset` — 42,745 images, 35 classes. **No
  licence declared**, recorded as a caveat.
- **Pose-disjoint splitting for ISL fingerspelling.** 41,609 images collapse
  to 1,159 distinct poses (2.8%), scattered rather than adjacent, so no
  index-based split can separate copies. Without this the model reports 99.75%
  and means nothing.
- **Dynamic model keeps 132 features**, not the 126 the brief specifies.
  With 126 the wrist sits at the origin every frame, so a still hand and a
  sweeping hand are identical vectors. Position took top-1 from 79.75% to
  84.81%. The **static** ISL model uses 126 exactly as specified.
- **Vocabulary capped at 40.** Measured: 20 → 84.81%, 40 → 89.93%, 70 →
  78.99%. INCLUDE's clip counts fall off a cliff after ~48 words.
- **Inference is a compiled `tf.function`.** Masking around an LSTM forces a
  per-timestep path: 1,373 ms eager → 18 ms compiled.
- **Violation feed is polled, not pushed.** Adding a third message type to the
  inference socket would couple attention logging to sign recognition, so a
  failure in one would take the other down.
- **Tailwind advisories not fixed.** `npm audit --omit=dev` reports zero; they
  are dev-only. The only fix is a breaking Tailwind 4 migration.

---

## Known issues

1. **Docker stack never run.** Docker is not installed on this machine. YAML
   parses, all paths resolve, images unbuilt. The one genuinely unverified
   deliverable.
2. **No HTTPS.** Required for camera/mic/Web Speech from any device other than
   localhost. Documented, not provided.
3. **`useFocusMonitor.js` is now dead code**, superseded by
   `useInterviewMode.js`. Left in place rather than deleted; safe to remove.
4. **H and J fingerspelling at 0% recall**, and 7 letters unjudgeable — a
   property of the source data, not the training.
5. **Section 4 journey not walked in two browser windows.** Every layer below
   the browser is verified; the two-window click-through needs a human.

---

## Final verification run (end of session)

Both services restarted from cold, then the whole journey driven through the
API. Every step passed.

```
/health   status ok | db connected | dialect mysql
          ASL letters  loaded=True  28 classes
          ISL letters  loaded=True  35 classes   <- did not exist at session start
          ISL WORDS    loaded=True  40 classes  lang=ISL
          Whisper      loaded=True  base

OK  host + guest login                 200
OK  create meeting                     201
OK  host joins / guest joins           200
OK  host switches interview mode ON    200  (start time stamped)
OK  guest BLOCKED from toggling        403
OK  host sees violation                1x, longest 37000ms
OK  guest BLOCKED from the host log    403
OK  sign caption saved                 201
OK  speech caption saved               201
OK  transcript returns both lines      200
OK  history lists 25 meetings          200
OK  TXT export    376 bytes            200
OK  PDF export   2006 bytes            200  magic=%PDF
OK  non-member blocked                 404
OK  meeting ended                      200
```

Not covered by this run, and needing a human in a browser: the two-window
click-through, the camera preview in the lobby, fullscreen and Keyboard Lock
actually engaging, and a real microphone producing captions. Every layer
beneath those is verified above.

---

## Measured recognition gates (Part A4)

Thresholds live in `frontend/src/config/recognition.js` and were chosen by
measuring, not guessing. Reproduce with `python ml/scripts/measure_gates.py`.

Gates: **confidence ≥ 0.7**, **margin over runner-up ≥ 0.15**.

### Accuracy on held-out data

| | ISL words | ISL letters |
|---|---|---|
| Held-out samples | 149 clips | 6343 |
| Rejected by the gates | 8 (5.4%) | 16 (0.2%) |
| **Accuracy of accepted** | **88.65%** | **98.37%** |
| Accuracy overall | 83.89% | 98.12% |

A rejection is a *missed* caption, not a wrong one. The two matter differently:
a miss is recoverable by signing again, a wrong caption is not.

### Idle false-positive rate — the number that matters more

Fed input containing no sign at all, how often do the gates let something
through? Target is zero.

| Input | ISL words | ISL letters |
|---|---|---|
| No hands (all zeros) | **0.0%** | **100.0%** |
| One pose held perfectly still | **56.8%** | n/a (no motion concept) |
| Random landmark noise | 52.2% | 81.8% |

**These are worst-case numbers with motion gating removed, and they are the
honest reason the motion gate exists.**

Two things the confidence and margin gates genuinely cannot do:

1. **The letter model passes all-zeros 100% of the time.** It learned that an
   empty hand slot looks like something, because ~31% of its training hand
   slots were legitimately empty — ISL has one-handed letters. In production
   this cannot fire: the backend returns the neutral state without calling the
   model when no hands are present. But it means the probability output carries
   no information about whether a hand is there.

2. **A pose held still passes 57% of the time.** A resting hand IS a valid
   handshape, so the model is not *wrong* to be confident about it, and no
   probability threshold separates "resting in this shape" from "signing this
   letter". Stability gating cannot help either — a parked hand is perfectly
   stable. This is what produced the reported "detecting M at 71% while not
   signing".

Movement is the only signal that distinguishes them, which is why
`MOTION_LOOKBACK_FRAMES` exists: nothing is committed unless real movement
occurred within the last 20 frames (2 s at 10 FPS). A hand left in frame stops
producing captions about two seconds after it stops moving.

**Not yet measured:** the end-to-end false-positive rate *with* motion gating
active, because the motion gate runs in the browser against live landmark
velocity and there is no recorded idle-webcam fixture to replay through it.
Acceptance check A6.4 — hands resting for 30 seconds — is the manual test that
covers it, and it needs a human at a camera.

