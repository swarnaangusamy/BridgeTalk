# BRIDGETALK — MASTER BUILD PROMPT (Claude Code / Opus) — v2

> Copy everything below this line into Claude Code as your first message in an empty project folder.

---

You are acting as a **senior full-stack + ML engineer and technical mentor**. You are building a working, demoable MVP of an academic project called **BridgeTalk**, and simultaneously writing documentation good enough that two MCA students who did not write the code can fully understand, run, modify and defend it in a college review.

Treat this as a real engineering project, not a code snippet dump. Build it end to end.

---

## 0. PROJECT CONTEXT

**Project title:** BridgeTalk — AI-Assisted Real-Time Communication Platform for Deaf and Hearing Individuals
**Course:** MCA Mini Project, PSG College of Technology, Department of Computer Applications
**Team:** Swarna Rathna A, Thamizhthilaga S D S
**Guide:** Dr. R. Manavalan

**The problem being solved:** Video conferencing platforms (Zoom, Google Meet, Teams) support speech-to-text captions, so a deaf user can read what a hearing user says. But there is no reverse channel — a hearing user cannot understand sign language without a human interpreter. BridgeTalk closes that loop by translating sign language into text in real time inside a video-calling platform.

**What this build must deliver:** A working **Sign Language → Text real-time translation MVP**, running in the browser, with the full application skeleton (auth, meetings, database, live subtitles, transcripts) around it. This is being demonstrated at a **first project review**, so it must actually run on a laptop with a standard webcam, in average indoor lighting, without a GPU.

---

## 1. NON-NEGOTIABLE GROUND RULES

1. **Do not stub anything.** Every file you create must contain real, working code. No `# TODO: implement this`, no placeholder functions, no fake data returned from an endpoint that pretends to be a model.
2. **Build in phases** (defined in Section 5). After each phase, actually run the code (`npm run dev`, `uvicorn`, `python train.py`, etc.), show me the output, confirm it works, and only then move to the next phase.
3. **Explain as you go.** Before each phase, write 3–6 lines telling me *what* you are about to build and *why* that design choice was made. I need to be able to defend these decisions to my project guide.
4. **Comment the non-obvious.** Especially in the ML code, the MediaPipe code, and the WebSocket code. Assume the reader knows Python and JavaScript but has never touched TensorFlow, MediaPipe, or WebRTC.
5. **Pin versions.** Put exact versions in `requirements.txt` and `package.json`. Version drift is the #1 reason student projects break the day before a review.
6. **Git discipline.** Run `git init` at the start. Make one clear commit at the end of every phase with a descriptive message.
7. If a design decision has a real trade-off, **tell me the trade-off** instead of silently picking one.
8. **Models are trained from public datasets only.** See Section 6 — this is a hard constraint, not a preference.
9. **Never invent credentials, dataset paths, or file locations.** If you need something from me, stop and use the handoff protocol in Section 2.
10. Ask me before installing anything larger than ~500 MB or anything that requires a GPU.

---

## 2. WHEN YOU NEED SOMETHING FROM ME — HANDOFF PROTOCOL

There are points in this build where you cannot proceed without me doing something manually: downloading a dataset, giving you a MySQL password, downloading MediaPipe model assets. **Do not guess, do not fabricate a path, and do not skip ahead.**

When you hit one of these points, stop and print a block in exactly this format:

```
╔══════════════════════════════════════════════╗
║  ACTION REQUIRED FROM YOU                    ║
╚══════════════════════════════════════════════╝

WHAT I NEED:      <one line>
WHY I NEED IT:    <one line — which phase/file is blocked>
ESTIMATED TIME:   <e.g. 10 minutes, ~1.2 GB download>

STEPS:
  1. <exact, copy-pasteable step>
  2. <...>
  3. <...>

EXPECTED RESULT:
  <exact folder structure / file names / approximate sizes>

VERIFY IT WORKED — run this and paste me the output:
  <a single command that proves it succeeded>

TROUBLESHOOTING:
  - <likely failure> → <fix>
  - <likely failure> → <fix>

I will wait here until you confirm.
```

