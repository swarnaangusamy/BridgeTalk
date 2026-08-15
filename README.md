# BridgeTalk

**AI-Assisted Real-Time Communication Platform for Deaf and Hearing Individuals**

> **Build status: Phase 0 of 7 complete (scaffold).**
> This README is a *graded teaching document* and is written progressively as
> the build proceeds. Sections marked **_(Phase N)_** are filled in when that
> phase lands. Nothing below is speculative — if it is written here, it is
> already true of the code in this repository.

---

## 1. Summary

BridgeTalk is a browser-based video-calling platform that translates **sign
language into text in real time**, so that a deaf participant and a hearing
participant can hold a conversation without a human interpreter present.

Hand tracking runs **in the browser** using MediaPipe. Only the 21 hand-landmark
coordinates — a few hundred bytes per frame — travel to the server, where a
TensorFlow model classifies the gesture and streams the recognised text back
over a WebSocket. Raw video never leaves the participant's machine.

| | |
|---|---|
| **Course** | MCA Mini Project |
| **Institution** | PSG College of Technology, Department of Computer Applications |
| **Team** | Swarna Rathna A · Thamizhthilaga S D S |
| **Guide** | Dr. R. Manavalan |

---

## 2. Problem statement

Zoom, Google Meet and Microsoft Teams all provide speech-to-text captions. A
deaf participant can therefore *read* what a hearing participant says.

There is no reverse channel. A hearing participant cannot understand sign
language, so the conversation stays one-directional unless a human interpreter
joins the call. Interpreters are expensive, must be booked in advance, and are
simply unavailable for an unplanned five-minute conversation.

BridgeTalk closes that loop: it adds the missing **sign → text** direction, and
keeps the existing **speech → text** direction, inside one meeting room.

```
Hearing user speaks  ──▶ Web Speech API ──▶ caption on deaf user's screen   ✅ exists today
Deaf user signs      ──▶       ???       ──▶ text on hearing user's screen  ❌ the gap
                              ▲
                       this is what BridgeTalk builds
```

---

## 3. What this MVP does and does not do

**It does:**

- Recognise **static ASL fingerspelling handshapes** (A–Z, plus `space`,
  `delete` and a neutral `nothing` class) from a standard laptop webcam.
- Assemble recognised letters into words and sentences with temporal smoothing,
  so the output does not flicker.
- Run a 1:1 WebRTC video call with live subtitles in both directions.
- Persist meeting transcripts to MySQL and export them.

**It does not:**

- Translate full sign-language *grammar*. ASL has its own syntax; this MVP
  performs gesture-to-text recognition, not linguistic translation.
- Recognise the thousands of word-level signs in everyday use. A 20-word
  dynamic model is attempted as a stretch goal and its real accuracy is reported
  honestly rather than hidden.
- Support Indian Sign Language yet. See *Future enhancements*.
- Work reliably in poor lighting, at extreme camera angles, or with hands
  partially out of frame — MediaPipe must see the hand to landmark it.

---

## 4. Glossary

_(Phase 7 — plain-language definitions of: landmark, MLP, LSTM, softmax,
confidence threshold, WebRTC, STUN, signalling, WebSocket, JWT, inference,
epoch, overfitting.)_

---

## 5. System architecture

_(Phase 7 — Mermaid component diagram + prose walkthrough. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the current working draft.)_

---

## 6. End-to-end data flow

_(Phase 7 — one sign traced from hand movement to text on the other person's
screen, numbered, naming the exact file and function at each step.)_

---

## 7. Module-by-module deep dive

_(Phase 7 — all eight SRS modules.)_

---

## 8. The machine learning, explained from zero

_(Phase 4 / Phase 7 — what a hand landmark is, why we classify landmarks instead
of pixels, why normalisation matters, why static and dynamic signs need
different architectures, how to read a confusion matrix.)_

---

## 9. Dataset documentation

_(Phase 3 — sources, licences, citations, statistics.)_

**Stated up front, because it is a design constraint and not an afterthought:**
every model in this project is trained on **publicly available datasets only**.
No member of the team recorded gesture data to train a model. This matters for
reproducibility — anyone with a Kaggle account can download the same data and
retrain the same model — and it keeps the reported accuracy honest, because the
model has never seen our faces, our hands, our room or our lighting during
training.

Two webcam scripts exist in `ml/scripts/`, and neither produces training data:

| Script | Purpose |
|---|---|
| `test_realtime.py` | Runs the **already-trained** model live, to see it work |
| `record_eval_clip.py` | Records a short clip to **evaluate** the trained model |

---

## 10. Model results

_(Phase 4 — accuracy, per-class metrics, confusion matrix, failure analysis.)_

---

## 11. API reference

_(Phases 1–2 and 5–6; see [docs/api.md](docs/api.md).)_

---

## 12. Database schema

_(Phase 1 — Mermaid ER diagram + table descriptions; see
[database/schema.sql](database/schema.sql).)_

---

## 13. Setup guide

### Prerequisites

| Requirement | Version | Check with |
|---|---|---|
| Python | **3.11** (3.12 works; **not** 3.13 — TensorFlow has no wheels for it) | `python3.11 --version` |
| Node.js | **20 LTS or newer** | `node --version` |
| MySQL | **8.x or newer**, e.g. via MySQL Workbench | `mysql --version` |
| Git | any recent version | `git --version` |

Installing Python 3.11 if you do not have it:

