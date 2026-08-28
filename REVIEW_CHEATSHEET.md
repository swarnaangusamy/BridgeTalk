# BridgeTalk — Review Cheat Sheet

**MCA Mini Project · PSG College of Technology, Dept. of Computer Applications**
Swarna Rathna A · Thamizhthilaga S D S · Guide: Dr. R. Manavalan

---

## 60-second pitch (say this out loud)

> "Video calling apps already caption speech. If I speak, a deaf person can read
> my words on screen. But there is no reverse channel — if a deaf person signs,
> I cannot understand them without a human interpreter.
>
> BridgeTalk builds that missing direction. It watches a deaf person sign
> through their webcam and turns it into text on the hearing person's screen, in
> real time, inside a video call. Both directions land in one shared transcript.
>
> The key design decision: hand tracking runs **inside the browser**. Only 21
> coordinate points per hand travel over the network — about 5 kilobytes per
> second. The video itself never leaves the user's machine."

---

## The one-sentence answer

> **Google Meet captions speech only. BridgeTalk captions sign language — the
> direction no mainstream platform supports.**

---

## Tech stack

| Technology | Where | Why |
|---|---|---|
| **React 18 + Vite** | Frontend | Component UI; Vite for fast builds |
| **MediaPipe HandLandmarker** | Browser (WebAssembly) | Finds 21 hand joints per frame, on-device |
| **FastAPI** | Backend | Native async WebSockets — the core of this project |
| **TensorFlow / Keras** | Backend | Runs the trained sign-recognition models |
| **WebSocket** | Both | Persistent 2-way channel; HTTP polling would add latency per frame |
| **WebRTC** | Browser ↔ Browser | Peer-to-peer video; media never touches our server |
| **Web Speech API** | Browser | Speech → text, free and built in |
| **MySQL 8 + SQLAlchemy** | Backend | Users, meetings, transcripts — relational data with real foreign keys |
| **JWT (python-jose) + bcrypt** | Backend | Stateless auth; hashed passwords |
| **OpenCV** | Offline only | Decoding dataset videos during training |

---

## Data flow — hand movement to text, in 8 steps

1. **Webcam** streams video into the browser at ~60 fps. It stays local.
2. **MediaPipe** (`useHandLandmarker.js`) converts each frame into 21 joint
   positions per hand — `(x, y, z)` numbers, not pixels.
3. **Feature builder** (`normalization.py`) turns those into **132 numbers**:
   hand shape for both hands, plus each wrist's position so *movement* survives.
4. **Throttle to 10 fps** (`SignDetection.jsx`) and send over the WebSocket
   `/ws/predict/{code}`. About **5 KB/s**. No image data.
5. **Backend buffers 30 frames** (`sequence.py`) — three seconds of movement,
   because a word sign *is* a movement, not a pose.
6. **The model predicts** (`predictor.py`) — a bidirectional LSTM, **18 ms**.
7. **Smoothing** (`smoothing.py`) — confidence gate → majority vote → debounce.
   Stops the caption flickering a new word ten times a second.
8. **Text is sent back** and broadcast to the other participant, who sees it in
   `SubtitleBar.jsx`. Final lines are saved to MySQL.

---

## Key numbers (all measured, from the code)

| | |
|---|---|
| **ISL words recognised** | **40** (plus 1 internal "between signs" class) |
| **Accuracy on cut clips** | **85.2%** top-1 · 94.6% top-3 |
| **Word Error Rate, continuous signing** | **17.5%** |
| Word Error Rate if the signer pauses | 34.2% — *worse* |
| **Model inference** | **18 ms** |
| **End-to-end (browser → text)** | **25 ms** |
| Dataset | INCLUDE — 2,014 clips, 137 words available; **829 clips** used for our 40 |
| Extraction discard rate | **0%** — MediaPipe found hands in every clip |
| ASL fingerspelling baseline | 90.5% top-1, 28 classes, 87,000 images → 66,858 vectors |
| **Automated tests** | **201, all passing** |
| **API endpoints** | **16 HTTP + 3 WebSocket** |
| Lines of code | backend 7,646 · frontend 4,251 · ML 5,186 · tests 3,290 · SQL 228 |
| Model input → output | `(30, 132)` → 41 classes |
| Training time | ~7 min, **CPU only** |
| Team size / duration | 2 people |
| CPU usage during inference | `NOT MEASURED` |

---

## Built vs not built — be honest

| ✅ Working | ❌ Not working / not done |
|---|---|
| ISL word recognition, 40 words, live | **Whisper fallback — code written, never installed or run** |
| ASL fingerspelling model (baseline) | ISL *alphabet* model — pipeline built, no dataset obtained |
| Real-time WebSocket inference, 25 ms | **HTTPS — not set up.** Two-laptop demo will fail |
| WebRTC 1:1 video call, peer-to-peer | Signer-independent testing — dataset has no signer IDs |
| Speech → text via Web Speech API | Speech provider refactor — **written, uncommitted, untested** |
| Transcripts saved to MySQL + `.txt` export | Full sentences / grammar — single signs only |
| Interview Mode (tab-focus logging) | Testing with real deaf users |
| JWT auth, bcrypt passwords | Production deployment |
| 201 automated tests | Mobile support |

---

## Five hardest questions

**1. Why not just build on Google Meet or Zoom?**
Neither gives third-party developers raw video frames — and frame access *is*
the project. Meet's Add-on SDK gives you a side panel, not the camera. We would
still need our own capture pipeline, so we'd gain nothing and lose the privacy
claim, since the video would already be on their servers.

**2. What's your accuracy, and why isn't it higher?**
85.2% on cut clips, but 17.5% word error rate on continuous signing — the
honest number. Two reasons: only ~20 training clips per word, and the model is
trained on pre-cut clips while real signing has no gaps between words.

**3. Is this signer-independent?**
No, and we can prove we know why. The INCLUDE dataset records no signer ID, so
our test split holds out *clips*, not *people*. Our code writes
`signer_disjoint: false` everywhere so the number is never overstated.

**4. Where is the video stored?**
Nowhere. It never leaves the browser. Only 21 coordinate triples per hand cross
the network, and `backend/app/ws/inference.py` has no code path that could
accept an image. That's the central privacy claim of the design.

**5. Can a deaf person actually use this today?**
Not as a daily tool — 40 words and one word in six wrong. It's a working
demonstration that the reverse caption channel is buildable, not a product. The
path to a product is more data per sign and continuous-signing segmentation.