Then **actually wait**. Do not continue to the next file.

Write these blocks assuming I have never used the tool before. For Kaggle, that means explaining how to make an account, where the API token lives, and where `kaggle.json` must be placed on Windows vs macOS/Linux — not just the download command.

**Credentials specifically:** I will give you my MySQL Workbench root password when you ask for it. Ask for it in Phase 1 using the block above. Put it only in `.env` (which must be gitignored), never in `.env.example`, never in a Python file, never in a commit, and never echoed back into the terminal in a command I would have to paste publicly. `.env.example` gets `DB_PASSWORD=your_password_here`.

---

## 3. TARGET ENVIRONMENT

- OS: Windows / macOS / Linux (write cross-platform code and cross-platform run scripts)
- Python: **3.11** (TensorFlow-compatible; do not use 3.13)
- Node.js: **20 LTS or newer**
- Database: **MySQL 8.x**, running locally via MySQL Workbench. Connect through a `DATABASE_URL` in `.env` using SQLAlchemy, so switching to SQLite for a quick demo is a one-line change. Document both.
- No GPU. Every model must train on CPU in **under 30 minutes**.
- Editor: VS Code.

---

## 4. TECHNOLOGY STACK (locked — matches our approved SRS, do not substitute)

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18 + Vite + Tailwind CSS | UI: login, dashboard, meeting room, subtitles, transcripts |
| Hand tracking | MediaPipe Tasks Vision (`@mediapipe/tasks-vision`, HandLandmarker) | Extracts 21 hand landmarks per hand **in the browser** |
| Backend | FastAPI (Python) + Uvicorn | REST APIs + WebSocket inference endpoint |
| ML | TensorFlow / Keras | Sign gesture classification from landmarks |
| Image/video processing | OpenCV | Offline landmark extraction from dataset images and videos |
| Real-time transport | WebSockets (FastAPI native) | Landmark stream in, predicted text out, subtitle broadcast |
| Video/audio call | WebRTC (peer-to-peer, backend as signalling server) | 1:1 meeting |
| Speech-to-Text | Web Speech API (browser-native, primary), Whisper documented as fallback | Hearing user's speech → captions for deaf user |
| Database | MySQL 8 via SQLAlchemy | users, meetings, participants, transcripts |
| Auth | JWT (python-jose) + passlib/bcrypt | Login, protected routes, protected meetings |

**Architectural note to respect:** MediaPipe runs **client-side**. Only the 21×3 landmark coordinates (a few hundred bytes) are sent to the backend — never raw video frames. This is a core selling point of our design and must be visibly true in the code. Say so in the README.

---

## 5. REPOSITORY STRUCTURE

Create exactly this structure. Create every directory, even if some are only populated in later phases (use `.gitkeep`).