```bash
# macOS
brew install python@3.11

# Ubuntu / Debian
sudo apt install python3.11 python3.11-venv

# Windows — download the 3.11 installer from python.org and tick
# "Add python.exe to PATH" during installation.
```

### One-command setup

```bash
git clone <your-repo-url> BridgeTalk
cd BridgeTalk

./scripts/setup.sh          # macOS / Linux
scripts\setup.bat           # Windows
```

The setup script:

1. finds a Python 3.11 interpreter and creates `.venv`;
2. installs every pinned package from `backend/requirements.txt`
   (this includes TensorFlow, so expect a few minutes);
3. runs `npm install` in `frontend/`;
4. downloads the MediaPipe `hand_landmarker.task` model and copies the WASM
   runtime into `frontend/public/models/`;
5. creates `.env` from `.env.example` if you do not already have one.

It is safe to re-run.

### Configure `.env`

`.env` is gitignored and holds every secret. After setup, edit it:

```bash
# 1. Point DATABASE_URL at your MySQL instance
DATABASE_URL=mysql+pymysql://bridgetalk:YOUR_PASSWORD@localhost:3306/bridgetalk

# 2. Generate a real JWT secret
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste that generated value into `JWT_SECRET_KEY`.

> **Quick demo without MySQL:** replace the `DATABASE_URL` line with
> `DATABASE_URL=sqlite:///./bridgetalk.db`. That is the only change needed —
> SQLAlchemy handles the rest.

### Database, datasets, model training

_(Phases 1, 3 and 4 — MySQL Workbench setup, Kaggle download, landmark
extraction and training instructions land here.)_

---

## 14. How to run

```bash
# terminal 1 — backend, http://localhost:8000  (Swagger UI at /docs)
./scripts/run_backend.sh          # Windows: scripts\run_backend.bat

# terminal 2 — frontend, http://localhost:5173
./scripts/run_frontend.sh         # Windows: scripts\run_frontend.bat
```

Then open <http://localhost:5173>.

> **Camera access needs a secure context.** Browsers grant `getUserMedia` only
> over HTTPS or on `localhost`. `http://localhost:5173` is fine; reaching this
> machine from a second laptop at `http://192.168.x.x:5173` is not, and the
> camera will silently fail. The two-machine testing instructions in Phase 6
> cover the ways around this.

---

## 15. Project structure

```
BridgeTalk/
├── backend/            FastAPI application
│   ├── app/
│   │   ├── api/        REST routers  (auth, meetings, transcripts)
│   │   ├── ws/         WebSocket endpoints (inference, WebRTC signalling)
│   │   ├── ml/         model loading, normalisation, smoothing
│   │   ├── models/     SQLAlchemy ORM tables
│   │   ├── schemas/    Pydantic request/response contracts
│   │   └── core/       JWT, password hashing, FastAPI dependencies
│   ├── tests/          pytest suite
│   └── requirements.txt
│
├── ml/                 everything that happens *before* the app runs
│   ├── data/raw/       downloaded public datasets        (gitignored)
│   ├── data/processed/ extracted landmark vectors        (gitignored)
│   ├── scripts/        download, extract, preprocess, train, evaluate
│   └── models/         trained .keras + labels.json + metadata.json
│
├── frontend/           React 18 + Vite + Tailwind client
│   ├── src/pages/      Login, Register, Dashboard, MeetingRoom, History
│   ├── src/components/ video tiles, subtitle bar, transcript, overlays
│   ├── src/hooks/      MediaPipe, WebSocket, speech-to-text, WebRTC
│   └── public/models/  MediaPipe .task + WASM assets    (gitignored)
│
├── database/           schema.sql, seed.sql
├── docs/               api.md, images/ (diagrams, confusion matrices)
└── scripts/            setup + run scripts, .sh and .bat
```

---

## 16. Troubleshooting

_(Phase 7 — the full list. Entries valid as of Phase 0:)_

| Symptom | Cause | Fix |
|---|---|---|
| `setup.sh: Python 3.11 not found` | Only Python 3.9/3.13 on PATH | `brew install python@3.11`, then re-run setup |
| `Node <version> is too old` | Node 18 or earlier | Install Node 20 LTS or newer |
| Frontend shows **Backend status: Offline** | API not running, or wrong port | Start `run_backend.sh`; check `VITE_API_BASE_URL` in `.env` |
| Browser console: CORS error | Frontend origin not allowed | Add it to `CORS_ORIGINS` in `.env` and restart the backend |
| `hand_landmarker.task` download failed | Network blocks Google Storage | Download the URL printed by setup manually into `frontend/public/models/` |

---

## 17. Testing

_(Phase 7 — how to run the suite and what it covers.)_

```bash
source .venv/bin/activate
pytest backend/tests -v
```

---

## 18. Limitations and known issues

_(Phase 7 — including the dataset domain-gap problem: a model trained on a
public dataset's lighting, cameras and framing performs measurably worse on
*our* webcam in *our* room. This is a real, documented, publishable limitation.)_

---

## 19. Future enhancements

Mapped to the SRS: sentence-level translation, multilingual support, Indian Sign
Language (INCLUDE / ISL-CSLTR datasets), emotion recognition, a mobile app, and
AI-generated meeting summaries.

---

## 20. References

_(Phase 7 — MediaPipe, TensorFlow, React, FastAPI, OpenCV, WebRTC and Whisper
documentation, plus dataset sources and the WLASL paper.)_
