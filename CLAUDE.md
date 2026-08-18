# CLAUDE.md — context for future Claude Code sessions

This file is read automatically by Claude Code when a session starts in this
repository. Keep it short, factual and current.

## What this project is

**BridgeTalk** — AI-assisted real-time communication platform for deaf and
hearing individuals. MCA mini project, PSG College of Technology, Department of
Computer Applications.

- **Team:** Swarna Rathna A, Thamizhthilaga S D S
- **Guide:** Dr. R. Manavalan

The gap being closed: video-conferencing tools caption *speech* for deaf users,
but there is no reverse channel — a hearing user cannot understand sign
language. BridgeTalk translates **sign language → text in real time**, inside a
video call.

## Build authority

`BridgeTalk_Master_Prompt_v2.md` at the repository root is the specification.
When this file and the master prompt disagree, the master prompt wins.

## Locked technology stack — do not substitute

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS |
| Hand tracking | `@mediapipe/tasks-vision` HandLandmarker, **in the browser** |
| Backend | FastAPI + Uvicorn (Python 3.11) |
| ML | TensorFlow / Keras |
| Offline video/image processing | OpenCV |
| Real-time transport | FastAPI native WebSockets |
| Call | WebRTC peer-to-peer, backend as signalling server |
| Speech-to-text | Web Speech API (Whisper documented as fallback only) |
| Database | MySQL 8+ via SQLAlchemy |
| Auth | JWT (python-jose) + passlib/bcrypt |

## Hard constraints

1. **Public datasets only.** All training data comes from published public
   datasets (ASL Alphabet, WLASL). No self-recorded training data anywhere in
   the repo. `test_realtime.py` and `record_eval_clip.py` use the webcam only to
   *evaluate* an already-trained model — they never write training samples.
2. **Landmarks leave the browser, video never does.** MediaPipe runs
   client-side; only 21×3 float coordinates (a few hundred bytes) go over the
   WebSocket. This is a core privacy/bandwidth claim of the design and must stay
   visibly true in the code.
3. **Normalisation is implemented twice and must agree to 1e-6:**
   `backend/app/ml/normalization.py` and
   `frontend/src/utils/landmarkUtils.js`. This is a deliberate departure from
   the master prompt's "three times" — every `ml/scripts/*` file *imports* the
   backend implementation rather than reimplementing it, because a second
   Python copy would manufacture exactly the drift the rule exists to prevent.
   `backend/tests/test_normalization_parity.py` guards the one boundary that
   can genuinely diverge, and was verified to fail when a 0.001% divergence is
   injected. A mismatch here is the classic silent bug: 97% training accuracy,
   garbage live predictions.
4. **CPU only.** Every model must train on CPU in under 30 minutes.
5. **No secrets in git.** Real values live in `.env` (gitignored).
   `.env.example` carries placeholders only.
6. **Pin every version** in `requirements.txt` and `package.json`.
7. **No stubs.** No `TODO: implement`, no placeholder functions, no endpoint
   returning fake data that pretends to be a model.

## Layout

```
backend/    FastAPI app (api/, ws/, ml/, models/, schemas/, core/) + tests
            ml/ holds predictor · normalization · smoothing · sequence
ml/         dataset scripts, training scripts, saved .keras models
frontend/   React + Vite client
database/   schema.sql, seed.sql
docs/       api.md, images/ (confusion matrices, diagrams, screenshots)
scripts/    setup + run scripts (.sh and .bat)
```

## Commands

```bash
# one-time setup (creates .venv, installs Python + npm deps)
./scripts/setup.sh                 # Windows: scripts\setup.bat

# run
./scripts/run_backend.sh           # FastAPI on :8000, docs at /docs
./scripts/run_frontend.sh          # Vite on :5173

# tests
source .venv/bin/activate && pytest backend/tests -v
```

## Build phase status

- [x] Phase 0 — scaffold, docs skeleton, setup scripts
- [x] Phase 1 — backend foundation, MySQL, JWT auth
- [x] Phase 2 — meetings & transcripts API
- [x] Phase 3 — dataset acquisition & landmark extraction
- [x] Phase 4 — model training + evaluation (Model A trained: 90.5% test.
      Model B pipeline complete and tested but **not trained** — WLASL is a
      multi-GB download that has not been fetched. No accuracy is claimed.)
- [x] Phase 5 — real-time inference over WebSocket
- [x] Phase 6 — meeting room UI, WebRTC, speech-to-text
- [x] Phase 7 — Interview Mode, polish, documentation

Update these boxes as phases complete.

## Working agreements

- One commit per completed phase, with a descriptive message.
- Run the code before claiming a phase works; show real terminal output.
- When something is genuinely blocked on the user (Kaggle terms, MySQL
  password, a large download), stop and use the ACTION REQUIRED block from
  Section 2 of the master prompt. Do not guess paths or fabricate credentials.