```
bridgetalk/
├── README.md                      ← the big learning document (see Section 12)
├── ARCHITECTURE.md
├── REVIEW_DEMO.md                 ← demo script + viva Q&A (see Section 13)
├── CLAUDE.md                      ← project context for future Claude Code sessions
├── .gitignore
├── .env.example
├── docker-compose.yml             ← MySQL only, optional convenience
│
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app, CORS, router registration
│   │   ├── config.py              # pydantic-settings, reads .env
│   │   ├── database.py            # SQLAlchemy engine + session
│   │   ├── models/                # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── meeting.py
│   │   │   └── transcript.py
│   │   ├── schemas/               # Pydantic request/response schemas
│   │   ├── api/
│   │   │   ├── auth.py            # register, login, me
│   │   │   ├── meetings.py        # create, join, list, history
│   │   │   └── transcripts.py     # fetch/export transcript
│   │   ├── ws/
│   │   │   ├── inference.py       # WS: landmarks in → predicted text out
│   │   │   ├── signaling.py       # WS: WebRTC offer/answer/ICE relay
│   │   │   └── connection_manager.py
│   │   ├── ml/
│   │   │   ├── predictor.py       # loads .keras model, runs inference
│   │   │   ├── normalization.py   # SHARED landmark normalisation logic
│   │   │   └── smoothing.py       # temporal smoothing + sentence assembly
│   │   └── core/
│   │       ├── security.py        # JWT create/verify, password hashing
│   │       └── deps.py            # get_current_user dependency
│   ├── requirements.txt
│   └── tests/
│
├── ml/
│   ├── data/
│   │   ├── raw/                   # downloaded datasets (gitignored)
│   │   └── processed/             # extracted landmark .npy / .csv files
│   ├── scripts/
│   │   ├── download_datasets.py       # Kaggle API automation + verification
│   │   ├── extract_landmarks_images.py# image dataset → landmark vectors
│   │   ├── extract_landmarks_video.py # video dataset → landmark sequences
│   │   ├── preprocess.py              # normalise, augment, split
│   │   ├── train_static.py            # MLP for static/fingerspelling signs
│   │   ├── train_dynamic.py           # LSTM/GRU for motion-based word signs
│   │   ├── evaluate.py                # accuracy, confusion matrix, per-class report
│   │   ├── test_realtime.py           # OpenCV webcam sanity check of trained model
│   │   └── record_eval_clip.py        # OPTIONAL: record a clip to TEST the model
│   ├── models/                    # saved .keras + labels.json + metadata.json
│   ├── notebooks/                 # optional exploration
│   └── README.md                  # ML-specific deep dive
│
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Login.jsx
│   │   │   ├── Register.jsx
│   │   │   ├── Dashboard.jsx
│   │   │   ├── MeetingRoom.jsx    # the main screen
│   │   │   └── History.jsx
│   │   ├── components/
│   │   │   ├── VideoTile.jsx
│   │   │   ├── SubtitleBar.jsx
│   │   │   ├── TranscriptPanel.jsx
│   │   │   ├── SignDetectionPanel.jsx   # live prediction + confidence bar
│   │   │   ├── HandOverlayCanvas.jsx    # draws the 21 landmarks
│   │   │   └── ModeSwitch.jsx           # Interview Mode toggle
│   │   ├── hooks/
│   │   │   ├── useHandLandmarker.js  # MediaPipe lifecycle
│   │   │   ├── useSignSocket.js      # WS to inference endpoint
│   │   │   ├── useSpeechToText.js    # Web Speech API
│   │   │   ├── useWebRTC.js
│   │   │   └── useFocusMonitor.js    # Interview Mode
│   │   ├── services/api.js
│   │   ├── context/AuthContext.jsx
│   │   └── utils/landmarkUtils.js    # MUST mirror backend normalization.py
│   ├── public/models/                # MediaPipe .task + wasm assets
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
│
├── database/
│   ├── schema.sql
│   └── seed.sql
│
├── docs/
│   ├── images/                    # confusion matrices, diagrams, screenshots
│   └── api.md
│
└── scripts/
    ├── setup.sh / setup.bat
    ├── run_backend.sh / .bat
    └── run_frontend.sh / .bat
```

---

## 6. DATASETS — READ THIS ENTIRE SECTION BEFORE PHASE 3

### 6.0 HARD CONSTRAINT

**All model training must use publicly available datasets.** We are not recording our own gesture data to train the model. Do not build a training-data collection tool, do not ask me to perform signs into a webcam to create training samples, and do not silently fall back to self-recorded data if a dataset turns out to be difficult.

The only permitted webcam scripts are:
- `test_realtime.py` — runs the **already-trained** model live so we can see it working.
- `record_eval_clip.py` — records a short clip purely for **evaluating** the trained model.

Neither of these produces training data. Label them clearly in the code and in the README.

**If, and only if, you reach a point where you genuinely believe the public-dataset path cannot produce a usable model,** stop and tell me directly using the ACTION REQUIRED block from Section 2. Explain what you tried, what accuracy you got, why it is insufficient, and what recording our own data would involve — exact number of samples per class, how long it would take, and exactly what script and commands we would run. I will make that call, not you.

### 6.1 Model A — Static fingerspelling (REQUIRED, primary deliverable)

**Dataset: ASL Alphabet** — Kaggle `grassknoted/asl-alphabet`
- ~87,000 images, 200×200 px, 29 classes: A–Z plus `space`, `delete`, `nothing`
- ~1.1 GB download
- Recognises static handshapes, so a single-frame MLP is the right model

Pipeline (`extract_landmarks_images.py`):
1. Walk class folders with OpenCV.
2. Run MediaPipe HandLandmarker in IMAGE mode on each image.
3. Discard images where no hand is detected, and **report the discard rate per class** — this is a genuine finding worth mentioning in the review.
4. Normalise per Section 8.3 and write `ml/data/processed/static_landmarks.csv` with a `label` column.
5. Support `--limit-per-class` (default 1500) so extraction takes minutes rather than hours and classes stay balanced.
6. Show a tqdm progress bar and print a final per-class count table.

Expected outcome: **92–98% validation accuracy.** This model alone is a complete, defensible MVP.

### 6.2 Model B — Dynamic word signs (STRETCH — attempt after Model A works)

Word-level sign language is much harder from public data. Attempt it in this order and report honestly.

**Option 1 (preferred): WLASL processed** — Kaggle `risangbaskoro/wlasl-processed`
- Word-Level American Sign Language, ~2,000 glosses in video form
- Use the **WLASL-20 subset**: pick the 20 glosses with the most video samples
- Run MediaPipe in VIDEO mode over each `.mp4`, sample/pad to 30 frames, extract both-hand landmarks → `(30, 126)` sequences
- **Split by signer where the metadata allows it**, so the model is not just memorising individuals
- Cite the WLASL paper (Li et al., WACV 2020) in the README; the dataset is licensed for research use

**Option 2 (fallback): Google Isolated Sign Language Recognition** — Kaggle competition `asl-signs`
- 250 signs, **already in MediaPipe landmark format** (parquet), so no extraction step
- Full download is ~55 GB, which is impractical — use the Kaggle API's single-file download to pull `train.csv` plus only the parquet files for a chosen 20-sign subset
- If you take this route, write the subset-selection script and explain the file-by-file download clearly in an ACTION REQUIRED block

**Be upfront with me about expected results.** On CPU, with 20 glosses from WLASL, realistic validation accuracy is roughly **55–80%**, and live webcam performance will be worse than that because our lighting, camera and framing differ from the dataset's. That is a well-known and publishable limitation, not a failure — document it properly in the README's failure-analysis section rather than hiding it.

**Decision rule:** if Model B's live behaviour is too unstable to demo, ship the MVP with Model A as the live demo and present Model B's metrics as documented work-in-progress. Tell me which path you are recommending and why.

### 6.3 Dataset acquisition — what you must give me

Before writing any extraction code, produce an ACTION REQUIRED block per Section 2 covering:
- Creating a Kaggle account and accepting each dataset's terms (WLASL and competition datasets require explicit acceptance on the site — this trips people up)
- Generating the API token and where `kaggle.json` goes: `C:\Users\<you>\.kaggle\kaggle.json` on Windows, `~/.kaggle/kaggle.json` on macOS/Linux, with `chmod 600` on Unix
- The exact `kaggle datasets download` / `kaggle competitions download` commands, with the `-p ml/data/raw` output path
- The browser-download alternative, in case the API is blocked on college Wi-Fi, including exactly where to unzip
- The exact folder structure I should see afterwards, with approximate sizes
- A verification command (`python ml/scripts/download_datasets.py --verify`) that checks paths, counts files per class, and prints PASS/FAIL

Also write `download_datasets.py` to automate this where possible and to fail with a clear, human-readable message — never a raw traceback — when the token is missing or terms have not been accepted.

### 6.4 Data hygiene rules (enforce in code)
- Split by **source file/signer, never by frame** — frames from one image folder or video must not leak across train/val/test. Use 70/15/15 stratified.
- Keep the `nothing` class from ASL Alphabet as the neutral class. Without it the model confidently classifies random hand positions as letters.
- Augment landmark vectors, not images: small random rotation, scale jitter, Gaussian coordinate noise, and horizontal mirroring with handedness swapped.
- Write `dataset_manifest.json` recording source dataset, version, class counts, split sizes, augmentation settings, and extraction date.

---

## 7. BUILD PHASES

Work through these in order. **Verify each phase runs before starting the next.** State the acceptance criteria result explicitly.

### Phase 0 — Scaffold & documentation skeleton
Full folder tree, `.gitignore`, `.env.example`, `CLAUDE.md`, `git init`. Write `setup.sh`/`setup.bat` that creates the Python venv, installs `requirements.txt`, and runs `npm install`.
**Acceptance:** structure listing shown; setup script runs clean.

### Phase 1 — Backend foundation + database + JWT auth
- **First, issue the ACTION REQUIRED block asking for my MySQL password**, plus the exact SQL to create the `bridgetalk` database and user in MySQL Workbench. Wait for my reply before continuing.
- FastAPI app with CORS for `http://localhost:5173`, `/health` endpoint.
- SQLAlchemy models + `database/schema.sql` matching them.
- `POST /api/auth/register`, `POST /api/auth/login` (returns JWT), `GET /api/auth/me`. Bcrypt hashing, HS256 JWT with expiry, secret from `.env`.
**Acceptance:** register + login + `/me` with the token via curl, with real terminal output shown; rows visible in Workbench.

### Phase 2 — Meetings & transcripts API
- `POST /api/meetings` (returns a short human-typable code), `POST /api/meetings/{code}/join`, `GET /api/meetings/history`, `GET /api/meetings/{code}`.
- `POST /api/transcripts`, `GET /api/transcripts/{meeting_id}`, `GET /api/transcripts/{meeting_id}/export` (`.txt` download).
- All routes protected by `get_current_user`.
**Acceptance:** full flow demonstrated via curl; rows visible in MySQL.

### Phase 3 — Dataset acquisition & landmark extraction
- Issue the dataset ACTION REQUIRED block (Section 6.3) and wait.
- Then build and run `download_datasets.py`, `extract_landmarks_images.py`, `preprocess.py`.
**Acceptance:** `ml/data/processed/` contains real files; you print per-class counts, discard rates and array shapes.

### Phase 4 — Model training
- Train Model A. Save `.keras` + `labels.json` + `metadata.json` (input shape, normalisation version, class names, val accuracy, source dataset, date).
- Run `evaluate.py`: classification report + confusion matrix saved to `docs/images/`.
- Run `test_realtime.py` — a standalone OpenCV window proving the model works live **before any web integration exists**. Do not skip this; it is how you isolate model bugs from plumbing bugs.
- Then attempt Model B per Section 6.2, and report your recommendation.
**Acceptance:** honest accuracy numbers reported. If Model A is below 85%, diagnose and fix before proceeding rather than papering over it.

### Phase 5 — Real-time inference over WebSocket ⭐ (core of the MVP)
- Backend `WS /ws/predict/{meeting_code}`: receives landmark frames, normalises, buffers, predicts, smooths, emits stable predictions.
- Frontend: `useHandLandmarker` + `useSignSocket` + `HandOverlayCanvas` + `SignDetectionPanel`.
- Throttle sending to ~10 FPS. Draw the 21 landmarks live over the video — a visible skeleton is the most convincing single element in a demo.
- Implement the smoothing/sentence-assembly algorithm in Section 9.
**Acceptance:** I sign in front of the webcam and correct text appears within ~1 second, with a visible confidence bar, and letters/words accumulate without stuttering or repeating.

### Phase 6 — Meeting room UI + WebRTC + Speech-to-Text
- WebRTC 1:1 call via the FastAPI signalling WebSocket (offer/answer/ICE, Google STUN).
- Recognised sign text broadcast to the other participant as a live subtitle.
- `useSpeechToText` via Web Speech API for the reverse direction.
- `TranscriptPanel` accumulates both directions with speaker label + timestamp and persists to the backend.
**Acceptance:** two browser tabs (or two laptops on one network) connected; sign text appears on the hearing user's screen, speech text on the deaf user's screen.

### Phase 7 — Interview Mode, polish, docs
- `useFocusMonitor`: `visibilitychange` + `blur`, warning counter, events logged to the meeting record. State honestly in the README that this is a deterrent, not real proctoring.
- Loading states, error boundaries, camera-permission-denied handling, WebSocket auto-reconnect, empty states, WCAG AA contrast, keyboard navigation.
- Write `README.md`, `ARCHITECTURE.md`, `REVIEW_DEMO.md`, `docs/api.md`, `ml/README.md`.
**Acceptance:** fresh-clone test — you walk the README setup steps yourself and confirm they are complete and correct.

---

## 8. MODEL SPECIFICATIONS

### 8.1 Model A — static classifier
```
Input (63,) → Dense 256 ReLU → BatchNorm → Dropout 0.3
            → Dense 128 ReLU → BatchNorm → Dropout 0.3
            → Dense 64  ReLU
            → Dense n_classes Softmax
```
Adam (lr 1e-3), sparse categorical crossentropy, EarlyStopping (patience 10, restore best), ReduceLROnPlateau, batch 64, up to 100 epochs.

### 8.2 Model B — dynamic classifier
```
Input (30, 126) → Masking → LSTM 128 return_sequences → Dropout 0.3
                → LSTM 64 → Dropout 0.3
                → Dense 64 ReLU → Dense n_classes Softmax
```
Same optimiser/callbacks. If LSTM is slow on CPU, try GRU and report the accuracy/speed trade-off.

### 8.3 Landmark normalisation — CRITICAL
This exact procedure must be implemented **three times and produce identical numbers**: `ml/scripts/preprocess.py`, `backend/app/ml/normalization.py`, and `frontend/src/utils/landmarkUtils.js`. A mismatch here is the classic silent bug where training accuracy is 97% and live inference is garbage.

1. Translate: subtract wrist landmark (index 0) from all 21 points → position invariance.
2. Scale: divide by the maximum Euclidean distance from the wrist → distance invariance.
3. Flatten to 63 floats in fixed landmark order.
4. Two hands: order as `[left_hand(63), right_hand(63)]` using MediaPipe handedness; zero-fill a missing hand.
5. Write a unit test feeding the same raw landmark array through the Python and JS implementations, asserting they match to 1e-6. Put it in `backend/tests/`.

Record `"normalization_version": 1` in `metadata.json`; the backend must refuse to load a model whose version does not match the code.

### 8.4 Saved artifacts
`ml/models/static_model.keras`, `dynamic_model.keras` (if produced), `labels.json`, `metadata.json`. Backend loads these once at startup, not per request.

---

## 9. REAL-TIME PREDICTION ALGORITHM

Raw frame-by-frame argmax output flickers and is unusable. Implement in `backend/app/ml/smoothing.py`:

1. **Frame rate:** frontend sends landmarks at ~10 FPS (throttle; do not send every `requestAnimationFrame`).
2. **Rolling buffer:** last 30 frames per connection for the dynamic model.
3. **Confidence gate:** ignore predictions below `CONFIDENCE_THRESHOLD = 0.80` (configurable in `.env`).
4. **Majority vote:** hold the last 10 predictions; accept a label only if it appears in ≥ 7.
5. **Debounce:** after emitting a label, suppress the same label for `COOLDOWN_MS = 1500`.
6. **Neutral reset:** when `nothing` dominates for ≥ 8 frames, close the current word and allow the next sign.
7. **Sentence assembly:** append accepted labels to a session buffer; for fingerspelling, append letters into words with `space` closing a word. Emit both the current prediction and the accumulated sentence. Provide a "clear" action in the UI.

**WebSocket message contract — implement exactly:**

Client → server:
```json
{ "type": "landmarks",
  "mode": "static" | "dynamic",
  "timestamp": 1234567890,
  "hands": [{"handedness": "Right", "landmarks": [[x,y,z], ... 21 items]}] }
```

Server → client:
```json
{ "type": "prediction", "label": "A", "confidence": 0.94,
  "stable": true, "sentence": "HELLO", "latency_ms": 38 }
```
```json
{ "type": "error", "code": "MODEL_NOT_LOADED", "message": "..." }
```

Surface `latency_ms` in the UI — being able to point at a real latency number during the review is worth a lot.

---

## 10. DATABASE SCHEMA

```
users(id PK, name, email UNIQUE, password_hash, role ENUM('deaf','hearing'), created_at)
meetings(id PK, code UNIQUE, title, host_id FK→users, is_interview_mode BOOL,
         started_at, ended_at, created_at)
meeting_participants(id PK, meeting_id FK, user_id FK, joined_at, left_at)
transcripts(id PK, meeting_id FK, user_id FK, source ENUM('sign','speech'),
            content TEXT, confidence FLOAT NULL, created_at)
focus_events(id PK, meeting_id FK, user_id FK, event_type ENUM('blur','hidden','return'), created_at)
```
Index `meetings.code`, `transcripts.meeting_id`, `meeting_participants.meeting_id`. Provide `database/schema.sql` and `seed.sql` with two demo users (one deaf-role, one hearing-role) so the demo does not depend on live registration.

---

## 11. FRONTEND REQUIREMENTS

- Clean, calm, high-contrast interface. Accessibility is the point of this project — meet WCAG AA contrast, use semantic HTML, label every control, support keyboard navigation.
- **Meeting room layout:** two video tiles side by side, landmark skeleton overlay on the local deaf-user tile, a large subtitle bar across the bottom, a collapsible transcript panel on the right, and a control bar (mic, camera, sign-detection on/off, Interview Mode, leave).
- Subtitles ≥ 22px, high contrast, readable over video.
- `SignDetectionPanel` shows current prediction, confidence bar, accumulated sentence, connection status, and latency.
- Handle explicitly and visibly: camera permission denied, no hand detected, model loading, WebSocket disconnected/reconnecting.
- Auto-reconnect the WebSocket with exponential backoff.

---

## 12. README.md — WRITE THIS AS A TEACHING DOCUMENT

The README is a graded deliverable and a study document. Two students who did not write the code must be able to read it and fully understand the system. Aim for genuine depth — several thousand words is appropriate. Use Mermaid diagrams (they render on GitHub).

Required sections, in order:

1. **Project title, one-paragraph summary, team + guide details**
2. **Problem statement** — why captions alone don't solve deaf↔hearing communication
3. **What this MVP does and does not do** — honest scope boundaries
4. **Glossary** — landmark, MLP, LSTM, softmax, confidence threshold, WebRTC, STUN, signalling, WebSocket, JWT, inference, epoch, overfitting. Plain-language definitions.
5. **System architecture** — Mermaid component diagram + prose walkthrough
6. **End-to-end data flow** — trace one sign from hand movement to text on the other person's screen, numbered, naming the exact file and function at each step
7. **Module-by-module deep dive** — for each of the 8 SRS modules: *what it does / why this technology / key files / how data moves through it / how to extend it*
8. **The machine learning explained from zero** — what a hand landmark is (with the 21-point map), why we classify landmarks instead of pixels, why normalisation matters, why static and dynamic need different architectures, what the training output numbers mean, how to read a confusion matrix
9. **Dataset documentation** — which public datasets we used, their sources, licences and citations; **the explicit statement that no self-recorded training data was used and why that matters for reproducibility**; datasets we rejected and why; full download instructions repeated here; dataset statistics table
10. **Model results** — accuracy, per-class metrics, confusion matrix image, and honest failure analysis (which letters/signs get confused and why — e.g. M/N/S/T in ASL fingerspelling are visually near-identical from landmarks alone)
11. **API reference** — every REST endpoint with method, path, auth requirement, request/response examples; both WebSocket protocols documented
12. **Database schema** — Mermaid ER diagram + table descriptions
13. **Complete setup guide** — prerequisites with versions, MySQL Workbench setup, `.env` configuration, Python venv, npm install, MediaPipe asset download, Kaggle dataset download, landmark extraction, model training. Numbered, copy-pasteable, no assumed knowledge.
14. **How to run** — exact commands for backend and frontend, in order, with expected output, plus how to run a two-person test on one machine and on two machines
15. **Project structure** — annotated file tree explaining what every directory is for
16. **Troubleshooting** — at minimum: camera not detected, MediaPipe WASM 404, CORS errors, MySQL access denied / connection refused, Kaggle 403 (terms not accepted), WebSocket disconnects, model file not found, good training accuracy but poor live accuracy, WebRTC not connecting across devices
17. **Testing** — how to run the tests, what they cover
18. **Limitations and known issues** — stated honestly, including the dataset-domain-gap problem
19. **Future enhancements** — mapped to our SRS: sentence-level translation, multilingual support, Indian Sign Language (INCLUDE / ISL-CSLTR datasets), emotion recognition, mobile app, AI meeting summaries
20. **References** — MediaPipe, TensorFlow, React, FastAPI, OpenCV, WebRTC, Whisper docs, plus dataset sources and papers

Write in clear, plain English. Expand acronyms on first use. Prefer short paragraphs and concrete examples over abstract description.

---

## 13. REVIEW_DEMO.md

A short separate document containing:
- A 5-minute demo script: exact click-by-click sequence, which signs to perform in which order, what to say while things load.
- A pre-demo checklist (MySQL running, model files present, camera free, lighting, backup recording).
- **Anticipated review questions with prepared answers:** Why landmarks instead of raw video? Why an MLP for static and an LSTM for dynamic? How do you handle prediction flicker? What is your accuracy and why isn't it higher? Which classes does the model confuse and why? Why did you train only on public datasets? Why MediaPipe over a custom CNN? How does this scale beyond fingerspelling? What happens on a slow network? How is this different from Google Meet captions? Why FastAPI over Flask/Django? Is Interview Mode real proctoring?
- Known weak spots and how to answer honestly if the demo misbehaves.

---

## 14. TESTING

- `backend/tests/`: auth flow, meeting CRUD, JWT expiry/rejection, the normalisation parity test (Section 8.3), and a smoothing-logic unit test using a synthetic prediction stream.
- `ml/scripts/evaluate.py`: classification report, confusion matrix, per-class accuracy, saved to `docs/images/`.
- One manual end-to-end test checklist in the README.
- Run the tests yourself and show me the passing output.

---

## 15. FINAL DELIVERABLES CHECKLIST

Before declaring the build complete, verify and report on each:

- [ ] `git log` shows one commit per phase
- [ ] `setup` script runs clean on a fresh clone
- [ ] Backend starts, `/docs` (Swagger) loads, all endpoints listed
- [ ] Frontend builds and runs with no console errors
- [ ] MySQL schema created and seeded; no credentials in git
- [ ] Model A trained from a public dataset, accuracy reported honestly
- [ ] Model B attempted, result and recommendation reported
- [ ] No self-recorded training data anywhere in the repo
- [ ] Live sign → text works in the browser end to end
- [ ] Landmark skeleton overlay visible
- [ ] Sentence assembly works without stuttering
- [ ] Two-tab WebRTC call with cross-participant subtitles
- [ ] Speech-to-text working
- [ ] Transcript saved to DB and exportable
- [ ] Interview Mode logs focus events
- [ ] README, ARCHITECTURE, REVIEW_DEMO, api.md, ml/README all complete
- [ ] All tests pass

---

## 16. START HERE

Do this now, before writing any code:

1. Confirm you have read and understood this brief, and restate the dataset constraint in Section 6.0 in your own words so I know it registered.
2. Give me a **short build plan**: the phases, what you'll build in each, and where you think the risk is.
3. List every point in the build where you will need an ACTION REQUIRED handoff from me, so I can prepare (Kaggle account, MySQL password, downloads).
4. Then begin **Phase 0** and work forward, pausing after each phase for me to confirm it works on my machine.

Do not attempt to build everything in one shot. Phase by phase, verified as you go.
