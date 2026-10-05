# BridgeTalk — Complete Technical Documentation

**Project:** BridgeTalk — AI-assisted real-time communication for deaf and hearing participants
**Course:** MCA mini project, PSG College of Technology, Department of Computer Applications
**Team:** Swarna Rathna A, Thamizhthilaga S D S
**Guide:** Dr. R. Manavalan
**Document generated:** 2026-10-05
**Documented commit:** `0b04c0d` on branch `client`

---

## How to read this document

Every section explains the part in **plain language first** — what it does and
why it exists — and then gives the precise technical detail. Every technical
term is defined the first time it appears. Every factual claim names the file it
came from, so you can open the code and check it.

Numbers in this document come from one of three places, and nothing else:

1. a file in the repository (source, config, schema, or a saved `.json` artefact),
2. the live MySQL database, queried while writing this,
3. a command run while writing this (the test suites, the model loader, the API).

Where a number is not recorded anywhere and cannot be measured, this document
says **"not recorded"** and states what would be needed to obtain it. See
[Appendix A](#appendix-a-how-this-document-was-verified) for exactly what was
verified by running something versus by reading code.

Where the code disagrees with `README.md`, `PROGRESS.md` or `ARCHITECTURE.md`,
**the code wins** and the disagreement is listed in
[Section 19](#19-known-issues-limitations-and-future-work).

---

## Table of contents

| # | Section | What it covers |
|---|---|---|
| 1 | [Project overview](#1-project-overview) | The problem, the users, scope and non-scope |
| 2 | [Features](#2-features) | Every user-facing feature and its true status |
| 3 | [System architecture](#3-system-architecture) | Component diagram and eight sequence diagrams |
| 4 | [Technology stack](#4-technology-stack) | Every library with its exact pinned version |
| 5 | [Repository structure](#5-repository-structure) | Full folder tree, explained |
| 6 | [Frontend](#6-frontend) | Routes, components, hooks, state, design system |
| 7 | [Backend API reference](#7-backend-api-reference) | All 18 endpoints and all 3 WebSockets |
| 8 | [External APIs, services and browser APIs](#8-external-apis-services-and-browser-apis) | Everything that is not our code |
| 9 | [Database](#9-database) | Engine, ER diagram, all 5 tables, all 34 columns |
| 10 | [Machine learning: datasets and models](#10-machine-learning-datasets-and-models) | Datasets, features, 3 models, evaluation |
| 11 | [Speech-to-text](#11-speech-to-text) | Two engines, selection, fallback, limits |
| 12 | [Real-time communication](#12-real-time-communication) | WebRTC signalling, ICE, tracks, reconnect |
| 13 | [Authentication and security](#13-authentication-and-security) | Passwords, tokens, access control, privacy |
| 14 | [Interview mode](#14-interview-mode) | What it detects and what it genuinely cannot |
| 15 | [Configuration](#15-configuration) | Every environment variable |
| 16 | [Running and deploying](#16-running-and-deploying) | Commands, Docker, HTTPS, browsers |
| 17 | [Testing](#17-testing) | Every test, and the result of running them now |
| 18 | [Development history](#18-development-history) | Timeline from the git log |
| 19 | [Known issues, limitations and future work](#19-known-issues-limitations-and-future-work) | Everything that is not right |
| 20 | [Review preparation](#20-review-preparation) | 30 likely examiner questions, answered |
| 21 | [Glossary](#21-glossary) | Every term, in one or two sentences |
| A | [Appendix A: how this document was verified](#appendix-a-how-this-document-was-verified) | Run vs read vs unconfirmed |

---

# 1. Project overview

## In one paragraph

BridgeTalk is a browser-based video-calling application in which **translation
runs in both directions at once**. When a deaf participant signs, hand
positions are tracked inside their own browser, sent to a Python server as a few
hundred bytes of coordinates, classified by a neural network, and appear as live
text on the hearing participant's screen. When the hearing participant speaks,
their speech is transcribed and appears as live text on the deaf participant's
screen. Both directions write into one shared transcript that is saved to a
MySQL database and can be downloaded afterwards as a `.txt` or `.pdf` file. The
system is a React single-page application talking to a FastAPI backend over REST
and three WebSockets, with the video and audio of the call itself travelling
peer-to-peer over WebRTC rather than through the server.

## The problem it solves

Video-conferencing tools already caption **speech** for deaf users. Google Meet,
Zoom and Teams all do this well. What none of them does is the **reverse
channel**: a hearing participant cannot understand sign language.

That asymmetry is the gap. In a meeting between a deaf person and a hearing
person using existing tools:

| Direction | Existing tools | What the deaf user experiences |
|---|---|---|
| Hearing person speaks → deaf person reads | Solved (live captions) | Works |
| Deaf person signs → hearing person understands | **Not addressed** | Must type, or bring an interpreter |

BridgeTalk closes the second row. The deaf participant signs; the hearing
participant reads.

## Who the users are

| User | Who they are | What they do in the app |
|---|---|---|
| **Deaf / hard-of-hearing participant** | Signs rather than speaks | Switches on sign recognition in the lobby, signs during the call, reads the hearing participant's speech as captions |
| **Hearing participant** | Speaks rather than signs | Speaks normally, reads the deaf participant's signs as captions |
| **Host** | Whoever created the meeting | Everything above, plus: can end the meeting for everyone, can switch Interview Mode on, and can read the Interview Mode log afterwards |
| **Interviewer** (a host, in a specific use case) | Conducting a remote interview | Uses Interview Mode to record when a candidate leaves the meeting tab |

The role is stored on the user account as an enum (`deaf` or `hearing`) in
`users.role`. It is explicitly **a UI hint, not a permission boundary** — the
comment in `database/schema.sql` says so, and both roles may use both
translation directions. Its only functional effect is in
`frontend/src/pages/Lobby.jsx`, where `user?.role === 'deaf'` pre-ticks the
"I will be signing in this meeting" checkbox.

## Objectives

| # | Objective | Where it is realised |
|---|---|---|
| 1 | Translate sign language to text live, inside a video call | `backend/app/ws/inference.py`, `frontend/src/hooks/useSignCaptions.js` |
| 2 | Translate speech to text live, in the same call | `frontend/src/services/stt/`, `backend/app/ws/transcribe.py` |
| 3 | Show both directions to both participants identically | `backend/app/ws/captions.py` (one protocol, one broadcast) |
| 4 | Keep the raw video on the user's own machine | MediaPipe runs in the browser; only coordinates cross the network |
| 5 | Save a usable transcript and let it be downloaded | `backend/app/api/transcripts.py` |
| 6 | Train only on published public datasets | `ml/models/*_manifest.json`, all with `self_recorded_data: false` |
| 7 | Train on CPU in under 30 minutes | Longest recorded training run is 451.9 s (`dynamic_metadata.json`) |

## Scope — what is in

- Account registration and login
- Creating a meeting, and joining one by a short code or a link
- A pre-join lobby with camera preview, microphone level meter and device selection
- A **two-person** peer-to-peer video and audio call
- Sign-to-text in three selectable modes: ISL words, ISL letters, ASL letters
- Speech-to-text with two engines (browser-based and server-based)
- Live captions shown to every participant
- Screen sharing as an additional video track
- Interview Mode (tab-switch detection and logging)
- Transcript saving, viewing, searching, and download as `.txt` and `.pdf`
- Meeting history

## Scope — what is deliberately out

| Out of scope | Why |
|---|---|
| **More than two people in a call** | The WebRTC code is written for one peer. `frontend/src/hooks/useWebRTC.js` holds a single `RTCPeerConnection`, and `Stage.jsx` has an explicit three-or-more grid branch but only ever receives one remote stream. A three-way call needs either a mesh of N−1 connections or a media server (SFU), which is a project of its own. |
| **Full continuous sign language translation** | The models classify isolated letters and isolated words from a 40-word vocabulary. Continuous sign language has its own grammar, facial grammar and non-manual markers; translating it is an open research problem, not a mini-project. |
| **Grammar correction of signed output** | The output is the recognised tokens joined together. ISL word order differs from English word order, and no language model reorders it. |
| **Self-recorded training data** | A hard project constraint. Every manifest records `self_recorded_data: false`. The webcam scripts (`ml/scripts/test_realtime.py`, `ml/scripts/record_eval_clip.py`) only *evaluate* an already-trained model and never write training samples. |
| **Mobile applications** | It is a web application. The layout is responsive below 900 px, but there is no native app. |
| **Real proctoring** | Interview Mode is explicitly a deterrent. It cannot see a second monitor, a phone, or another person in the room. See [Section 14](#14-interview-mode). |
| **Production-grade deployment** | No TURN server is configured, so calls fail on networks that need media relaying. See [Section 12](#12-real-time-communication). |

---

# 2. Features

**Status key:** **Working** = exercised by an automated test or by a command run
for this document. **Partly working** = functions, with a stated limitation or
an untested path. **Broken** = confirmed defect, detailed in
[Section 19](#19-known-issues-limitations-and-future-work).

| # | Feature | What the user sees | How it works internally | Main files | Status |
|---|---|---|---|---|---|
| 1 | **Registration** | A 400 px card: full name, email, password, confirm password, and "How will you mostly take part?" | The form validates locally with the same rules the server enforces (password ≥ 8 characters), then `POST /api/auth/register`. The server bcrypt-hashes the password, inserts a `users` row, and returns a JWT plus the user object in one response, so registering logs you straight in. | `frontend/src/pages/Login.jsx`, `backend/app/api/auth.py::register` | Working |
| 2 | **Login** | Email and password, with a show/hide eye on the password | `POST /api/auth/login/json` verifies the bcrypt hash and returns a JWT valid for 1440 minutes. The token is stored in `localStorage` and attached as an `Authorization: Bearer` header by `services/api.js`. On every page load `AuthContext` calls `GET /api/auth/me` to check the token is still valid. | `frontend/src/pages/Login.jsx`, `frontend/src/context/AuthContext.jsx`, `backend/app/api/auth.py::login_json` | Working |
| 3 | **Create a meeting** | "New meeting" opens a menu: "Create a meeting for later" (shows code + link + copy button) or "Start an instant meeting" (goes to the lobby) | Both menu items call the same `POST /api/meetings`. Only what happens next differs. The server generates a code with `secrets.choice` over a 31-character alphabet that excludes O/0, I/1 and L, in two groups of three (`K7Q-2M4`). | `frontend/src/pages/Home.jsx`, `backend/app/api/meetings.py::create_meeting`, `::generate_meeting_code` | Working |
| 4 | **Join a meeting** | A "Enter a code or link" box with a Join button that stays disabled until you type | `parseMeetingCode` in `utils/formatters.js` accepts a bare code, a hyphenated code or a full URL. Home then calls `GET /api/meetings/{code}` **before** navigating, so an unknown code shows an inline error on Home rather than a broken lobby with the camera already requested. | `frontend/src/pages/Home.jsx`, `frontend/src/utils/formatters.js::parseMeetingCode` | Working |
| 5 | **Lobby (pre-join)** | A mirrored 16∶9 camera preview, round mic/camera buttons over it, a five-bar live microphone level meter, three device dropdowns, and "I will be signing in this meeting" | `getUserMedia` is requested here rather than in the meeting, so the browser's permission prompt happens on a calm screen — and in an Interview Mode meeting the prompt does not get counted as leaving the tab. The level meter is a real Web Audio `AnalyserNode` computing time-domain RMS. Device choices go to `sessionStorage`, never the URL. | `frontend/src/pages/Lobby.jsx`, `frontend/src/hooks/useMicLevel.js`, `frontend/src/services/devicePreferences.js` | Working |
| 6 | **Video and audio call** | Two video tiles: the other person fills the stage, your own video floats bottom-right | A peer-to-peer WebRTC connection. The `/ws/signal/{code}` WebSocket relays offer/answer/ICE messages verbatim; the server never parses SDP. Media never touches the server. "Perfect negotiation" (polite/impolite peers) prevents both sides offering at once. | `frontend/src/hooks/useWebRTC.js`, `backend/app/ws/signaling.py` | Partly working — media path verified only by automated stubs; two real browsers not verified by me |
| 7 | **Sign-to-text** | A hand skeleton on your own tile, a pill showing what is being detected, and the recognised word appearing as a caption on both screens | MediaPipe HandLandmarker runs in the browser at animation-frame rate and produces 21 3-D points per hand. Those are normalised (wrist to origin, scale to 1.0), throttled to 10 frames/second, and sent over `/ws/predict/{code}`. The server classifies them with one of three Keras models and returns a per-frame prediction; the **client** decides where a word starts and ends and sends a `caption` message. | `frontend/src/hooks/useHandLandmarker.js`, `frontend/src/hooks/useSignCaptions.js`, `backend/app/ws/inference.py`, `backend/app/ml/predictor.py` | Partly working — see accuracy and idle false positives in [Section 10](#10-machine-learning-datasets-and-models) |
| 8 | **Speech-to-text** | Grey interim text that firms to white when you pause | Two engines behind one interface. Web Speech API runs in the browser and streams interim text word by word. Whisper runs on the server: the browser records Opus audio with `MediaRecorder` and streams it over `/ws/transcribe/{code}`, where ffmpeg decodes it and faster-whisper transcribes complete utterances. | `frontend/src/services/stt/`, `frontend/src/hooks/useSpeechCaptions.js`, `backend/app/ws/transcribe.py` | Partly working — "Auto" and "Whisper" work; selecting **"Browser"** in Settings crashes the page (issue K-1) |
| 9 | **Live captions** | A 140 px area between the video and the control bar, showing the last three lines with the speaker's avatar, name, and a "Sign" or "Speech" badge | One protocol for both directions. Every caption carries a producer-generated `segment_id`. An **interim** event carries the full current text of that segment and receivers **replace** that line; a **final** event closes it. The server broadcasts to everyone *including the sender*, so both screens render from one source of truth. | `frontend/src/components/meeting/CaptionRail.jsx`, `frontend/src/hooks/useCaptionStore.js`, `backend/app/ws/captions.py` | Working |
| 10 | **Caption display toggle** | A "CC" button, blue when on; captions are on by default | Display only. Producing captions is gated on your microphone being unmuted and your camera being on — never on whether you chose to look at captions. | `frontend/src/pages/MeetingRoom.jsx` (`captionsVisible`) | Working |
| 11 | **Screen sharing** | A Present button; the shared screen fills the stage and both camera tiles move to a strip on the right | `getDisplayMedia` produces a second video track which is **added** to the peer connection, not swapped in — so the signer stays visible while anyone presents. Start and stop are announced over the signalling socket as `presentation-start` / `presentation-stop`. Stopping works from our button, from the browser's own "Stop sharing" bar, and on the presenter leaving. | `frontend/src/hooks/useScreenShare.js`, `frontend/src/components/meeting/Stage.jsx` | Partly working — signalling verified; two-browser media path not verified by me |
| 12 | **Interview Mode** | Host switches it on from the More menu; the other participant gets an acknowledgement dialog, an "Interview mode" chip, and a blocking overlay if they leave the tab | Three browser APIs: `visibilitychange` and `blur` detect leaving, the Fullscreen API makes leaving cost you the view, and the Keyboard Lock API (Chromium only) captures Escape. Each event is `POST`ed to `/api/meetings/{code}/focus-events` so it survives a reload. | `frontend/src/hooks/useInterviewMode.js`, `backend/app/api/meetings.py::log_focus_event` | Working, with hard limits — see [Section 14](#14-interview-mode) |
| 13 | **Transcript saving** | Nothing — it is automatic | Persisted once per segment, on the **final** caption event, by `persist_final_caption`. The database has `UNIQUE (meeting_id, segment_id)`, so a client retry or a reconnect that replays its tail collides instead of writing a duplicate line. | `backend/app/ws/captions.py::persist_final_caption` | Working |
| 14 | **Live transcript panel** | A 360 px panel sliding in from the right, listing every saved entry with speaker, time and source badge | Reads the **persisted rows** from `GET /api/transcripts/{meeting_id}` rather than the in-memory caption list, so it agrees with the downloaded file and includes everything said before you joined. Refreshed when a final caption arrives, not on a timer. | `frontend/src/components/meeting/LiveTranscriptPanel.jsx` | Working |
| 15 | **Meeting history** | "Meeting history" with a search box and a list of meetings, newest first | `GET /api/meetings/history` returns meetings you hosted or attended, each with its participants and a caption count. Four SQL queries regardless of how many meetings. "Load more" pages client-side. | `frontend/src/pages/History.jsx`, `backend/app/api/meetings.py::meeting_history` | Working |
| 16 | **Search** | One box that finds a meeting by its title **or** by something said in it | Server-side, via `?q=`. Titles are matched with `ILIKE`; caption text is matched with a **subquery** over `transcripts` rather than a JOIN, so a meeting containing the word five times appears once. Debounced 300 ms in the browser. | `backend/app/api/meetings.py::meeting_history`, `frontend/src/pages/History.jsx` | Working |
| 17 | **Transcript page** | Source chips (All / Sign / Speech), a participant filter, a search box that highlights matches, and consecutive lines from one speaker grouped under one name | Loads the meeting and its transcript, filters and groups in the browser. Access control is the server's: `GET /api/transcripts/{id}` returns 403 to a non-participant, and the page turns that into "You do not have access to this transcript". | `frontend/src/pages/Transcript.jsx`, `backend/app/api/transcripts.py::get_transcript` | Working |
| 18 | **Transcript download** | "Download TXT" and "Download PDF" | Both go through an authenticated `fetch` to a Blob and a temporary anchor click — a plain `<a href>` cannot carry the `Authorization` header, which is why the button once returned 401 instead of a file. The PDF is built with reportlab. | `frontend/src/services/api.js::transcripts.download`, `backend/app/api/transcripts.py::export_transcript`, `::export_transcript_pdf` | Working |
| 19 | **Meeting-ended page** | "You left the meeting" or "The meeting has ended", with Rejoin, Return to home, and a saved-transcript card | Re-fetches the meeting rather than trusting what it was told, because the host may have ended the meeting while you were in it. Rejoin is withheld once `is_active` is false. | `frontend/src/pages/MeetingEnded.jsx` | Working |
| 20 | **End meeting for everyone** | Host-only. The Leave button opens a menu with "Just leave" and "End meeting for everyone" | `POST /api/meetings/{code}/end` sets `ended_at` and stamps `left_at` on every participant. Host-only, enforced server-side. | `backend/app/api/meetings.py::end_meeting` | Working |
| 21 | **Settings dialog** | Three tabs: Audio and video, Captions, Sign recognition | Changes apply immediately — no Save button, because these are the controls you reach for when something is already wrong. Device changes acquire a new track, put it in the local stream, and `replaceTrack` it into the peer connection. Preferences persist in `localStorage` per user id. | `frontend/src/components/meeting/SettingsDialog.jsx`, `frontend/src/hooks/useMeetingPreferences.js` | Partly working — the Captions tab's "Browser" option triggers issue K-1 |
| 22 | **Keyboard shortcuts** | Ctrl/Cmd+D microphone, Ctrl/Cmd+E camera, C captions; shown in each tooltip | A single `keydown` listener on `window`, skipped when focus is in an `INPUT`, `TEXTAREA` or `SELECT` so typing a meeting code cannot mute you. | `frontend/src/pages/MeetingRoom.jsx` | Working |
| 23 | **Toasts** | Short notices bottom-left: someone joined, left, or started presenting | Deduplicated: WebRTC and the signalling socket both observe a participant arriving, so a toast with text already on screen refreshes that toast's timer instead of stacking a copy. | `frontend/src/components/ui/ToastHost.jsx` | Working |
| 24 | **Meeting details panel** | Title, code, joining link with a copy button, host, and a privacy note | `navigator.clipboard.writeText`. Fails silently on plain HTTP from a non-localhost origin, where the Clipboard API is unavailable; the link is selectable text so copying by hand still works. | `frontend/src/components/meeting/DetailsPanel.jsx` | Working |
| 25 | **People panel** | Each participant with their microphone and camera state | Your own state is read directly. The remote state is **inferred** from whether their media tracks are present and unmuted, so it is labelled honestly ("No audio arriving", not "Muted") — a dropped network looks the same as a mute button. | `frontend/src/components/meeting/PeoplePanel.jsx` | Working |
| 26 | **Sign recognition check** (`/detect`) | A standalone page: camera, skeleton, and the current prediction with a confidence bar | The quickest way to check a model works without a second participant. Uses the same `useHandLandmarker` and `/ws/predict` path as the meeting, with `DEMO` as the meeting code — for which the inference socket deliberately persists nothing. | `frontend/src/pages/SignDetection.jsx`, `frontend/src/components/SignDetectionPanel.jsx` | Working |
| 27 | **Debug overlay** (`?debug=1`) | A panel listing microphone track state, speech engine and state, last interim text, last caption sent, last caption received, sign recogniser state and socket state | Shown only when the URL carries `?debug=1`. Exists because "I spoke and nothing happened" is not a reportable bug without knowing which stage died. | `frontend/src/components/DebugOverlay.jsx` | Working |
| 28 | **Undo / clear while signing** | Two tiny buttons on the detection pill on your own tile | Lets a signer correct a wrong word **before** it is finalised and sent. Once a final event is broadcast, the text is on the other person's screen and in the transcript, and nothing in the interface takes it back. | `frontend/src/pages/MeetingRoom.jsx::SignPill`, `frontend/src/hooks/useSignCaptions.js` | Working |
| 29 | **Full screen** | More menu → Full screen | `document.documentElement.requestFullscreen()`. Separate from Interview Mode's own fullscreen enforcement. | `frontend/src/pages/MeetingRoom.jsx::toggleFullscreen` | Working |
| 30 | **Health endpoint** | Not user-facing | `GET /health` reports API version, database reachability and dialect, the load state of all three sign models, Whisper's state, and live socket occupancy. Used by the Docker health check and as the first thing to look at when something is wrong. | `backend/app/main.py::health` | Working |

---

# 3. System architecture

## 3.1 The one idea that shapes everything

**Hand tracking runs in the browser; only coordinates cross the network.**

MediaPipe — Google's on-device vision library — runs as WebAssembly inside the
user's own browser. It turns each video frame into 21 three-dimensional points
per hand. Those points, not the picture, are what travel to the server:
63 floating-point numbers for one hand, about 500 bytes per frame at 10 frames
per second.

This single decision produces four consequences that run through the whole
system:

| Consequence | Why it follows |
|---|---|
| **Privacy** | The server never receives video. There is no frame to leak, log or subpoena. |
| **Bandwidth** | ~5 KB/s of coordinates instead of ~500 KB/s of video — a factor of about 100. |
| **Server cost** | The server does one small matrix multiplication per frame, not video decoding. The ASL model has 60,892 parameters; median server-side inference is **0.7 ms** (`ml/models/inference_path_report.json`). |
| **It must stay visibly true** | If any code path ever sent a frame, the central privacy claim of the design would be false. This is why the inference socket accepts only a `landmarks` message and rejects anything else. |

The **call itself** is separate. The video and audio the two people see and hear
travel **peer-to-peer over WebRTC**, directly between the two browsers. The
backend is only a signalling relay: it passes connection-setup messages back and
forth and never sees the media.

## 3.2 Component diagram

```mermaid
graph TB
    subgraph B1["Browser — deaf participant"]
        CAM1["Camera + microphone<br/>getUserMedia"]
        MP1["MediaPipe HandLandmarker<br/>WASM, in-browser<br/>21 points x 3 coords per hand"]
        NORM1["landmarkUtils.js<br/>normalise: wrist to origin, scale to 1.0"]
        UI1["React SPA<br/>Stage · CaptionRail · ControlBar"]
        RTC1["useWebRTC<br/>RTCPeerConnection"]
        CAM1 --> MP1 --> NORM1
    end

    subgraph B2["Browser — hearing participant"]
        MIC2["Microphone"]
        WS2["Web Speech API<br/>engine 1"]
        MR2["MediaRecorder<br/>Opus, for engine 2"]
        UI2["React SPA"]
        RTC2["useWebRTC<br/>RTCPeerConnection"]
        MIC2 --> WS2
        MIC2 --> MR2
    end

    subgraph SRV["FastAPI backend — Python 3.11, Uvicorn, port 8000"]
        REST["REST routers<br/>auth · meetings · transcripts<br/>18 endpoints"]
        WSP["/ws/predict/{code}<br/>inference.py"]
        WSS["/ws/signal/{code}<br/>signaling.py"]
        WST["/ws/transcribe/{code}<br/>transcribe.py"]
        PRED["predictor.py<br/>3 Keras models, loaded once at startup"]
        SMOOTH["smoothing.py<br/>gate - vote - debounce - reset"]
        SEQ["sequence.py<br/>30-frame sliding window"]
        CAPS["captions.py<br/>ONE caption protocol"]
        CM["connection_manager.py<br/>who is in which meeting"]
        WHIS["WhisperTranscriber<br/>faster-whisper base, int8 CPU"]
        FFM["ffmpeg subprocess<br/>Opus to 16 kHz PCM"]
        WSP --> PRED --> SMOOTH
        WSP --> SEQ
        WSP --> CAPS
        WST --> FFM --> WHIS
        WSP --> CM
        WSS --> CM
    end

    DB[("MySQL 9.7.1<br/>users · meetings<br/>meeting_participants<br/>transcripts · focus_events")]

    MODELS[["ml/models/<br/>static_model.keras 753 KB<br/>isl_model.keras 948 KB<br/>dynamic_model.keras 5.1 MB"]]

    subgraph EXT["External — outside our control"]
        GOOG["Google speech servers<br/>receives AUDIO when<br/>Web Speech is the engine"]
        STUN["Google STUN<br/>stun.l.google.com:19302"]
        FONTS["Google Fonts CDN<br/>Roboto + Material Symbols"]
    end

    NORM1 -. "landmark JSON, ~5 KB/s<br/>NO VIDEO" .-> WSP
    WSP -. "prediction per frame" .-> UI1
    UI1 -. "caption: segment_id + text" .-> WSP
    WSP -. "caption broadcast to EVERYONE<br/>including the sender" .-> UI1
    WSP -. "caption broadcast" .-> UI2

    WS2 -. "audio" .-> GOOG
    GOOG -. "transcript text" .-> UI2
    MR2 -. "Opus chunks" .-> WST
    WST -. "transcript text" .-> UI2
    UI2 -. "caption: segment_id + text" .-> WSP

    RTC1 <-. "offer / answer / ICE<br/>relayed verbatim" .-> WSS
    RTC2 <-. "offer / answer / ICE" .-> WSS
    RTC1 <== "VIDEO + AUDIO<br/>peer-to-peer, never via the server" ==> RTC2
    RTC1 -. "what is my public address?" .-> STUN
    RTC2 -. "what is my public address?" .-> STUN

    UI1 -. "REST + JWT" .-> REST
    UI2 -. "REST + JWT" .-> REST
    REST --> DB
    CAPS --> DB
    PRED --> MODELS
    UI1 -. "fonts, first load only" .-> FONTS

    style MODELS fill:#e8f0fe
    style DB fill:#e6f4ea
    style EXT fill:#fce8e6
```

### Walk-through of the component diagram

1. **Both browsers** run the same React single-page application, built by Vite
   and served on port 5173 in development. Which features each participant uses
   differs; the code does not.
2. **The deaf participant's browser** captures the camera, runs MediaPipe over
   each frame locally, normalises the resulting landmarks, and sends only those
   numbers to `/ws/predict/{code}`.
3. **The backend** classifies each frame with one of three Keras models and
   sends a `prediction` message **back to that one client only** — it is not
   broadcast, because a per-frame prediction is not yet a caption.
4. **The client** decides where a word begins and ends (`useSignCaptions.js`)
   and only then sends a `caption` message with a stable `segment_id`.
5. **The backend broadcasts that caption to everyone in the meeting, the sender
   included.** This is the detail that makes both screens agree: neither side
   renders its own words from local state.
6. **On a final caption**, `persist_final_caption` writes exactly one
   `transcripts` row, protected by a `UNIQUE (meeting_id, segment_id)` index.
7. **The hearing participant's browser** transcribes their own microphone with
   whichever engine is selected, and sends the result as a `caption` message on
   the same socket. Speech and sign are the same protocol from here on.
8. **The call media** goes directly browser-to-browser. `/ws/signal/{code}`
   relays setup messages and nothing else; `connection_manager.py` tracks who is
   in which meeting.
9. **MySQL** holds all five tables. The Keras models are loaded from disk once,
   during FastAPI's `lifespan` startup, never per request.

## 3.3 Flow: sign to caption

```mermaid
sequenceDiagram
    autonumber
    participant V as Video element
    participant MP as MediaPipe<br/>(in browser)
    participant SC as useSignCaptions<br/>(in browser)
    participant S as /ws/predict
    participant M as Keras model
    participant SM as PredictionSmoother
    participant OTHER as Other participant
    participant DB as MySQL

    loop every animation frame (~60 Hz)
        V->>MP: detect(videoElement)
        MP-->>SC: 21 landmarks x 3 coords per hand
        SC->>SC: measureMotion() vs previous frame
    end

    loop throttled to 10 Hz (SEND_INTERVAL_MS = 100)
        SC->>S: {type:"landmarks", mode, hands:[...]}
        S->>S: normalize_hands / sequence_frame_features
        S->>M: predict(feature vector)
        M-->>S: label, confidence, full probability array
        S->>SM: push(label, confidence)
        SM-->>S: label, stable, emitted, sentence
        S-->>SC: {type:"prediction", label, confidence,<br/>margin, stable, latency_ms}
    end

    Note over SC: Client-side gates, all from config/recognition.js:<br/>confidence >= 0.70 AND margin >= 0.15<br/>AND real movement within last 20 frames<br/>AND hands returned to rest since last commit

    SC->>SC: movement segment ends<br/>(4 consecutive still frames)
    SC->>S: {type:"caption", segment_id, source:"sign",<br/>text, is_final:false}
    S->>OTHER: {type:"caption", ...} broadcast
    S->>SC: {type:"caption", ...} sender included

    Note over SC: hands at rest 1500 ms (UTTERANCE_END_MS)

    SC->>S: {type:"caption", segment_id, text, is_final:true}
    S->>OTHER: final caption broadcast
    S->>DB: persist_final_caption()<br/>INSERT ... UNIQUE(meeting_id, segment_id)
```

**Step by step.**

- **1–3.** `useHandLandmarker` calls MediaPipe on every animation frame, so the
  skeleton overlay looks smooth. Detection is local and costs only CPU.
- **4.** `useSignCaptions.measureMotion` compares this frame's landmarks with the
  previous frame's: the mean per-landmark displacement, in normalised units
  where a hand spans 1.0.
- **5.** Sending is throttled to one frame per 100 ms. The smoother votes over
  10 frames, which at 10 Hz is a one-second decision — about how long a person
  holds a letter. Sending at 60 Hz would sextuple the traffic to reach the same
  answer.
- **6–7.** The server normalises and classifies. Which function is used depends
  on the mode: `normalize_primary_hand` → 63 features (ASL),
  `normalize_hands` → 126 (ISL letters), `sequence_frame_features` → 132 per
  frame in a 30-frame window (ISL words).
- **8–10.** `PredictionSmoother` applies the server-side gate, majority vote,
  cooldown and neutral reset, and returns a per-frame result **to that client
  only**.
- **11.** The client applies its own four gates. The fourth —
  `MOTION_LOOKBACK_FRAMES` — exists because of a measurement: fed a resting
  hand, the letter model passes confidence and margin essentially always, since
  a hand at rest genuinely *is* a valid handshape. Movement is the only signal
  that separates "resting in this shape" from "signing this letter".
- **12–14.** When a movement segment ends, the client sends an interim caption.
  The server broadcasts it to everyone including the sender.
- **15–17.** After 1500 ms at rest the client sends `is_final: true`. The server
  broadcasts it and writes exactly one database row.

## 3.4 Flow: speech to caption — engine 1, Web Speech API

```mermaid
sequenceDiagram
    autonumber
    participant MIC as Microphone
    participant WSP as WebSpeechProvider<br/>(in browser)
    participant G as Google speech servers<br/>EXTERNAL
    participant SP as useSpeechCaptions
    participant S as /ws/predict
    participant OTHER as Other participant
    participant DB as MySQL

    SP->>WSP: start()  (microphone is unmuted)
    WSP->>WSP: new SpeechRecognition()<br/>continuous = true<br/>interimResults = true<br/>lang = 'en-IN'
    WSP->>G: streams AUDIO from the microphone

    loop while speaking
        G-->>WSP: onresult: interim transcript
        WSP-->>SP: onInterim(text)
        SP->>S: {type:"caption", segment_id, source:"speech",<br/>text:"<full current text>", is_final:false}
        S->>OTHER: caption broadcast
        S->>SP: caption broadcast (sender included)
    end

    Note over G: speaker pauses

    G-->>WSP: onresult: isFinal = true
    WSP-->>SP: onFinal(text)
    SP->>S: {type:"caption", segment_id, text, is_final:true}
    S->>OTHER: final caption broadcast
    S->>DB: one transcripts row
    SP->>SP: newSegmentId() for the next utterance

    G-->>WSP: onend (the API stops on its own, by design)
    WSP->>WSP: restart if still wanted<br/>bounded: MAX_RESTARTS = 40,<br/>backoff 300 ms to 5000 ms
    WSP->>G: new session
```

**Step by step.**

- **1–3.** The Web Speech API is a browser API. `continuous = true` keeps it
  running across sentences; `interimResults = true` is what gives word-by-word
  text; `lang` comes from preferences and defaults to `en-IN`.
- **4.** **The audio leaves the machine.** In Chrome, Web Speech sends
  microphone audio to Google's servers for recognition. This is stated in the
  UI — `services/stt/index.js` labels it *"Audio is sent to Google"* — because it
  sits in direct tension with the project's "video never leaves your machine"
  claim for the other direction. See [Section 8](#8-external-apis-services-and-browser-apis).
- **5–9.** Each interim result carries the **full current text** of the
  utterance, and receivers replace the line with that `segment_id`. Appending
  instead of replacing is what once produced captions reading
  "warm warm warm".
- **10–13.** A final result closes the segment, is persisted, and the client
  generates a new `segment_id`.
- **14–16.** `onend` fires routinely — the API terminates sessions on its own.
  The provider restarts it whenever the microphone is still unmuted, with
  bounded retries and exponential backoff so a permanently failing recogniser
  cannot busy-loop (`config/recognition.js` → `SPEECH`).

## 3.5 Flow: speech to caption — engine 2, Whisper on the server

```mermaid
sequenceDiagram
    autonumber
    participant MIC as Microphone
    participant MR as MediaRecorder<br/>(in browser)
    participant WP as WhisperProvider
    participant T as /ws/transcribe
    participant SD as StreamDecoder
    participant FF as ffmpeg subprocess
    participant UB as UtteranceBuffer<br/>(energy VAD)
    participant W as faster-whisper base<br/>int8, CPU
    participant SP as useSpeechCaptions
    participant S as /ws/predict

    WP->>T: connect with ?token=<JWT>
    T-->>WP: {type:"ready", provider:"whisper",<br/>model:"base", sample_rate:16000,<br/>provides_interim:false}

    WP->>MR: start(timeslice)
    loop every timeslice
        MR-->>WP: Blob (Opus in WebM)
        WP->>T: binary frame
        T->>SD: feed(bytes)
        Note over SD: Keeps the WHOLE stream and re-decodes it,<br/>feeding forward only NEW samples.<br/>Only fragment 1 carries the WebM init segment,<br/>so decoding fragments independently yields<br/>ZERO samples from fragment 2 onwards.
        SD->>FF: whole stream on stdin
        FF-->>SD: 16 kHz mono float32 PCM
        SD-->>UB: new samples only
        UB->>UB: RMS < 0.015 counts as silence
    end

    Note over UB: 0.7 s of silence, or 12 s ceiling reached

    UB-->>T: complete utterance (>= 0.4 s, else discarded)
    T->>W: transcribe(samples, language)  via asyncio.to_thread
    W-->>T: text, confidence
    T-->>SP: {type:"transcript", text, confidence,<br/>is_final:true, audio_seconds, latency_ms}
    SP->>S: {type:"caption", segment_id, source:"speech",<br/>text, is_final:true}
```

**Step by step.**

- **1–2.** The socket authenticates by JWT in the query string, then reports
  `provides_interim: false` — so the UI shows a listening indicator rather than
  waiting for partial text that will never come.
- **3–5.** `MediaRecorder` produces fragmented WebM/Opus. Each `timeslice`
  yields a Blob which is sent as a binary WebSocket frame.
- **6–7.** **This is where the "speech produced no captions" bug lived.** Only
  the *first* MediaRecorder fragment carries the WebM initialisation segment.
  Decoding each fragment independently gives real audio from fragment 1 and
  **zero samples** from every fragment after it. `StreamDecoder` keeps the whole
  stream, re-decodes it, and feeds forward only the newly appeared samples.
- **8–10.** ffmpeg is a **subprocess**, not a library. Without it on `PATH`,
  the socket closes immediately with `FFMPEG_MISSING`.
- **11–13.** `UtteranceBuffer` is an **energy-based** voice-activity detector:
  root-mean-square below `SILENCE_RMS = 0.015` is silence; `SILENCE_DURATION_S
  = 0.7` of it ends an utterance; `MAX_UTTERANCE_S = 12.0` is a hard ceiling;
  anything under `MIN_UTTERANCE_S = 0.4` is discarded as a cough or a door.
- **14.** Whisper is CPU-bound and blocking, so it runs in
  `asyncio.to_thread`. Calling it directly would stall the event loop and
  freeze every other socket this worker serves.
- **15–16.** The result is always `is_final: true` — Whisper has no interim
  concept. The client then sends it as a normal `caption` message, so from this
  point speech and sign are identical.

## 3.6 Flow: caption broadcast to the other participant

```mermaid
sequenceDiagram
    autonumber
    participant P as Producer<br/>(either participant)
    participant S as /ws/predict<br/>inference.py
    participant V as validate_caption
    participant B as build_caption_event
    participant CM as inference_manager
    participant R1 as Receiver 1 (the sender)
    participant R2 as Receiver 2 (the other person)
    participant DB as MySQL

    P->>S: {type:"caption", segment_id, source,<br/>text, is_final, confidence}
    S->>V: validate_caption(message)
    alt invalid
        V-->>S: error string
        S-->>P: {type:"error", code:"INVALID_MESSAGE", message}
    else valid
        V-->>S: None
        S->>B: build_caption_event(...)
        B-->>S: event with SERVER timestamp,<br/>speaker{id,name}, meeting_code
        S->>CM: broadcast(meeting_code, event)
        CM->>R1: caption event
        CM->>R2: caption event
        Note over R1,R2: BOTH apply it the same way:<br/>useCaptionStore replaces the entry<br/>whose segmentId matches. Never appends.
        opt is_final AND meeting_code != "DEMO"
            S->>DB: SELECT meeting WHERE code = ?
            S->>DB: persist_final_caption()
            alt IntegrityError (UNIQUE collision)
                DB-->>S: already stored - rollback, no-op
            end
        end
    end
```

**Step by step.**

- **2–5.** `validate_caption` checks four things before anything is broadcast:
  `segment_id` is a non-empty string of at most 64 characters, `source` is
  exactly `sign` or `speech`, `text` is a string, and `confidence` is a number
  or null. An invalid message gets an error **back to the sender only**.
- **6–7.** `build_caption_event` stamps the **server's** time, not the client's.
  Two clients with skewed clocks would otherwise produce a transcript that does
  not sort into the order the conversation happened in.
- **8–10.** The broadcast goes to **everyone, sender included**. This is the
  key design point. Previously the sender was excluded and rendered its own
  words from local state, so the two participants' caption lists were assembled
  by different code paths and disagreed.
- **11.** Both receivers apply the event identically: replace the entry with
  this `segment_id`.
- **12–15.** Persistence happens only on `is_final`, and only for a real
  meeting — the `DEMO` code used by `/detect` writes nothing. A duplicate final
  event hits the `UNIQUE (meeting_id, segment_id)` index, raises
  `IntegrityError`, is rolled back, and returns `False`. Idempotent by database
  constraint, not by hope.

## 3.7 Flow: transcript saving and retrieval

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant S as /ws/predict
    participant DB as MySQL transcripts
    participant API as GET /api/transcripts/{id}
    participant PANEL as LiveTranscriptPanel
    participant EXP as GET .../export(.pdf)

    S->>DB: INSERT (meeting_id, user_id, segment_id,<br/>source, content, confidence)
    Note over DB: UNIQUE (meeting_id, segment_id)<br/>content is THIS SEGMENT only, never history

    C->>C: a final caption arrived - refresh
    C->>API: GET /api/transcripts/7  (Bearer JWT)
    API->>DB: SELECT ... WHERE meeting_id = 7<br/>ORDER BY created_at
    API->>API: membership check:<br/>host OR in meeting_participants
    alt not a participant
        API-->>C: 403 Forbidden
    else participant
        API-->>C: 200 [TranscriptPublic, ...]<br/>each with user_name joined in
        C->>PANEL: render persisted rows
    end

    C->>EXP: GET /api/transcripts/7/export  (Bearer JWT)
    Note over C,EXP: An authenticated fetch to a Blob, NOT an <a href>.<br/>A navigation cannot set an Authorization header,<br/>which is why this once returned 401 instead of a file.
    EXP-->>C: text/plain + Content-Disposition filename
    C->>C: createObjectURL - click a temporary anchor - revokeObjectURL
```

**Step by step.**

- **1–2.** One row per segment. `content` holds only what was said in that
  segment. The transcript once stored the whole accumulated sentence per emitted
  word, producing rows reading "a", "a b", "a b c"; the `segment_id` column and
  its UNIQUE index are what stopped that.
- **3–5.** The panel refreshes when a final caption arrives — not on a timer —
  so a quiet meeting makes no requests.
- **6–8.** Access control is server-side. `get_transcript` checks the caller is
  the host or appears in `meeting_participants`; anyone else gets 403. The
  frontend only turns that into a readable sentence.
- **9–12.** Both exports use an authenticated `fetch` → `Blob` → temporary
  anchor, and revoke the object URL afterwards so a long meeting does not hold
  every download in memory.

## 3.8 Flow: joining a meeting and establishing the call

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant L as Lobby
    participant API as REST API
    participant MR as MeetingRoom
    participant SIG as /ws/signal
    participant PEER as Other browser
    participant STUN as Google STUN

    U->>L: open /lobby/K7Q-2M4
    L->>API: GET /api/meetings/K7Q-2M4
    API-->>L: MeetingDetail (title, participants, interview flag)
    L->>L: getUserMedia({video, audio})<br/>echoCancellation + noiseSuppression ON
    Note over L: Permission prompt happens HERE, on a calm screen -<br/>not mid-call, where it would steal focus and be<br/>logged as an Interview Mode violation.
    U->>L: picks devices, ticks "I will be signing", Join now
    L->>L: saveDevicePreferences() to sessionStorage
    L->>API: POST /api/meetings/K7Q-2M4/join
    API-->>L: {meeting, is_first_participant}
    L->>MR: navigate to /meeting/K7Q-2M4

    MR->>MR: getUserMedia again, using the stored device ids
    MR->>SIG: connect ?token=<JWT>
    SIG-->>MR: {type:"joined", self, peers:[...],<br/>should_initiate: peers.length > 0}
    SIG->>PEER: {type:"peer-joined", peer}

    Note over MR,PEER: should_initiate decides who offers.<br/>Whoever arrives SECOND starts the call,<br/>because they know somebody is waiting.<br/>This avoids "glare" - both offering at once.

    MR->>STUN: gather ICE candidates
    STUN-->>MR: public address (server-reflexive candidate)
    MR->>MR: createOffer(); setLocalDescription()
    MR->>SIG: {type:"offer", payload: SDP}
    SIG->>PEER: {type:"offer", from, payload}
    Note over SIG: Relayed VERBATIM. The server never parses SDP,<br/>so a WebRTC spec change needs no backend change.
    PEER->>PEER: setRemoteDescription(); createAnswer()
    PEER->>SIG: {type:"answer", payload: SDP}
    SIG->>MR: {type:"answer", from, payload}
    MR->>MR: setRemoteDescription()

    loop ICE candidates, both directions
        MR->>SIG: {type:"ice-candidate", payload}
        SIG->>PEER: {type:"ice-candidate", from, payload}
    end

    MR<<-->>PEER: connectionState = "connected"<br/>AUDIO + VIDEO flow DIRECTLY
```

**Step by step.**

- **2–5.** The lobby fetches the meeting first, so an unknown code fails before
  the camera is touched. `getUserMedia` requests echo cancellation and noise
  suppression explicitly — not cosmetic, because speech recognition runs on this
  microphone and the remote participant's voice coming back through the speakers
  would otherwise be transcribed as if this user had said it.
- **8–10.** Device ids go to `sessionStorage`. They were once query parameters
  on the join link, which put a stable hardware identifier into a URL users are
  told to share, plus browser history and `Referer` headers.
- **13–14.** `should_initiate` is `len(existing_peers) > 0`. Exactly one side
  creates the offer; if both offered simultaneously the negotiation would
  collide ("glare") and both would have to back off and retry.
- **16–17.** STUN tells a browser what its own public address looks like. It is
  enough when a direct path exists — two laptops on one Wi-Fi network. It is
  **not** enough behind symmetric NAT, where TURN is required. No TURN server is
  configured. See [Section 12](#12-real-time-communication).
- **18–24.** Offer, answer and ICE candidates are relayed verbatim. The server
  stamps who sent each message and forwards the opaque `payload`.
- **25.** Once ICE succeeds, media flows directly between the browsers. Nothing
  about the audio or video passes through the backend.

## 3.9 Flow: screen sharing

```mermaid
sequenceDiagram
    autonumber
    participant U as Presenter
    participant MR as MeetingRoom
    participant IM as useInterviewMode
    participant SS as useScreenShare
    participant BR as Browser screen picker
    participant RTC as RTCPeerConnection
    participant SIG as /ws/signal
    participant PEER as Other browser

    U->>MR: clicks Present
    alt someone else is already presenting
        MR->>U: window.confirm("Take over presenting?")
    end
    MR->>IM: suppressBriefly(4000)
    Note over IM: The screen picker steals focus from the page.<br/>Without this, Interview Mode would record the<br/>app's OWN dialog as leaving the tab.
    MR->>SS: startPresenting()
    SS->>BR: navigator.mediaDevices.getDisplayMedia({video:true})
    alt user cancels the picker
        BR-->>SS: NotAllowedError
        SS->>SS: treated as CANCEL, not an error -<br/>no message is shown
    else user picks a window
        BR-->>SS: MediaStream with one video track
        SS->>RTC: addTrack(screenTrack)  -- ADDED, not swapped
        Note over RTC: An ADDITIONAL track, deliberately.<br/>replaceTrack would hide the camera, and the<br/>signer must stay visible while anyone presents.
        RTC->>RTC: onnegotiationneeded fires
        RTC->>SIG: {type:"offer", payload: new SDP}
        SIG->>PEER: offer -> answer -> renegotiated
        SS->>SIG: {type:"presentation-start", payload:{presenterId}}
        SIG->>PEER: presentation-start
        PEER->>PEER: route the new track by stream id;<br/>stage switches to presenting layout
        SS->>SS: screenTrack.addEventListener('ended', stop)
        Note over SS: Catches the BROWSER'S OWN "Stop sharing" bar,<br/>which does not go through our button at all.
    end

    U->>SS: Stop presenting  (our button, or the browser bar, or leaving)
    SS->>RTC: removeScreenSender()
    SS->>SIG: {type:"presentation-stop"}
    SIG->>PEER: presentation-stop
    PEER->>PEER: stage returns to the normal layout
```

**Step by step.**

- **4.** Interview Mode is suppressed for four seconds around the picker. The
  picker is the application's own dialog; recording it as a violation would
  punish a candidate for using a feature the app offers.
- **7–8.** A cancelled picker throws `NotAllowedError` — the same error as a
  denied permission. `useScreenShare` treats it as a cancel and shows nothing,
  because an error message for "I changed my mind" is wrong.
- **10–11.** The screen is an **additional** track. This is the single most
  important choice in this flow: replacing the camera track would remove the
  signer from the call at exactly the moment someone is presenting something to
  discuss.
- **12–14.** Adding a track fires `onnegotiationneeded`, and the perfect-negotiation
  logic in `useWebRTC` runs a real offer/answer exchange.
- **17.** The `ended` event on the track is what catches the browser's own
  "Stop sharing" floating bar, which never touches our UI.

## 3.10 Flow: Interview Mode violation reporting

```mermaid
sequenceDiagram
    autonumber
    participant C as Candidate browser
    participant IM as useInterviewMode
    participant API as POST .../focus-events
    participant DB as focus_events
    participant H as Host browser
    participant GET as GET .../focus-events

    Note over C,IM: Host has switched the mode on.<br/>It lives on the MEETING RECORD, so a reload<br/>does not escape it.

    IM->>C: show acknowledgement dialog
    C->>IM: clicks Acknowledge
    Note over IM: The click is also the USER GESTURE the browser<br/>requires before fullscreen is allowed - which is<br/>why enforcement starts on the click, not on mount.
    IM->>C: requestFullscreen()
    IM->>C: navigator.keyboard.lock(['Escape', ...])  -- Chromium only

    C->>C: user switches tab / clicks another window
    C-->>IM: visibilitychange (hidden) or window blur
    IM->>IM: record start time; awayCount += 1
    IM->>API: {event_type:"blur" | "hidden"}
    API->>DB: INSERT focus_events row
    IM->>C: show BLOCKING overlay

    Note over C: The overlay is not dismissible by clicking away.<br/>The only route out is re-entering fullscreen,<br/>which needs a user gesture.

    C->>C: comes back
    C-->>IM: visibilitychange (visible)
    IM->>API: {event_type:"return", duration_away_ms: 4200}
    API->>DB: INSERT focus_events row WITH the duration
    C->>IM: clicks "Return to the meeting"
    IM->>C: requestFullscreen() again

    loop every 5 s, host only
        H->>GET: GET /api/meetings/{code}/focus-events
        GET->>GET: host-only check (403 otherwise)
        GET->>DB: SELECT ... WHERE meeting_id = ?
        GET-->>H: FocusSummary {total_events, away_count,<br/>events[], by_participant[]}
    end
```

**Step by step.**

- **1.** The mode lives on `meetings.is_interview_mode`, not in browser state.
  Reloading the page is therefore not a way out.
- **3–4.** The acknowledgement click does double duty. Browsers refuse
  `requestFullscreen()` unless it follows a user gesture, so enforcement cannot
  begin on mount.
- **5.** Keyboard Lock captures Escape so it does not silently exit fullscreen.
  It is **Chromium-only**; `useInterviewMode` checks `navigator.keyboard?.lock`
  and reports `reducedEnforcement` honestly rather than pretending.
- **6–10.** Both `visibilitychange` and `blur` are watched: tab-switching fires
  the first, clicking another application fires the second.
- **8.** Each event is POSTed immediately, so a candidate who switches tab and
  then refreshes the page is still in the host's log.
- **12–13.** The `return` event is the first moment the duration is known, which
  is why `duration_away_ms` is set on `return` rows only. A 300 ms notification
  steal and a two-minute absence must be distinguishable.
- **16–20.** The host polls every five seconds. Polling rather than pushing is
  deliberate: adding a third message type to the inference socket would couple
  attention logging to sign recognition, so a failure in one would take down the
  other.

---

# 4. Technology stack

Every version below is the exact pin from `backend/requirements.txt` or
`frontend/package.json`. Nothing is a range; nothing is "latest".

## 4.1 Backend — Python

| Technology | Version | What it does here | Why this and not the obvious alternative |
|---|---|---|---|
| **Python** | 3.11 | The backend language | Pinned by `backend/Dockerfile` (`python:3.11-slim`) and `scripts/setup.sh`. 3.11 because TensorFlow 2.16 does not support 3.12 at this pin. |
| **FastAPI** | 0.115.6 | REST routers and the three WebSocket endpoints | Chosen over Flask because WebSockets are **native** rather than an extension, and over Django because no admin, ORM-first or template layer is needed. Also generates the OpenAPI spec this document's endpoint tables were extracted from. |
| **Uvicorn** (`[standard]`) | 0.34.0 | ASGI server | The reference ASGI server. The `[standard]` extra brings `uvloop` and `httptools`. Gunicorn alone cannot serve ASGI WebSockets. |
| **websockets** | 14.1 | WebSocket protocol implementation under Uvicorn | Pulled in explicitly rather than left implicit, so the version is pinned. |
| **python-multipart** | 0.0.20 | Parses `application/x-www-form-urlencoded` | Required by `POST /api/auth/login`, which uses `OAuth2PasswordRequestForm`. |
| **Pydantic** | 2.10.4 | Request/response validation; the single definition of the wire format | v2 rather than v1 for the Rust-based core and `model_validate`/`model_copy`. Everything in `backend/app/schemas/` is Pydantic. |
| **pydantic-settings** | 2.7.0 | Typed reading of `.env` | Chosen over raw `os.environ` so a typo like `CONFIDENCE_THRESHOLD=0.8O` fails loudly at boot rather than silently at 2 a.m. `backend/app/config.py` is the only module that reads the environment. |
| **python-dotenv** | 1.0.1 | Loads the `.env` file | A pydantic-settings dependency, pinned explicitly. |
| **email-validator** | 2.2.0 | Backs Pydantic's `EmailStr` | Without it `EmailStr` raises at import. |
| **SQLAlchemy** | 2.0.36 | ORM and connection pooling | Chosen over raw SQL so the schema has one typed definition in Python, and over Django's ORM because we are not using Django. 2.x `Mapped[...]` style throughout `backend/app/models/`. |
| **PyMySQL** | 1.1.1 | Pure-Python MySQL driver | Chosen over `mysqlclient` because that needs a C compiler and MySQL headers at install time — a real obstacle on a student laptop. |
| **cryptography** | 44.0.0 | Crypto primitives for JWT signing | Required by `python-jose[cryptography]`. |
| **python-jose** (`[cryptography]`) | 3.3.0 | Creates and verifies JWTs | Chosen over PyJWT because FastAPI's own tutorial uses it, so the code matches the documentation an examiner is likeliest to check against. |
| **passlib** | 1.7.4 | Password hashing interface | Provides `CryptContext`, which supports `deprecated="auto"` so old hashes can be marked for rehash on next login without a migration. |
| **bcrypt** | 4.0.1 | The actual hashing algorithm | Deliberately slow — that is the feature. Chosen over SHA-256 because a fast hash is exactly what an attacker with a stolen database wants. Pinned at 4.0.1 because passlib 1.7.4 reads `bcrypt.__about__.__version__`, which was removed in bcrypt 4.1. |
| **TensorFlow** | 2.16.2 | Loads and runs the three Keras models | Chosen over PyTorch for Keras 3's one-line `.keras` save/load, and because the project constraint is CPU-only training where the two are comparable. |
| **NumPy** | 1.26.4 | All numeric work: normalisation, feature vectors, audio buffers | Held at 1.x deliberately: TensorFlow 2.16.2 and `ctranslate2` both break against NumPy 2.x at these pins. |
| **MediaPipe** | 0.10.14 | **Offline landmark extraction only** | Used by `ml/scripts/extract_landmarks_images.py` and `extract_landmarks_video.py` to turn dataset images into landmarks. At **runtime** MediaPipe runs in the browser instead; this Python copy never serves a request. |
| **OpenCV** | 4.10.0.84 | Reads dataset images and video frames offline | Only in `ml/scripts/`. Never imported by the running server. |
| **scikit-learn** | 1.5.2 | Train/val/test splitting, the classification report and confusion matrices | Chosen over hand-written metric code because `classification_report` is the standard an examiner will recognise. |
| **pandas** | 2.2.3 | Holds the extracted-landmark tables during preprocessing | Only in `ml/scripts/`. |
| **faster-whisper** | 1.0.3 | The fallback speech-to-text engine | Chosen over `openai-whisper` because it is a CTranslate2 reimplementation that is several times faster on CPU and supports int8 quantisation, which matters on a laptop. |
| **CTranslate2** | 4.8.1 | The inference engine under faster-whisper | Pinned at 4.8.1 after confirming with `pip install --dry-run` that it keeps NumPy at 1.26.4. |
| **reportlab** | 4.2.5 | Builds the transcript PDF | Chosen over `weasyprint` because it has no system library dependencies (no Pango, no Cairo). |
| **matplotlib** | 3.9.2 | Renders confusion matrices to `docs/images/` | Offline only. |
| **seaborn** | 0.13.2 | Heatmap styling for the confusion matrices | Offline only. |
| **kaggle** | 1.6.17 | Dataset download CLI | Used by `ml/scripts/download_datasets.py`. Needs the user's own Kaggle API token. |
| **tqdm** | 4.67.1 | Progress bars during extraction, which takes tens of minutes | Offline only. |
| **pytest** | 8.3.4 | The backend test runner | 258 tests. |
| **pytest-asyncio** | 0.25.0 | Lets `async def` tests run | Needed for the WebSocket tests. |
| **httpx** | 0.28.1 | Backs FastAPI's `TestClient` | Required by `fastapi.testclient` at this version. |

## 4.2 Frontend — JavaScript

| Technology | Version | What it does here | Why this and not the obvious alternative |
|---|---|---|---|
| **React** | 18.3.1 | The whole UI | 18 rather than 19 because `@mediapipe/tasks-vision` and the Testing Library pins in use are known-good against 18. StrictMode's deliberate double-mounting in development is why several hooks carry `cancelled` flags. |
| **react-dom** | 18.3.1 | React's DOM renderer | — |
| **react-router-dom** | 7.18.2 | Client-side routing for the nine routes | Chosen over hand-rolled `history` handling because route guards (`RequireAuth`) and `:code` parameters are the whole navigation model. |
| **Vite** | 7.3.6 | Dev server and production bundler | Chosen over Create React App (unmaintained) and webpack (slower, much more config). Its `import.meta.env.VITE_*` convention is how the frontend reads configuration. |
| **@vitejs/plugin-react** | 5.1.1 | JSX transform and hot module replacement | — |
| **@mediapipe/tasks-vision** | 0.10.18 | **The hand tracker, in the browser** | This is the core technical choice of the project. Runs as WebAssembly on the user's own machine, so video never leaves it. Chosen over TensorFlow.js handpose because MediaPipe's `HandLandmarker` has a `VIDEO` running mode that tracks across frames rather than re-detecting each one — and jittery landmarks become jittery predictions. |
| **Tailwind CSS** | 3.4.17 | All styling | Chosen over CSS modules or styled-components because the design system is a fixed palette and a fixed set of radii and heights, which is exactly what a config-driven utility framework expresses well. `tailwind.config.js` holds the two palettes with their contrast ratios recorded. |
| **PostCSS** | 8.5.26 | Runs Tailwind and autoprefixer | — |
| **autoprefixer** | 10.4.20 | Adds vendor prefixes | — |
| **ESLint** | 8.57.1 | Static analysis | Configured by `frontend/.eslintrc.cjs`, with `no-use-before-define` as an **error**. This is not decorative: eleven use-before-define errors once shipped and crashed the meeting room, because the script existed with no config file and `vite build` performs no scope analysis. |
| **eslint-plugin-react** | 7.37.2 | React rules, including JSX-aware variable usage | — |
| **eslint-plugin-react-hooks** | 4.6.2 | `rules-of-hooks` and `exhaustive-deps` | — |
| **eslint-plugin-react-refresh** | 0.4.16 | Warns when a module exports non-components | Advisory; five warnings remain by design. |
| **Vitest** | 2.1.9 | Frontend test runner | Chosen over Jest because it shares Vite's transform pipeline, so the tests see the same module graph the app does with no second build config. |
| **jsdom** | 25.0.1 | A DOM implementation for Node | Lets the render tests mount real pages without a browser. |
| **@testing-library/react** | 16.1.0 | `render` and queries by accessible role | Chosen over shallow rendering because querying by role is what proves the accessible labels exist. |
| **@testing-library/dom** | 10.4.0 | Query engine under the above | — |
| **@vitest/coverage-v8** | 2.1.9 | Coverage reporting | Installed; no coverage threshold is configured. |
| **@types/react**, **@types/react-dom** | 18.3.17, 18.3.5 | Type definitions for editor support | The project is plain JavaScript, not TypeScript. |

## 4.3 Infrastructure and external services

| Technology | Version | What it does here | Why this and not the alternative |
|---|---|---|---|
| **MySQL** | **9.7.1** (live server, measured with `SELECT VERSION()`) | The database | Chosen over PostgreSQL because it was the locked project stack; over SQLite for production because concurrent writers need real locking. SQLite remains a documented one-line fallback via `DATABASE_URL`. `docker-compose.yml` pins `mysql:8.4`, which differs from the live server — see issue K-7. |
| **ffmpeg** | not pinned — whatever is on `PATH` | Decodes browser Opus/WebM audio to 16 kHz PCM for Whisper | Invoked as a **subprocess**, not a library. If absent, `/ws/transcribe` closes with `FFMPEG_MISSING` and Whisper is simply unavailable. Measured version on this machine: see Appendix A. |
| **nginx** | 1.27-alpine | Serves the built frontend in the Docker image | `frontend/Dockerfile` runtime stage. |
| **Node** | 20-alpine | Builds the frontend in Docker | `frontend/Dockerfile` build stage. |
| **Google STUN** | n/a (a service) | Lets each browser discover its own public address | Free and needs no account. See [Section 8](#8-external-apis-services-and-browser-apis). |
| **Google Fonts** | n/a (a CDN) | Serves Roboto and Material Symbols Outlined | Loaded from `frontend/index.html`. The icon font uses `display=block` so the control bar never briefly renders the literal ligature names. |
| **Web Speech API** | browser built-in | Speech recognition engine 1 | Chromium-only in practice. **Sends audio to Google.** |
| **Hugging Face Hub** | n/a (a service) | One-time download of the faster-whisper `base` weights | Cached into `ml/models/whisper/`. `HF_HUB_DISABLE_XET=1` is required — the Xet backend stalls at 0 bytes. |

---

# 5. Repository structure

```
BridgeTalk/
│
├── .env.example                 Template for .env. Placeholders only, never real secrets.
├── .eslintrc.cjs → frontend/    (lives under frontend/, see below)
├── docker-compose.yml           Three services: MySQL 8.4, backend, frontend. One volume.
│
├── CLAUDE.md                    Context for future AI coding sessions: locked stack, hard
│                                constraints, phase status, and the four commands to run.
├── README.md                    The long teaching document: architecture, ML explained from
│                                zero, API reference, troubleshooting, limitations.
├── PROGRESS.md                  Build log. What was done, what broke, what each fix was.
├── ARCHITECTURE.md              Architecture notes predating the interface rebuild.
├── BridgeTalk_Master_Prompt_v2.md  The original build specification.
├── REVIEW_CHEATSHEET.md         Condensed facts for the review.
├── REVIEW_DEMO.md               A scripted demo walk-through.
│
├── backend/
│   ├── Dockerfile               python:3.11-slim, installs requirements, runs uvicorn on 8000.
│   ├── requirements.txt         30 pinned Python packages.
│   ├── app/
│   │   ├── __init__.py          Holds __version__, reported by /health.
│   │   ├── main.py              FastAPI app, CORS, router registration, the lifespan startup
│   │   │                        that loads all three models and Whisper, and GET /health.
│   │   ├── config.py            pydantic-settings. THE ONLY module that reads the environment.
│   │   │                        Also resolve_path(), which makes .env paths repo-relative.
│   │   ├── database.py          SQLAlchemy engine + SessionLocal + init_db().
│   │   │
│   │   ├── api/                 REST routers — thin: validate, delegate, serialise.
│   │   │   ├── auth.py          register, login (form), login/json, me.          4 endpoints
│   │   │   ├── meetings.py      create, history, get, join, leave, end,
│   │   │   │                    interview-mode, focus-events (POST + GET),
│   │   │   │                    plus generate_meeting_code().                     9 endpoints
│   │   │   └── transcripts.py   create, get, export (.txt), export.pdf.           4 endpoints
│   │   │
│   │   ├── ws/                  The three real-time endpoints.
│   │   │   ├── inference.py     /ws/predict/{code}. Landmarks in, predictions out; also the
│   │   │   │                    caption broadcast and persistence. The largest ws file.
│   │   │   ├── signaling.py     /ws/signal/{code}. Relays 6 WebRTC message types verbatim.
│   │   │   ├── transcribe.py    /ws/transcribe/{code}. Opus in, text out. Contains
│   │   │   │                    StreamDecoder, UtteranceBuffer and WhisperTranscriber.
│   │   │   ├── captions.py      THE caption protocol: build_caption_event, validate_caption,
│   │   │   │                    persist_final_caption. Shared by sign and speech.
│   │   │   └── connection_manager.py  Who is connected to which meeting, per channel.
│   │   │
│   │   ├── ml/
│   │   │   ├── normalization.py THE canonical normalisation. Must agree with
│   │   │   │                    frontend/src/utils/landmarkUtils.js to 1e-6.
│   │   │   ├── predictor.py     SignPredictor: loads a .keras once, guards the normalisation
│   │   │   │                    version, compiles a tf.function. Three instances.
│   │   │   ├── smoothing.py     PredictionSmoother: confidence gate, majority vote, cooldown,
│   │   │   │                    neutral reset. Plus SmoothingConfig and NEUTRAL_LABEL.
│   │   │   └── sequence.py      SequenceBuffer: the 30-frame sliding window for word signs.
│   │   │
│   │   ├── models/              SQLAlchemy ORM — the only place that knows SQL.
│   │   │   ├── user.py          User, UserRole enum.
│   │   │   ├── meeting.py       Meeting (with the is_active property), MeetingParticipant,
│   │   │   │                    FocusEvent, FocusEventType enum.
│   │   │   └── transcript.py    Transcript, TranscriptSource enum.
│   │   │
│   │   ├── schemas/             Pydantic — the only place defining the wire format.
│   │   │   ├── user.py          UserRegister, UserLogin, UserPublic, Token, UserRole.
│   │   │   ├── meeting.py       MeetingCreate, MeetingPublic, MeetingDetail, MeetingSummary,
│   │   │   │                    MeetingJoinResponse, ParticipantPublic.
│   │   │   ├── transcript.py    TranscriptCreate, TranscriptPublic, TranscriptSource.
│   │   │   └── focus.py         FocusEventCreate, FocusEventPublic, FocusSummary,
│   │   │                        ParticipantViolations, InterviewModeUpdate.
│   │   │
│   │   └── core/
│   │       ├── security.py      bcrypt hashing, JWT create/decode. CryptContext lives here.
│   │       └── deps.py          get_current_user, DbSession, CurrentUser. The auth dependency.
│   │
│   └── tests/                   258 passing, 2 skipped. See Section 17.
│       ├── conftest.py          In-memory SQLite fixtures: db_session, client, registered_user,
│       │                        auth_headers, second_headers, meeting.
│       ├── test_auth.py                      23 tests
│       ├── test_meetings.py                  40 tests
│       ├── test_transcripts.py                5 tests
│       ├── test_captions.py                   9 tests
│       ├── test_websockets.py                21 tests
│       ├── test_focus_events.py              18 tests
│       ├── test_schema_parity.py              4 tests
│       ├── test_smoothing.py                 28 tests
│       ├── test_normalization_parity.py      20 tests
│       ├── test_sequence_buffer.py           11 tests
│       ├── test_dynamic_mode.py              12 tests
│       ├── test_dynamic_augmentation.py      12 tests
│       ├── test_isl_preprocessing.py         11 tests
│       ├── test_include_dataset.py           19 tests
│       └── test_transcribe.py                27 tests (2 skipped)
│
├── frontend/
│   ├── Dockerfile               node:20-alpine build stage → nginx:1.27-alpine runtime.
│   ├── index.html               The SPA shell. Loads Roboto and Material Symbols from Google
│   │                            Fonts; icon font uses display=block deliberately.
│   ├── package.json             4 runtime dependencies, 16 dev. All exact pins.
│   ├── vite.config.js           Vite + React plugin.
│   ├── vitest.config.js         jsdom environment, setupFiles, test include pattern.
│   ├── .eslintrc.cjs            no-use-before-define = error. Explains why, at length.
│   ├── tailwind.config.js       The two palettes with contrast ratios, named radii, named
│   │                            heights, caption font sizes, keyframes.
│   ├── postcss.config.js        Tailwind + autoprefixer.
│   │
│   ├── public/models/           MediaPipe assets, served from our own origin (gitignored).
│   │   ├── hand_landmarker.task     7,819,105 bytes. The hand-tracking model.
│   │   └── wasm/                    4 files, ~19 MB. The WebAssembly runtime.
│   │
│   └── src/
│       ├── main.jsx             ReactDOM.createRoot, StrictMode, imports index.css.
│       ├── App.jsx              9 routes, RequireAuth, PublicOnly, ErrorBoundary,
│       │                        ToastProvider.
│       ├── index.css            Tailwind layers, the Material Symbols class, focus rings for
│       │                        both palettes, .btn/.card component classes, reduced-motion.
│       │
│       ├── pages/
│       │   ├── Login.jsx            Login AND register, driven by an initialMode prop.
│       │   ├── Home.jsx             The landing page: new meeting, join by code, recents.
│       │   ├── Lobby.jsx            Pre-join: preview, mic meter, devices, will-sign.
│       │   ├── MeetingRoom.jsx      The meeting. The largest file in the project.
│       │   ├── MeetingEnded.jsx     Post-call page.
│       │   ├── History.jsx          Searchable meeting list.
│       │   ├── Transcript.jsx       One meeting's transcript, filtered and searchable.
│       │   └── SignDetection.jsx    Standalone model check at /detect.
│       │
│       ├── components/
│       │   ├── ui/                  The design system.
│       │   │   ├── Icon.jsx             Material Symbols ligature, always aria-hidden.
│       │   │   ├── Avatar.jsx           Initial in a circle; colour hashed from the name.
│       │   │   ├── IconButton.jsx       Round button, CSS tooltip + accessible label.
│       │   │   ├── Dialog.jsx           Modal: focus moved in, restored out, Tab trapped.
│       │   │   ├── Menu.jsx             Menu, MenuItem, MenuDivider, MenuHeader.
│       │   │   ├── TextField.jsx        Outlined field with a floating label.
│       │   │   ├── Select.jsx           Native <select>, labelled.
│       │   │   ├── ToastHost.jsx        ToastProvider + useToast. Deduplicates.
│       │   │   ├── States.jsx           Spinner, LoadingState, SkeletonRow, EmptyState,
│       │   │   │                        ErrorState, FormError.
│       │   │   ├── TopBar.jsx           The 64 px bar + SubPageTopBar.
│       │   │   ├── Logo.jsx             Inline-SVG mark + wordmark.
│       │   │   ├── useDismiss.js        Escape + outside-pointerdown, shared by Menu/Dialog.
│       │   │   └── index.js             Barrel export; pages import from here.
│       │   │
│       │   ├── meeting/             Meeting-room-specific pieces.
│       │   │   ├── Stage.jsx            Tile layout: alone / two / presenting.
│       │   │   ├── MeetingTile.jsx      One tile: video, name, mute icon, speaking ring.
│       │   │   ├── CaptionRail.jsx      The 140 px caption area, last 3 lines.
│       │   │   ├── ControlBar.jsx       The 80 px bar, three zones, centre pinned.
│       │   │   ├── SidePanel.jsx        The 360 px slide-in shell.
│       │   │   ├── DetailsPanel.jsx     Title, code, joining link, copy button.
│       │   │   ├── PeoplePanel.jsx      Participants with mic/camera state.
│       │   │   ├── LiveTranscriptPanel.jsx  Persisted rows + TXT/PDF buttons.
│       │   │   └── SettingsDialog.jsx   Three tabs, applied immediately.
│       │   │
│       │   ├── HandOverlayCanvas.jsx    Draws the 21-point skeleton on a <canvas>.
│       │   ├── SignDetectionPanel.jsx   The prediction panel used by /detect.
│       │   ├── RecognitionModeToggle.jsx  Mode switch used by /detect.
│       │   ├── InterviewModeDialog.jsx  The acknowledgement dialog.
│       │   ├── InterviewModeOverlay.jsx The blocking overlay.
│       │   ├── DebugOverlay.jsx         The ?debug=1 panel.
│       │   └── ErrorBoundary.jsx        Class component. Catches render errors app-wide.
│       │
│       ├── hooks/
│       │   ├── useHandLandmarker.js     Creates the MediaPipe HandLandmarker; exposes detect().
│       │   ├── useSignSocket.js         /ws/predict with exponential backoff + jitter.
│       │   ├── useSignCaptions.js       Movement segmentation. Decides where a word starts/ends.
│       │   ├── useSpeechCaptions.js     Drives whichever speech provider is selected.
│       │   ├── useCaptionStore.js       The live caption list, keyed by segmentId. newSegmentId().
│       │   ├── useWebRTC.js             RTCPeerConnection, perfect negotiation, screen routing.
│       │   ├── useScreenShare.js        getDisplayMedia as an additional track.
│       │   ├── useInterviewMode.js      visibilitychange + blur + fullscreen + keyboard lock.
│       │   ├── useMediaDevices.js       enumerateDevices for cameras, mics and speakers.
│       │   ├── useMicLevel.js           Web Audio AnalyserNode; time-domain RMS.
│       │   ├── useMeetingPreferences.js localStorage per user id, with sanitising.
│       │   └── useClock.js              Current time, aligned to the minute boundary.
│       │
│       ├── services/
│       │   ├── api.js                   THE only module that calls fetch. Token storage,
│       │   │                            ApiError, and the WebSocket URL builders.
│       │   ├── devicePreferences.js     sessionStorage, never the URL.
│       │   └── stt/
│       │       ├── SttProvider.js       The interface both engines implement.
│       │       ├── WebSpeechProvider.js Browser SpeechRecognition, with bounded restarts.
│       │       ├── WhisperProvider.js   MediaRecorder → /ws/transcribe.
│       │       └── index.js             PROVIDERS registry, resolveProvider, LANGUAGES.
│       │
│       ├── config/recognition.js        EVERY recognition threshold, in one file.
│       ├── context/AuthContext.jsx      user, loading, login, register, logout.
│       ├── utils/
│       │   ├── landmarkUtils.js         The JS normalisation. MUST match normalization.py.
│       │   └── formatters.js            Dates, durations, meeting-code parsing.
│       └── test/
│           ├── setup.js                 Browser API stubs: getUserMedia, MediaStream,
│           │                            RTCPeerConnection, WebSocket, AudioContext, srcObject.
│           ├── renderPage.jsx           Mounts a page with its providers; the API stub.
│           └── pages.test.jsx           13 tests: all 8 routes render + lobby/meeting wiring.
│
├── ml/
│   ├── README.md                Notes on the ML pipeline.
│   ├── data/raw/                Downloaded datasets                      (gitignored)
│   ├── data/processed/          Extracted landmark tables                (gitignored)
│   ├── models/
│   │   ├── static_model.keras            753 KB. Model A, ASL letters.
│   │   ├── isl_model.keras               948 KB. Model C, ISL letters.
│   │   ├── dynamic_model.keras           5.1 MB. Model B, ISL words.
│   │   ├── labels.json / labels_isl.json / labels_dynamic.json
│   │   │                                 classes + label_to_index per model.
│   │   ├── metadata.json / isl_metadata.json / dynamic_metadata.json
│   │   │                                 architecture, hyperparameters, metrics, sample counts.
│   │   ├── dataset_manifest.json         ASL: source, licence posture, classes, balancing, split.
│   │   ├── isl_dataset_manifest.json     ISL letters: same shape. See issue K-5.
│   │   ├── dynamic_manifest.json         ISL words: INCLUDE citation, split strategy. See K-6.
│   │   ├── evaluation_report.json        Model A on test: top-1, top-3, per-class, confusion.
│   │   ├── isl_evaluation_report.json    Model C, plus an honest_summary block.
│   │   ├── dynamic_evaluation_report.json Model B on test.
│   │   ├── continuous_evaluation_report.json  Word error rate on a continuous stream.
│   │   ├── gate_measurement.json         Accuracy of accepted predictions AND idle
│   │   │                                 false-positive rates. The most important artefact.
│   │   ├── inference_path_report.json    End-to-end accuracy and median latency per model.
│   │   ├── training_history.json / isl_training_history.json /
│   │   │   dynamic_training_history.json  Per-epoch loss and accuracy.
│   │   └── whisper/                      faster-whisper base cache          (gitignored)
│   │
│   └── scripts/
│       ├── download_datasets.py          Verifies what is on disk; --verify mode.
│       ├── extract_landmarks_images.py   MediaPipe over a directory of images.
│       ├── extract_landmarks_video.py    MediaPipe over video clips (INCLUDE/WLASL).
│       ├── preprocess.py                 Balance, split, augment → static/ISL training sets.
│       ├── preprocess_dynamic.py         The same for sequences, with the transition class.
│       ├── train_static.py               Trains Model A and Model C (the MLPs).
│       ├── train_dynamic.py              Trains Model B (the BiLSTM).
│       ├── evaluate.py                   Classification report + confusion matrix PNG.
│       ├── evaluate_continuous.py        Word error rate on a synthesised continuous stream.
│       ├── measure_gates.py              Produces gate_measurement.json. Measures the
│       │                                 confidence/margin gates AND idle false positives.
│       ├── test_inference_path.py        Feeds held-out samples through the live code path.
│       ├── test_realtime.py              Live webcam check. Writes NO training data.
│       └── record_eval_clip.py           Records an evaluation clip. Writes NO training data.
│
├── database/
│   ├── schema.sql               The authoritative human-readable schema. Idempotent.
│   ├── seed.sql                 Two demo users and the DEMO-01 meeting.
│   └── migrations/
│       ├── 001_interview_mode_enforcement.sql   Adds interview_mode_started_at,
│       │                                        duration_away_ms, the 'return' enum value.
│       └── 002_caption_segments.sql             Adds transcripts.segment_id and its
│                                                UNIQUE (meeting_id, segment_id) index.
│
├── docs/
│   ├── api.md                   Hand-written API notes.
│   ├── BridgeTalk_Project_Documentation.md   THIS FILE.
│   └── images/                  Confusion matrices, diagrams, screenshots.
│
└── scripts/
    ├── setup.sh / setup.bat     Creates .venv, installs Python + npm deps, downloads
    │                            hand_landmarker.task, copies the MediaPipe WASM runtime.
    ├── run_backend.sh / .bat    uvicorn app.main:app --app-dir backend --reload
    └── run_frontend.sh / .bat   npm run dev
```

---

# 6. Frontend

## 6.1 What the frontend is

A **single-page application** (SPA): one HTML file is served, and JavaScript
swaps the visible content as you navigate, instead of the server sending a new
page each time. Written in **React** (a library for building UIs from
components) with **react-router-dom** handling the URLs.

All source is plain JavaScript with JSX, not TypeScript.

## 6.2 Routes

`frontend/src/App.jsx` declares **10 `<Route>` elements**: nine that render a
page, plus a catch-all that redirects unknown URLs to `/`.

Two route guards wrap them:

- **`RequireAuth`** — renders a loading state while `GET /api/auth/me` is in
  flight, then either the page or a redirect to `/login`. The loading branch
  matters: without it, every page reload flashes the login screen and a
  signed-in user gets bounced to `/login` and back.
- **`PublicOnly`** — the reverse. Renders `Login` when signed out, redirects to
  `/` when signed in. Returns `null` rather than a spinner while loading,
  because this resolves in a few milliseconds from `localStorage` and a spinner
  that flashes for one frame reads as a glitch.

| # | URL | Component file | Purpose | Login required | Backend endpoints used | WebSockets used | Main interface elements |
|---|---|---|---|---|---|---|---|
| 1 | `/login` | `pages/Login.jsx` (`initialMode="login"`) | Sign in | No — redirects to `/` if already signed in | `POST /api/auth/login/json` | none | 400 px card, email field, password field with show/hide, full-width primary button, link to register |
| 2 | `/register` | `pages/Login.jsx` (`initialMode="register"`) | Create an account | No — redirects to `/` if already signed in | `POST /api/auth/register` | none | The above plus full name, confirm password, and a "How will you mostly take part?" select |
| 3 | `/` | `pages/Home.jsx` | Landing page | **Yes** | `POST /api/meetings`, `GET /api/meetings/history`, `GET /api/meetings/{code}` | none | TopBar; 44 px heading; "New meeting" button with a two-item menu; "Enter a code or link" field with a Join button disabled until there is text; "Recent meetings" column of up to 5 cards; a dialog showing the code and link with a copy button |
| 4 | `/history` | `pages/History.jsx` | All past meetings | **Yes** | `GET /api/meetings/history?q=` | none | TopBar; "Meeting history" heading; search field (debounced 300 ms); clickable rows with title, date, duration, caption count, participant avatars, Interview-mode badge, "View transcript" button; skeleton rows while loading; "Load more" |
| 5 | `/history/:code` | `pages/Transcript.jsx` | One meeting's transcript | **Yes** (and must be a participant — enforced server-side) | `GET /api/meetings/{code}`, `GET /api/transcripts/{id}`, `GET /api/transcripts/{id}/export`, `.../export.pdf`, `GET /api/meetings/{code}/focus-events` (host only) | none | SubPageTopBar with a back arrow; date, start–end time, duration, code, participant avatars; Download TXT and Download PDF; filter chips All/Sign/Speech; participant select; search field that highlights matches; grouped entries; a host-only collapsible "Interview mode log" |
| 6 | `/lobby/:code` | `pages/Lobby.jsx` | Pre-join check | **Yes** | `GET /api/meetings/{code}`, `POST /api/meetings/{code}/join` | none | Logo only — **no account menu**, per the specification; mirrored 16∶9 preview; name top-left; round mic/camera buttons bottom-centre; five-bar mic level meter bottom-left; three device selects; "Ready to join?", title, code, who is already here; "I will be signing in this meeting"; Join now; Back to home; per-error permission instructions with a Try again button |
| 7 | `/meeting/:code` | `pages/MeetingRoom.jsx` | The meeting | **Yes** | `POST /api/meetings/{code}/join`, `GET /api/meetings/{code}`, `POST .../leave`, `POST .../end`, `PATCH .../interview-mode`, `POST .../focus-events`, `GET /api/transcripts/{id}`, `GET /api/transcripts/{id}/export(.pdf)` | **`/ws/predict/{code}`**, **`/ws/signal/{code}`**, **`/ws/transcribe/{code}`** (only when Whisper is the engine) | Full-window dark layout, no page scroll: Stage / CaptionRail / ControlBar. Control bar: clock + code, then mic, camera, CC, sign, present, more, red leave pill, then three panel buttons. Three 360 px slide-in panels, closed by default. Settings dialog with three tabs. Interview-mode dialog and overlay. `?debug=1` overlay |
| 8 | `/ended/:code` | `pages/MeetingEnded.jsx` | After leaving | **Yes** | `GET /api/meetings/{code}` | none | Light theme, centred: "You left the meeting" or "The meeting has ended"; Rejoin (hidden once the meeting is over) and Return to home screen; a card offering View transcript |
| 9 | `/detect` | `pages/SignDetection.jsx` | Check a model without a second person | **Yes** | none | **`/ws/predict/DEMO`** | TopBar; camera with the skeleton overlay; the prediction panel with label, confidence bar, mode toggle and model status |
| 10 | `*` | — | Unknown URL | n/a | none | none | Redirects to `/` |

## 6.3 Shared UI components

In `frontend/src/components/ui/`, exported through `index.js` so a page never
reaches into an individual file and cannot quietly grow its own button.

| Component | What it does | The detail worth knowing |
|---|---|---|
| `Icon` | Renders one Material Symbols glyph | The icon's **name is its text content** — Material Symbols is a ligature font, so the string `mic` becomes the microphone glyph. Always `aria-hidden`, because otherwise a screen reader announces a mute button as "mic mic". |
| `Avatar` | A person's initial in a coloured circle | The colour is a **djb2 hash of the name** over an 8-colour palette, so the same person is the same colour on every page with no extra database column and no extra API field. |
| `IconButton` | A round icon button | Carries **both** a tooltip and an accessible label, from one `label` prop so they cannot drift apart. The tooltip is CSS (`group-hover`), not the native `title` attribute — native titles take about a second, cannot be styled to read on the dark control bar, and never appear on keyboard focus. The tooltip is `pointer-events-none` so it can never swallow the click it describes. |
| `Dialog` | A modal | Moves focus in on open, restores it on close, and **traps Tab** inside the panel. Also sets `body { overflow: hidden }` and restores it. `closeOnDismiss={false}` is for dialogs that must be answered rather than escaped. |
| `Menu` / `MenuItem` / `MenuDivider` / `MenuHeader` | Dropdown menus | The caller owns the open state and renders the trigger, because the triggers differ too much to generalise (an avatar, a three-dot button, a pill). |
| `useDismiss` | Escape + outside-press handling, shared by Menu and Dialog | Listens for **`pointerdown`**, not `click`: a click fires on release, so a press starting outside and finishing inside would not dismiss. `mousedown` alone would miss touch. |
| `TextField` | Outlined field with a floating label | The label floats when focused **or non-empty**. The second half matters: browser autofill never fires focus, so a float driven by focus alone leaves the label sitting on top of autofilled text. |
| `Select` | A labelled native `<select>` | Native on purpose. A custom listbox would have to reimplement keyboard navigation, type-ahead and the mobile picker — and these are the controls someone reaches for when their microphone is already broken. |
| `ToastHost` | `ToastProvider` + `useToast` | **Deduplicates**: WebRTC and the signalling socket both observe a participant arriving, so a toast whose text is already on screen refreshes that toast's timer instead of stacking a copy. `aria-live="polite"`, never assertive — assertive would interrupt a screen reader mid-caption on the one page where captions are the point. `useToast` returns a no-op outside a provider rather than throwing. |
| `States` | `Spinner`, `LoadingState`, `SkeletonRow`, `EmptyState`, `ErrorState`, `FormError` | One file so every page's "nothing here yet" looks identical. |
| `TopBar` / `SubPageTopBar` | The 64 px bar | Logo linking home, then clock and date (hidden below `sm`), then the avatar opening a menu with name, email, History, Sign recognition check, Sign out. |
| `Logo` / `LogoMark` | BridgeTalk's own mark | Inline SVG — two piers bridged by a line — so it inherits `currentColor` and works on both palettes from one asset. Deliberately not Google's mark, name or font. |

## 6.4 Meeting-specific components

In `frontend/src/components/meeting/`.

| Component | What it does | The detail worth knowing |
|---|---|---|
| `Stage` | Chooses the tile layout | Three layouts: alone (your tile fills), two (the **other person** fills, your video floats bottom-right), presenting (screen fills, cameras in a right-hand strip). "The other person fills the stage" is not cosmetic — when they sign, the hearing user needs their hands as large as possible. The shared screen uses `object-contain`, never `cover`: cropping a screen hides its edges, which is where menus and the thing being pointed at live. |
| `MeetingTile` | One participant | `srcObject` is set in an **effect**, not as a prop — React can only set DOM *attributes* declaratively, so `<video srcObject={...}>` is silently ignored. The identity check before assigning matters too: re-assigning the same stream restarts playback and shows a black frame, and captions cause several re-renders a second. **Only your own tile is mirrored**; mirroring the remote tile would flip the other person's signs, which for a handed language can change which sign is read. |
| `CaptionRail` | The 140 px caption area | Shows the last **three** lines. Keyed by `segmentId`, so a line updates in place. Interim is `#BDC1C6` grey, final is white — the only signal a reader gets that text may still change. Scrolls by assigning `scrollTop` directly, because `scrollIntoView({behavior:'smooth'})` would queue animations faster than they finish at interim rates. |
| `ControlBar` | The 80 px bar | Three zones. The centre group is **absolutely positioned** at the true centre, because the three zones are different widths and `justify-between` would leave the controls off-centre *and shift them* as the clock changes width. Below `sm` the pinning is dropped. |
| `SidePanel` | The 360 px slide-in shell | A **sibling** of the stage, not an overlay, so the stage genuinely shrinks. Floating would be less code but would cover the person who is signing. Below `md` it does overlay, because 360 px of a 700 px window leaves the video unusable. |
| `DetailsPanel` | Title, code, joining link | Clears its copy-confirmation timer on unmount, because the panel unmounts the moment it closes. |
| `PeoplePanel` | Who is here and their device state | Your own state is read directly; the remote state is **inferred** from track presence, so it is labelled "No audio arriving" rather than "Muted" — a dropped network looks identical to a mute button, and claiming to know which would be a lie. |
| `LiveTranscriptPanel` | The running record | Reads **persisted rows**, not the in-memory caption list, so it matches the downloaded file and includes what was said before you joined. Sticks to the bottom as lines arrive **unless** the user has scrolled up to read something. |
| `SettingsDialog` | Three tabs | No Save button: these are settings you change *because something is wrong right now*. The Sign recognition tab reads class counts and accuracy from the **server's own model metadata**, so a model that is not loaded says so and its option is disabled, rather than the UI printing a hardcoded number beside a model that failed to load. |

## 6.5 Hooks

| Hook | Responsibility | The detail worth knowing |
|---|---|---|
| `useHandLandmarker` | Creates the MediaPipe `HandLandmarker`, exposes `detect()` | `runningMode: 'VIDEO'` tracks the hand across frames rather than re-detecting each one, which produces steadier landmarks — and jittery landmarks become jittery predictions. `delegate: 'GPU'`, with MediaPipe falling back to CPU itself. `numHands` is 1 for ASL and 2 otherwise. |
| `useSignSocket` | `/ws/predict` with reconnection | Exponential backoff with up to 30 % **jitter**, capped at 10 s, 12 attempts. Jittered so that if several clients drop at once they do not retry in lockstep and recreate the stampede. Close code **1008** (our policy violation) stops retrying, because a bad token cannot be fixed by trying again. `sendLandmarks` drops frames when `bufferedAmount > 64 KB` — on a slow network, dropping the newest frame beats building a backlog that makes predictions arrive seconds late. |
| `useSignCaptions` | **Decides where a word starts and ends** | The heart of sign captioning. `measureMotion` compares consecutive frames; a movement segment ends after `REST_FRAMES_TO_END_SEGMENT` still frames; a token is committed **once per movement** and not repeated until the hands return to rest. This replaced a time-based cooldown that fired again the moment it expired even though the signer had not moved — the direct cause of "warm warm warm". |
| `useSpeechCaptions` | Drives the selected speech provider | Enabled purely by `micOn && meeting`. Never by a panel toggle. Generates one `segment_id` per utterance. |
| `useCaptionStore` | The live caption list | **Replaces** by `segmentId`, never appends. Capped at `MAX_LIVE_CAPTIONS = 40`, because an hour-long meeting would otherwise hold thousands of entries in React state and re-render all of them several times a second. `newSegmentId()` combines a prefix, `Date.now()` in base 36 and 8 random characters — unique across *participants*, not just within one browser, because the UNIQUE index is on `(meeting_id, segment_id)`. |
| `useWebRTC` | The peer connection | Perfect negotiation (`makingOfferRef`, `ignoreOfferRef`, `politeRef`), `onnegotiationneeded`, ICE candidate queueing until the remote description lands, and screen-track routing by stream id. Exposes `replaceVideoTrack` and `replaceAudioTrack` built on one `replaceTrackOfKind`. |
| `useScreenShare` | `getDisplayMedia` as an **additional** track | `NotAllowedError` is treated as a **cancel, not an error** — a cancelled picker throws the same error as a denied permission, and showing "permission denied" for "I changed my mind" is wrong. Listens for the track's `ended` event to catch the browser's own Stop-sharing bar. |
| `useInterviewMode` | Tab-switch detection and enforcement | Watches `visibilitychange` and `blur`; drives Fullscreen and Keyboard Lock; reports `capabilities` and `reducedEnforcement` honestly. `suppressBriefly(ms)` is what stops the screen picker being logged as a violation. |
| `useMediaDevices` | `enumerateDevices` for cameras, microphones and speakers | Permission must be granted **before** enumerating, or every label is an empty string — a deliberate anti-fingerprinting measure that looks like a bug. Watches `devicechange` so plugging in a headset updates the list. |
| `useMicLevel` | 0–1 loudness for the lobby meter | Time-domain **RMS**, not `getByteFrequencyData` — RMS over the waveform is amplitude, which is what "how loud am I" means. Uses `requestAnimationFrame` so a backgrounded tab stops the analyser. Keyed on the audio **track id**, not the stream object, so toggling the camera does not needlessly close and reopen an AudioContext. Deliberately **not** connected to `context.destination`, which would be a feedback loop. |
| `useMeetingPreferences` | Caption size, engine, language, mode, overlay | `localStorage`, namespaced by user id so two people sharing a laptop do not inherit each other's settings. `sanitise()` discards any value this build does not understand — a stored `recognitionMode: 'words'` from an older build would otherwise be sent to the socket, which would reject every frame. |
| `useClock` | The current time | Aligns its **first** tick to the next real minute boundary, then settles into a 60 s interval. A plain interval drifts: mounting at 10:00:59 would show 10:00 for one second and then always be most of a minute late. Once a minute, not once a second, so it does not re-render the stage for nothing. |

## 6.6 How state is managed

There is **no Redux, MobX or Zustand**. State lives at the level that owns it:

| Scope | Mechanism | What lives there |
|---|---|---|
| **Application-wide** | React Context — `AuthContext` | `user`, `loading`, `login`, `register`, `logout`, `isAuthenticated`. One provider, in `App.jsx`. |
| **Application-wide** | React Context — `ToastProvider` | The toast queue. Inside the router so a meeting-page toast can be raised; outside `<Routes>` so a toast survives a navigation. |
| **Page-level** | `useState` in the page component | `MeetingRoom.jsx` owns `micOn`, `cameraOn`, `captionsVisible`, `signRecognitionOn`, `openPanel`, `settingsOpen`, the meeting record and the transcript rows, and passes them down as props. |
| **Feature-level** | Custom hooks | Each hook above owns its own internal state and exposes a small interface. |
| **Per-meeting, surviving reload** | `sessionStorage` (`services/devicePreferences.js`) | Chosen microphone, speaker and camera; `willSign`; `micOn`/`cameraOn`. Session, not local, so a headset plugged in for one call is not still selected a week later on a machine where it is no longer attached — which presents as a camera that will not start, with no clue why. |
| **Per-user, surviving the tab** | `localStorage` (`useMeetingPreferences`) | Caption size, speech engine, language, recognition mode, hand overlay. |
| **Auth token** | `localStorage`, key `bridgetalk.token` | A documented trade-off: an httpOnly cookie resists XSS, which `localStorage` does not, but needs CSRF protection and **cannot be read by the WebSocket URL builder**, which needs the raw token as a query parameter. |

Every storage access is wrapped in `try`/`catch`, because `localStorage` and
`sessionStorage` throw in a private window with site data blocked — and a
remembered caption size must never be what stops a meeting loading.

## 6.7 Design system

Defined in `frontend/tailwind.config.js` and `frontend/src/index.css`. Two
palettes, because the product genuinely has two environments.

### Colours — outside a meeting (light)

| Token | Hex | Used for | Contrast on its background |
|---|---|---|---|
| `light.bg` | `#FFFFFF` | Page background | — |
| `light.surface` | `#F8F9FA` | Cards, hovers, the auth page background | — |
| `light.text` | `#202124` | Body text | 16.1 : 1 on white |
| `light.muted` | `#5F6368` | Secondary text | 5.9 : 1 on white |
| `light.border` | `#DADCE0` | Borders and dividers | — |
| `light.blue` | `#1A73E8` | Primary actions, links, selected states | 4.6 : 1 on white |
| `light.bluehover` | `#1765CC` | Primary button hover | — |
| `light.danger` | `#D93025` | Errors and destructive actions | — |

### Colours — inside the meeting (dark)

| Token | Hex | Used for | Contrast on `#202124` |
|---|---|---|---|
| `dark.bg` | `#202124` | The meeting background | — |
| `dark.surface` | `#3C4043` | Tiles, control buttons | — |
| `dark.raised` | `#292A2D` | Side panels | — |
| `dark.text` | `#E8EAED` | Primary text | 14.0 : 1 |
| `dark.muted` | `#9AA0A6` | Secondary text | 6.0 : 1 |
| `dark.accent` | `#8AB4F8` | Active controls, the speaking ring | 8.4 : 1 |
| `dark.danger` | `#EA4335` | Muted mic, camera off, the leave pill | 4.3 : 1 — **large text and icon buttons only**, never body copy |

All of these are the values the interface specification fixed. The contrast
ratios are recorded in `tailwind.config.js` itself, because this is an
accessibility project and the pairs actually used must clear WCAG AA (4.5 : 1
for body text, 3 : 1 for large text and UI components).

### Typography

| Item | Value |
|---|---|
| Font family | **Roboto**, then `ui-sans-serif, system-ui, -apple-system, Segoe UI, Helvetica Neue, Arial, sans-serif` |
| Weights loaded | 400, 500, 700 |
| Icons | **Material Symbols Outlined**, variable axes `opsz 20–48, wght 100–700, FILL 0–1, GRAD −50–200` |
| Caption text | `text-caption` 22 px / 30 px · `text-caption-lg` 28 px / 38 px · `text-caption-xl` 34 px / 46 px |
| Home heading | `text-display` 44 px / 52 px, weight 400 |

Both fonts come from Google Fonts. Roboto uses `display=swap`; the icon font
uses **`display=block`** deliberately — with `swap` the browser paints the
literal ligature names ("mic", "videocam") in a fallback font for a moment, so
the control bar visibly reads as words before turning into icons.

### Shape and layout

| Token | Value | Applied to |
|---|---|---|
| `rounded-card` | 8 px | Cards, inputs, menus |
| `rounded-tile` | 12 px | Video tiles, the camera preview |
| `rounded-dialog` | 8 px | Dialogs |
| Buttons | `rounded-full`, height 40 px (`.btn`), 44–48 px for round icon buttons | All buttons are pill-shaped |
| `h-topbar` | 64 px | The top bar |
| `h-controlbar` | 80 px | The meeting control bar |
| `h-captions` | 140 px | The caption area |
| `w-panel` | 360 px | Side panels |
| `max-w-caption` | 900 px | The caption column |
| `max-w-transcript` | 800 px | Transcript body |
| `max-w-authcard` | 400 px | Login and register card |

Shadows: `shadow-dialog`, `shadow-menu`, `shadow-tile` — all Material-style
two-layer shadows defined in the config.

### Responsive rule

Two-column pages collapse to one column **below 900 px**, expressed as
Tailwind's `lg:` breakpoint (1024 px) on Home and the Lobby and `sm:`/`md:`
elsewhere. In the meeting: below `sm` the control bar drops its left and right
zones and centres the controls; below `md` the side panels become overlays.

### Accessibility rules applied throughout

- A **visible focus ring** on everything, in two variants — `ring-light-blue`
  on white and `ring-dark-accent` on the dark surfaces — because one colour
  cannot work on both.
- Every icon button has **both** a tooltip and an `aria-label`.
- Every decorative icon is `aria-hidden`.
- The caption area is an `aria-live="polite"` region.
- `prefers-reduced-motion: reduce` collapses every animation and transition to
  0.01 ms.
- The meeting room sets `.on-dark` on its root so the dark focus-ring variant
  applies to everything inside it.

---

# 7. Backend API reference

## 7.1 Conventions

| Item | Value |
|---|---|
| Base URL (development) | `http://localhost:8000` |
| Interactive docs | `GET /docs` (Swagger UI), `GET /redoc`, `GET /openapi.json` |
| Authentication | `Authorization: Bearer <JWT>` on every endpoint marked **Yes** below |
| Content type | `application/json`, except `POST /api/auth/login` (form-encoded) and the two export endpoints |
| Error shape | FastAPI's `{"detail": "..."}` for `HTTPException`, or `{"detail": [{...}]}` for 422 validation errors |
| Timestamps | ISO 8601, naive (no timezone suffix), as MySQL `DATETIME` |

**Counts:** FastAPI registers **22 HTTP route entries**. Four are framework
built-ins (`/docs`, `/docs/oauth2-redirect`, `/openapi.json`, `/redoc`), leaving
**18 application endpoints**: 17 under `/api` plus `GET /health`. There are
**3 WebSocket endpoints**. All were enumerated by importing the app and reading
`app.routes` — see [Appendix A](#appendix-a-how-this-document-was-verified).

Every status code listed as "possible" is either produced by an explicit
`raise HTTPException` in the handler, or is FastAPI's automatic 422 for a body
that fails Pydantic validation, or 401 from the `get_current_user` dependency.

## 7.2 Authentication endpoints — `backend/app/api/auth.py`

### 7.2.1 `POST /api/auth/register`

| | |
|---|---|
| **Purpose** | Create an account and return a token, so registering logs you straight in |
| **Auth required** | No |
| **Handler** | `backend/app/api/auth.py::register` |
| **Request body** | `UserRegister` |
| **Response** | `201` → `Token` |
| **Status codes** | `201` created · `409` email already registered · `422` validation failed |

Request fields:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `name` | string | yes | 1–120 characters |
| `email` | string (email) | yes | must contain `@`; validated by `email-validator` |
| `password` | string | yes | **8–72 characters**. The 72 ceiling is bcrypt's — it truncates silently beyond it, so it is rejected up front instead |
| `role` | `"deaf"` \| `"hearing"` | no | default `"hearing"` |

**Example request**

```http
POST /api/auth/register
Content-Type: application/json

{
  "name": "Swarna Rathna A",
  "email": "swarna@example.com",
  "password": "strongpassword123",
  "role": "deaf"
}
```

**Example response** (`201`)

```json
{
  "access_token": "eyJhbGciOiJIUzI1Ni...<redacted>",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": 108,
    "name": "Swarna Rathna A",
    "email": "swarna@example.com",
    "role": "deaf",
    "created_at": "2026-10-05T03:07:54"
  }
}
```

### 7.2.2 `POST /api/auth/login`

| | |
|---|---|
| **Purpose** | OAuth2-style form login. Exists so Swagger UI's "Authorize" button works |
| **Auth required** | No |
| **Handler** | `backend/app/api/auth.py::login` |
| **Request body** | `application/x-www-form-urlencoded`: `username` (the email), `password` |
| **Response** | `200` → `Token` |
| **Status codes** | `200` · `401` incorrect credentials · `422` |

**Example request**

```http
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

username=deaf.demo@example.com&password=bridgetalk123
```

Response is identical in shape to `register`'s.

### 7.2.3 `POST /api/auth/login/json`

| | |
|---|---|
| **Purpose** | The login the frontend actually uses |
| **Auth required** | No |
| **Handler** | `backend/app/api/auth.py::login_json` |
| **Request body** | `UserLogin`: `email` (string, email), `password` (string) |
| **Response** | `200` → `Token` |
| **Status codes** | `200` · `401` · `422` |

**Example request**

```http
POST /api/auth/login/json
Content-Type: application/json

{"email": "deaf.demo@example.com", "password": "bridgetalk123"}
```

**Example response** (`200`, captured from the live server)

```json
{
  "access_token": "eyJhbGciOiJIUzI1Ni...<redacted>",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": 101,
    "name": "Demo Deaf User",
    "email": "deaf.demo@example.com",
    "role": "deaf",
    "created_at": "2026-08-15T23:29:10"
  }
}
```

**Example error** (`401`)

```json
{"detail": "Incorrect email or password"}
```

That wording is deliberate and identical for an unknown email and a wrong
password. Distinguishing them would let an attacker enumerate which email
addresses have accounts.

### 7.2.4 `GET /api/auth/me`

| | |
|---|---|
| **Purpose** | The current user's profile. Called on every page load to check the stored token is still valid |
| **Auth required** | **Yes** |
| **Handler** | `backend/app/api/auth.py::read_current_user` |
| **Request** | no body, no parameters |
| **Response** | `200` → `UserPublic` |
| **Status codes** | `200` · `401` missing, malformed, expired or forged token, or a token for a deleted user |

**Example response** (`200`, live)

```json
{
  "id": 101,
  "name": "Demo Deaf User",
  "email": "deaf.demo@example.com",
  "role": "deaf",
  "created_at": "2026-08-15T23:29:10"
}
```

Note `password_hash` is absent. `UserPublic` exists precisely so the hash
cannot leak: it is excluded by the schema, not by remembering to delete it.

## 7.3 Meeting endpoints — `backend/app/api/meetings.py`

### 7.3.1 `POST /api/meetings`

| | |
|---|---|
| **Purpose** | Create a meeting and generate its join code |
| **Auth required** | **Yes** — the caller becomes the host |
| **Handler** | `meetings.py::create_meeting`, using `::generate_meeting_code` |
| **Request body** | `MeetingCreate`: `title` (string, 1–200), `is_interview_mode` (boolean, default `false`) |
| **Response** | `201` → `MeetingPublic` |
| **Status codes** | `201` · `401` · `422` · `503` could not allocate a unique code after 10 attempts |

**Example request**

```http
POST /api/meetings
Authorization: Bearer <JWT>
Content-Type: application/json

{"title": "Documentation example meeting"}
```

**Example response** (`201`, live)

```json
{
  "id": 139,
  "code": "4T9-7M2",
  "title": "Documentation example meeting",
  "host": {
    "id": 101, "name": "Demo Deaf User", "email": "deaf.demo@example.com",
    "role": "deaf", "created_at": "2026-08-15T23:29:10"
  },
  "is_interview_mode": false,
  "interview_mode_started_at": null,
  "started_at": null,
  "ended_at": null,
  "created_at": "2026-10-05T03:07:54",
  "is_active": true
}
```

`started_at` is `null`: the clock starts when the **first participant joins**,
not at creation, so a meeting created on Monday for Friday does not report a
Monday start.

### 7.3.2 `GET /api/meetings/history`

| | |
|---|---|
| **Purpose** | Every meeting the caller hosted or attended, newest first, with participants and a caption count |
| **Auth required** | **Yes** |
| **Handler** | `meetings.py::meeting_history` |
| **Query parameters** | `q` — optional string, max 200 characters. Searches meeting **titles and saved caption text** |
| **Response** | `200` → `array[MeetingSummary]` |
| **Status codes** | `200` · `401` · `422` (`q` over 200 characters) |

Declared **before** `GET /{code}` on purpose: FastAPI matches routes in
declaration order, so `/{code}` would otherwise swallow `history` and look for a
meeting whose code is literally `"history"`.
`test_history_route_is_not_shadowed_by_the_code_route` guards this.

**Example request**

```http
GET /api/meetings/history?q=dataset
Authorization: Bearer <JWT>
```

**Example response** (`200`, live, truncated to one row)

```json
[
  {
    "id": 139,
    "code": "4T9-7M2",
    "title": "Documentation example meeting",
    "host": { "id": 101, "name": "Demo Deaf User", "email": "deaf.demo@example.com",
              "role": "deaf", "created_at": "2026-08-15T23:29:10" },
    "is_interview_mode": true,
    "interview_mode_started_at": "2026-10-05T03:08:11",
    "started_at": "2026-10-05T03:07:54",
    "ended_at": null,
    "created_at": "2026-10-05T03:07:54",
    "is_active": true,
    "participants": [
      { "id": 157,
        "user": { "id": 101, "name": "Demo Deaf User", "email": "deaf.demo@example.com",
                  "role": "deaf", "created_at": "2026-08-15T23:29:10" },
        "joined_at": "2026-10-05T03:07:54", "left_at": null }
    ],
    "caption_count": 1
  }
]
```

**Query cost.** Four SQL statements regardless of how many meetings: the
meetings; `selectinload` for participants; `selectinload` for their users; and
one grouped `COUNT` over `transcripts`. Caption text is matched with a
**subquery, not a JOIN** — a join returns one row per matching caption, so a
meeting containing the word five times would appear five times.
`test_history_search_returns_each_meeting_once` and
`test_history_does_not_issue_a_query_per_meeting` guard both decisions.

### 7.3.3 `GET /api/meetings/{code}`

| | |
|---|---|
| **Purpose** | One meeting with its attendance list |
| **Auth required** | **Yes** (any signed-in user — this is how joining by code works) |
| **Handler** | `meetings.py::get_meeting` |
| **Path parameter** | `code` — string, the meeting code |
| **Response** | `200` → `MeetingDetail` |
| **Status codes** | `200` · `401` · `404` no meeting with that code |

**Example error** (`404`, live)

```json
{"detail": "No meeting found with code 'ZZZ-ZZZ'"}
```

### 7.3.4 `POST /api/meetings/{code}/join`

| | |
|---|---|
| **Purpose** | Record attendance, start the meeting clock if first in, and tell the client whether it should create the WebRTC offer |
| **Auth required** | **Yes** |
| **Handler** | `meetings.py::join_meeting` |
| **Path parameter** | `code` — string |
| **Request body** | none |
| **Response** | `200` → `MeetingJoinResponse`: `meeting` (`MeetingDetail`), `is_first_participant` (boolean) |
| **Status codes** | `200` · `401` · `404` · `409` the meeting has ended |

**Example response** (`200`, live, abridged)

```json
{
  "meeting": {
    "id": 139, "code": "4T9-7M2", "title": "Documentation example meeting",
    "host": { "id": 101, "name": "Demo Deaf User", "...": "..." },
    "is_interview_mode": false, "interview_mode_started_at": null,
    "started_at": "2026-10-05T03:07:54", "ended_at": null,
    "created_at": "2026-10-05T03:07:54", "is_active": true,
    "participants": [
      { "id": 157, "user": { "id": 101, "name": "Demo Deaf User", "...": "..." },
        "joined_at": "2026-10-05T03:07:54", "left_at": null }
    ]
  },
  "is_first_participant": true
}
```

`meeting_participants` is a **log, not a set**: rejoining after a dropped
connection inserts a new row rather than updating the old one, so the attendance
history stays truthful about disconnections.

### 7.3.5 `POST /api/meetings/{code}/leave`

| | |
|---|---|
| **Purpose** | Stamp `left_at` on the caller's open attendance rows |
| **Auth required** | **Yes** |
| **Handler** | `meetings.py::leave_meeting` |
| **Response** | `200` → `MeetingDetail` |
| **Status codes** | `200` · `401` · `404` |

### 7.3.6 `POST /api/meetings/{code}/end`

| | |
|---|---|
| **Purpose** | End the meeting for everyone |
| **Auth required** | **Yes — host only** |
| **Handler** | `meetings.py::end_meeting` |
| **Response** | `200` → `MeetingDetail` with `ended_at` set and `is_active: false` |
| **Status codes** | `200` · `401` · `403` not the host · `404` |

Also stamps `left_at` on every participant whose row is still open.
`is_active` is **computed** from `ended_at is None` (a property on the `Meeting`
ORM model), so it cannot fall out of sync with a separate boolean column.

### 7.3.7 `PATCH /api/meetings/{code}/interview-mode`

| | |
|---|---|
| **Purpose** | Switch Interview Mode on or off during a meeting |
| **Auth required** | **Yes — host only** |
| **Handler** | `meetings.py::set_interview_mode` |
| **Request body** | `InterviewModeUpdate`: `enabled` (boolean, required) |
| **Response** | `200` → `MeetingDetail` |
| **Status codes** | `200` · `401` · `403` not the host · `404` · `422` |

**Example request**

```http
PATCH /api/meetings/4T9-7M2/interview-mode
Authorization: Bearer <JWT>
Content-Type: application/json

{"enabled": true}
```

**Example response** (`200`, live, abridged)

```json
{
  "id": 139, "code": "4T9-7M2",
  "is_interview_mode": true,
  "interview_mode_started_at": "2026-10-05T03:08:11",
  "...": "the rest of MeetingDetail"
}
```

Switching it on stamps `interview_mode_started_at`. That timestamp is load-bearing:
the rollup in `get_focus_events` ignores events from **before** it, so a tab
switch from earlier in the meeting — when it was perfectly allowed — is not
reported as a violation.

### 7.3.8 `POST /api/meetings/{code}/focus-events`

| | |
|---|---|
| **Purpose** | Record one focus change for the caller |
| **Auth required** | **Yes** (any participant — you log your own events) |
| **Handler** | `meetings.py::log_focus_event` |
| **Request body** | `FocusEventCreate`: `event_type` (`"blur"` \| `"hidden"` \| `"return"`, required), `duration_away_ms` (integer or null) |
| **Response** | `201` → `FocusEventPublic` |
| **Status codes** | `201` · `401` · `404` · `422` |

**Example request**

```http
POST /api/meetings/4T9-7M2/focus-events
Authorization: Bearer <JWT>
Content-Type: application/json

{"event_type": "return", "duration_away_ms": 4200}
```

**Example response** (`201`, live)

```json
{
  "id": 26,
  "meeting_id": 139,
  "user_id": 101,
  "user_name": "Demo Deaf User",
  "event_type": "return",
  "duration_away_ms": 4200,
  "created_at": "2026-10-05T03:08:11"
}
```

### 7.3.9 `GET /api/meetings/{code}/focus-events`

| | |
|---|---|
| **Purpose** | The host's attention log for a meeting, with a per-participant rollup |
| **Auth required** | **Yes — host only** |
| **Handler** | `meetings.py::get_focus_events` |
| **Response** | `200` → `FocusSummary` |
| **Status codes** | `200` · `401` · `403` not the host · `404` |

Host-only because this is a record *about* the participants; letting everyone
read everyone else's attention log would be surveillance of each other rather
than a tool for the person running the interview.

**Example response** (`200`, live)

```json
{
  "meeting_id": 139,
  "total_events": 2,
  "away_count": 1,
  "events": [
    { "id": 25, "meeting_id": 139, "user_id": 101, "user_name": "Demo Deaf User",
      "event_type": "blur", "duration_away_ms": null,
      "created_at": "2026-10-05T03:08:11" },
    { "id": 26, "meeting_id": 139, "user_id": 101, "user_name": "Demo Deaf User",
      "event_type": "return", "duration_away_ms": null,
      "created_at": "2026-10-05T03:08:11" }
  ],
  "by_participant": [
    { "user_id": 101, "user_name": "Demo Deaf User",
      "away_count": 1, "total_away_ms": 4200, "longest_away_ms": 4200 }
  ]
}
```

> **Defect visible in this very example.** Event `26` was stored with
> `duration_away_ms = 4200` — the database row confirms it, and
> `by_participant.total_away_ms` reports 4200 — yet the `events[]` entry says
> `null`. `get_focus_events` constructs `FocusEventPublic(...)` **without
> passing `duration_away_ms`**, so it falls back to its default of `None`. The
> host's "Interview mode log" on the transcript page therefore shows an em dash
> for every duration. Recorded as issue **K-3**.

`away_count` counts only `blur` and `hidden`; a `return` is the recovery, not
another offence.

## 7.4 Transcript endpoints — `backend/app/api/transcripts.py`

### 7.4.1 `POST /api/transcripts`

| | |
|---|---|
| **Purpose** | Append one line to a meeting transcript |
| **Auth required** | **Yes — must be host or a participant** |
| **Handler** | `transcripts.py::create_transcript` |
| **Request body** | `TranscriptCreate` |
| **Response** | `201` → `TranscriptPublic` |
| **Status codes** | `201` · `401` · `403` not a member · `404` no such meeting · `409` the meeting has ended · `422` |

Request fields:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `meeting_id` | integer | yes | — |
| `segment_id` | string or null | no | **accepted and then discarded — see the note below** |
| `source` | `"sign"` \| `"speech"` | yes | — |
| `content` | string | yes | 1–5000 characters; stored stripped |
| `confidence` | number or null | no | 0.0–1.0 |

**Example request**

```http
POST /api/transcripts
Authorization: Bearer <JWT>
Content-Type: application/json

{"meeting_id": 139, "segment_id": "doc-example-1",
 "source": "sign", "content": "good morning", "confidence": 0.91}
```

**Example response** (`201`, live — note what happened to `segment_id`)

```json
{
  "id": 51,
  "meeting_id": 139,
  "user_id": 101,
  "user_name": "Demo Deaf User",
  "segment_id": null,
  "source": "sign",
  "content": "good morning",
  "confidence": 0.91,
  "created_at": "2026-10-05T03:08:11"
}
```

> **Defect.** `segment_id` was sent as `"doc-example-1"` and came back `null`.
> `create_transcript` builds its `Transcript(...)` without the field, so the
> endpoint silently discards it. Because MySQL exempts `NULL` from `UNIQUE`,
> rows created this way are **not** protected by
> `UNIQUE (meeting_id, segment_id)` and can be duplicated without limit. The
> running application does not hit this path — captions are persisted over the
> WebSocket by `persist_final_caption`, which **does** set `segment_id` — and no
> frontend page calls this endpoint. Recorded as issue **K-2**.

The line is always attributed to the **authenticated caller**, never to a
`user_id` in the body. Trusting the body would let anyone put words in another
participant's mouth in the permanent record.

### 7.4.2 `GET /api/transcripts/{meeting_id}`

| | |
|---|---|
| **Purpose** | The full transcript for one meeting, in time order |
| **Auth required** | **Yes — must be host or a participant** |
| **Handler** | `transcripts.py::get_transcript` |
| **Path parameter** | `meeting_id` — integer (the numeric id, **not** the join code) |
| **Response** | `200` → `array[TranscriptPublic]` |
| **Status codes** | `200` · `401` · `403` not a member · `404` |

**Example response** (`200`, live)

```json
[
  {
    "id": 51, "meeting_id": 139, "user_id": 101,
    "user_name": "Demo Deaf User", "segment_id": null,
    "source": "sign", "content": "good morning",
    "confidence": 0.91, "created_at": "2026-10-05T03:08:11"
  }
]
```

`user_name` is joined in server-side so the client never has to resolve user ids
to names itself.

### 7.4.3 `GET /api/transcripts/{meeting_id}/export`

| | |
|---|---|
| **Purpose** | Download the transcript as a `.txt` file |
| **Auth required** | **Yes — must be host or a participant** |
| **Handler** | `transcripts.py::export_transcript` |
| **Response** | `200` → `text/plain`, with a `Content-Disposition` filename |
| **Status codes** | `200` · `401` · `403` · `404` |

**Example response body** (`200`, live)

```
BridgeTalk meeting transcript
============================================================
Meeting:  Documentation example meeting
Code:     4T9-7M2
Started:  2026-10-05T03:07:54
Ended:    still active
Lines:    1
============================================================

[03:08:11] SIGN  Demo Deaf User: good morning  (91%)
```

### 7.4.4 `GET /api/transcripts/{meeting_id}/export.pdf`

| | |
|---|---|
| **Purpose** | Download the transcript as a PDF |
| **Auth required** | **Yes — must be host or a participant** |
| **Handler** | `transcripts.py::export_transcript_pdf` |
| **Response** | `200` → `application/pdf` bytes, with a `Content-Disposition` filename |
| **Status codes** | `200` · `401` · `403` · `404` |

Built with reportlab. Both exports share one builder so the header block and
the line format cannot drift between the two formats.

**Why the frontend cannot use a plain link for either.** Both endpoints are
member-only and authenticated by a bearer token. A plain `<a href>` triggers a
browser *navigation*, and a navigation cannot set request headers — so the
server sees no token and answers 401. That was a real bug. `services/api.js`
instead does an authenticated `fetch`, turns the response into a `Blob`, clicks
a temporary anchor at an object URL, and then revokes it.

## 7.5 System endpoint — `backend/app/main.py`

### 7.5.1 `GET /health`

| | |
|---|---|
| **Purpose** | Liveness, database reachability, model status and socket occupancy in one request |
| **Auth required** | No |
| **Handler** | `main.py::health` |
| **Response** | `200` → object |
| **Status codes** | `200` always — database failure is reported as a **field**, not a 503, so a half-working system is still diagnosable from one request |

**Example response** (`200`, live, class name lists abridged)

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "connected",
  "database_error": null,
  "dialect": "mysql",
  "model":         { "mode": "static",  "loaded": true, "error": null, "classes": 28,
                     "class_names": ["A", "...", "space"], "normalization_version": 1,
                     "val_accuracy": 0.9404, "trained_at": "2026-08-22T05:41:27",
                     "source_dataset": "ASL Alphabet (grassknoted/asl-alphabet)",
                     "language": null, "signer_disjoint": null },
  "isl_model":     { "mode": "isl",     "loaded": true, "classes": 35, "val_accuracy": 0.9919, "...": "..." },
  "dynamic_model": { "mode": "dynamic", "loaded": true, "classes": 40, "val_accuracy": 0.8571,
                     "language": "ISL", "signer_disjoint": false, "...": "..." },
  "speech_to_text": { "whisper_loaded": true, "whisper_model": "base", "whisper_error": null },
  "websockets": {
    "inference": { "meetings": 0, "connections": 0 },
    "signaling": { "meetings": 0, "connections": 0 }
  }
}
```

Note `dynamic_model.classes` is **40**, not 41. The model has 41 outputs, but
`predictor.describe()` reports `user_facing_classes`, which excludes the
internal `__transition__` class — machinery, not vocabulary, and it must not
appear in a count shown to a user as "40 words".

## 7.6 WebSocket endpoints

All three authenticate by **JWT in the query string** (`?token=<JWT>`), not a
header, because the browser `WebSocket` constructor cannot set headers. All
three `accept()` the connection **first** and then close with code **1008**
(policy violation) on a bad token — rejecting before accepting surfaces in the
browser as an opaque 1006 with no reason attached.

| Endpoint | File | Purpose |
|---|---|---|
| `/ws/predict/{meeting_code}` | `backend/app/ws/inference.py` | Landmarks in, predictions out; also the caption channel for **both** directions |
| `/ws/signal/{meeting_code}` | `backend/app/ws/signaling.py` | Relays WebRTC setup messages verbatim |
| `/ws/transcribe/{meeting_code}` | `backend/app/ws/transcribe.py` | Audio in, Whisper text out |

### 7.6.1 `/ws/predict/{meeting_code}` — 11 message types

**Client → server (4)**

| Type | Payload fields | When sent | Handled by |
|---|---|---|---|
| `landmarks` | `mode` (`"static"`\|`"isl"`\|`"dynamic"`), `timestamp` (number), `hands` (array of `{handedness: "Left"\|"Right", landmarks: [[x,y,z] × 21]}`) | Every 100 ms while sign recognition is on | `_handle_static_frame` / `_handle_isl_frame` / `_handle_dynamic_frame` |
| `caption` | `segment_id` (string ≤ 64), `source` (`"sign"`\|`"speech"`), `text` (string), `is_final` (boolean), `confidence` (number or null) | When the client decides a caption segment has updated or closed | `validate_caption` → `build_caption_event` → broadcast → `persist_final_caption` |
| `clear` | none | User clears the sentence | Resets the active smoother and the sequence buffer |
| `backspace` | none | User deletes the last token | `smoother.backspace()` |
| `ping` | none | Keep-alive | Replies `pong` |

**Server → client (6)**

| Type | Payload fields | When sent | Scope |
|---|---|---|---|
| `connected` | `meeting_code`, `user{id,name}`, `model`, `isl_model`, `dynamic_model` (each a `describe()` object), `config{confidence_threshold, majority_window, majority_min, cooldown_ms}`, `dynamic_config{… plus filled, length, stride, min_detection_rate}` | Immediately after a successful connection | **Personal** |
| `prediction` | `mode`, `label`, `confidence`, `margin`, `stable`, `emitted`, `sentence`, `hand_detected`, `latency_ms`; plus `hands_seen` in ISL mode; plus `buffering`, `buffer_filled`, `buffer_length` in dynamic mode | Per classified frame | **Personal** — a per-frame prediction is not a caption |
| `caption` | `type`, `meeting_code`, `segment_id`, `speaker{id,name}`, `source`, `text`, `is_final`, `confidence`, `timestamp` (**server** time) | On every valid `caption` message received | **Broadcast to everyone, sender included** |
| `sentence` | `sentence` (string) | After `clear` or `backspace` | **Personal** |
| `pong` | none | After `ping` | **Personal** |
| `error` | `code`, `message` | On a bad message or a missing model | **Personal** |

Error codes emitted: `UNAUTHORIZED`, `MODEL_NOT_LOADED`, `INVALID_MESSAGE`.

The `caption` broadcast including the sender is the detail that makes both
screens agree. Previously the sender was excluded and rendered its own words
from local state, so the two participants' caption lists came from different
code paths and disagreed.

### 7.6.2 `/ws/signal/{meeting_code}` — 10 message types

**Client → server — the 6 relayed types** (the set `RELAYED_TYPES`)

| Type | Payload | When sent |
|---|---|---|
| `offer` | `payload` — an opaque SDP object | The initiating peer starts or renegotiates |
| `answer` | `payload` — an opaque SDP object | The receiving peer responds |
| `ice-candidate` | `payload` — an opaque ICE candidate | Throughout connection setup |
| `hangup` | `payload` (unused) | A peer leaves deliberately |
| `presentation-start` | `payload` — `{presenterId}` | Screen sharing starts |
| `presentation-stop` | `payload` | Screen sharing stops |
| `ping` | none | Keep-alive, replies `pong` |

Anything else is answered with an `error` carrying
`Cannot relay message type '<x>'`.

**Server → client (4 + the relays)**

| Type | Payload | When sent | Scope |
|---|---|---|---|
| `joined` | `self{id,name}`, `peers[{id,name}]`, `should_initiate` (boolean) | On connecting | **Personal** |
| `peer-joined` | `peer{id,name}` | Someone else connects | Broadcast, excluding them |
| `peer-left` | `peer{id,name}` | Someone disconnects | Broadcast |
| `no-peers` | `message` | A relay reached nobody | **Personal** |
| *(any relayed type)* | `type`, `from{id,name}`, `payload` | A peer sent it | Broadcast, excluding the sender |
| `pong` / `error` | — / `code`, `message` | — | **Personal** |

**The server never parses SDP or ICE.** It stamps who sent each message and
forwards the opaque `payload`. Not parsing them means a WebRTC specification
change needs no backend change at all.

`should_initiate` is `len(existing_peers) > 0`: **whoever arrives second starts
the call**, because they are the one who knows somebody is waiting. Exactly one
side offering is what avoids "glare".

### 7.6.3 `/ws/transcribe/{meeting_code}` — 5 message types

**Client → server (3)**

| Type | Format | Payload | When sent |
|---|---|---|---|
| *(audio)* | **binary frame** | Opus-in-WebM bytes from `MediaRecorder` | Every `timeslice` while recording |
| `config` | text JSON | `language` (string, e.g. `"en-IN"`) | On connecting, and on a language change |
| `flush` | text JSON | none | The user turned captions off mid-sentence — transcribe what is buffered rather than discarding their last words |

**Server → client (3)**

| Type | Payload | When sent |
|---|---|---|
| `ready` | `provider: "whisper"`, `model` (e.g. `"base"`), `sample_rate: 16000`, `provides_interim: false` | Immediately after a successful connection |
| `transcript` | `text`, `confidence` (or null), `is_final: true`, `audio_seconds`, `latency_ms` | When an utterance has been transcribed |
| `error` | `code`, `message` | On failure |

Error codes: `UNAUTHORIZED`, `MODEL_NOT_LOADED` (Whisper absent — the socket
then closes with 1008), `FFMPEG_MISSING` (also closes), `INVALID_MESSAGE`,
`TRANSCRIBE_FAILED`.

`is_final` is **always true**: Whisper has no interim concept, which is exactly
why `provides_interim: false` is advertised in `ready` — so the UI shows a
listening indicator rather than waiting for partial text that will never arrive.

---

# 8. External APIs, services and browser APIs

Everything here is code or infrastructure the project **calls but does not
own**. For each: what it is for, exactly what data goes to it, whether the
internet is needed, whether an account or key is needed, what it costs, and what
happens if it is unavailable.

## 8.1 Summary table

| Service / API | Category | Data sent to it | Internet needed | Account or key | Cost | If unavailable |
|---|---|---|---|---|---|---|
| **MediaPipe Tasks Vision** | Browser library (npm) | Nothing leaves the machine | **No** after setup | No | Free, Apache 2.0 | Hand tracking fails; the UI shows the landmarker error and sign captions stop |
| `hand_landmarker.task` | Model file | — (downloaded once at setup) | Only at setup | No | Free | `useHandLandmarker` errors with a message naming the missing file |
| MediaPipe WASM runtime | WebAssembly | — (copied from npm at setup) | No | No | Free | Same as above |
| **Web Speech API** | Browser API | **The user's microphone audio** → Google (in Chrome) | **Yes** | No | Free | `resolveAuto()` falls back to Whisper and says why |
| **Google STUN** | Network service | Our public IP and port | **Yes** | No | Free | The call connects only if both peers are on the same local network |
| **TURN** | Network service | Would relay all call media | n/a | Yes, if used | Paid bandwidth | **Not configured.** Calls fail on networks needing a relay |
| **Google Fonts** | CDN | Browser headers, including the referring page | First load only | No | Free | Text falls back to system sans-serif; **icons render blank** |
| **Hugging Face Hub** | Model host | Nothing (a download) | Only at first Whisper load | No | Free | Whisper does not load; `/health` reports `whisper_error` and the socket closes with `MODEL_NOT_LOADED` |
| **ffmpeg** | Local subprocess | Audio bytes, on stdin, locally | No | No | Free | `/ws/transcribe` closes with `FFMPEG_MISSING` |
| **Kaggle API** | Dataset host | Your Kaggle credentials | Only when downloading data | **Yes — your own token** | Free | Datasets cannot be downloaded; training cannot be rerun |
| Camera / microphone (`getUserMedia`) | Browser API | Nothing — a local device handle | No | No (user permission) | Free | Lobby shows per-error recovery steps and a Try again button |
| Screen capture (`getDisplayMedia`) | Browser API | Nothing — a local handle | No | No (user permission) | Free | Present does nothing; a cancelled picker shows no error |
| Fullscreen API | Browser API | Nothing | No | No | Free | Interview Mode reports `reducedEnforcement` |
| Keyboard Lock API | Browser API | Nothing | No | No | Free | Escape can exit fullscreen; reported as reduced enforcement |
| Clipboard API | Browser API | The joining link, to the OS clipboard | No | No | Free | Copy silently fails; the link is selectable text |
| Web Audio API | Browser API | Nothing | No | No | Free | The lobby level meter stays at zero |
| `MediaRecorder` | Browser API | Nothing (produces local Blobs) | No | No | Free | `WhisperProvider.isSupported()` returns false |
| WebRTC (`RTCPeerConnection`) | Browser API | Call media, peer-to-peer | **Yes** (across networks) | No | Free | No video or audio; captions still work |

## 8.2 MediaPipe — the hand tracker

**What it is.** Google's on-device vision library. `HandLandmarker` finds hands
in an image and returns **21 three-dimensional landmarks** per hand (wrist,
then four points per finger), as normalised coordinates in roughly `[0, 1]`.

**Where it runs.** In the browser, as WebAssembly, on the user's own machine.
This is the project's central technical decision.

**Where its files come from.**

| Asset | Served from | Size | Obtained by |
|---|---|---|---|
| `hand_landmarker.task` | **our own origin** — `frontend/public/models/` | 7,819,105 bytes | `scripts/setup.sh` downloads it once from `storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task` |
| `vision_wasm_internal.wasm` | our own origin | 9,502,124 bytes | copied from `node_modules/@mediapipe/tasks-vision/wasm` |
| `vision_wasm_nosimd_internal.wasm` | our own origin | 9,376,240 bytes | same |
| `vision_wasm_internal.js` / `_nosimd_internal.js` | our own origin | 203,819 / 203,672 bytes | same |

Serving them from our own origin rather than a CDN means **the application runs
fully offline after setup** — no request leaves the machine for hand tracking,
which would undermine the privacy claim if it did.

**Configuration** (`frontend/src/hooks/useHandLandmarker.js`):

| Option | Value | Why |
|---|---|---|
| `runningMode` | `'VIDEO'` | Tracks the hand across frames instead of re-detecting each one. Produces steadier landmarks, and jittery landmarks become jittery predictions |
| `delegate` | `'GPU'` | Several times faster and keeps the main thread free. MediaPipe falls back to CPU itself if WebGL is unavailable |
| `numHands` | 1 for ASL, 2 otherwise | ISL fingerspells with both hands; tracking one would leave half of every feature vector zero |
| `minHandDetectionConfidence` | 0.5 | MediaPipe default |
| `minHandPresenceConfidence` | 0.5 | MediaPipe default |
| `minTrackingConfidence` | 0.5 | MediaPipe default |

**Data sent to Google: none at runtime.** The only Google request is the
one-time model download during setup.

**Licence.** Apache 2.0.

## 8.3 Web Speech API — speech engine 1

**What it is.** A browser API (`SpeechRecognition`, in Chrome
`webkitSpeechRecognition`) that turns microphone audio into text.

**What data is sent, and where it goes.** **In Chrome, the microphone audio is
sent to Google's servers for recognition.** This is Chrome's implementation, not
something the project chose, and it cannot be disabled while using this engine.

This sits in direct tension with the project's central privacy claim. The
project's response is to **state it in the interface rather than bury it**:
`frontend/src/services/stt/index.js` labels this engine *"Fast, word-by-word.
Chrome/Edge only. **Audio is sent to Google.**"* and offers Whisper as the
alternative that keeps audio on the project's own backend.

| Property | Value |
|---|---|
| Browser support | Chromium only in practice. Firefox has none; Safari's is partial and unreliable |
| Internet required | **Yes** |
| Account or key | No |
| Cost | Free, with undocumented rate limits |
| Settings used | `continuous = true`, `interimResults = true`, `lang` from preferences (default `en-IN`) |
| If unavailable | `resolveAuto()` detects it and falls back to Whisper, reporting the reason to the UI |

`continuous = true` keeps it running across sentences; `interimResults = true`
is what produces word-by-word text. The API terminates sessions on its own, so
`onend` fires routinely and `WebSpeechProvider` restarts it whenever the
microphone is still unmuted — bounded at `MAX_RESTARTS = 40` with backoff from
300 ms to 5000 ms, and the budget is refunded after a `HEALTHY_RUN_MS = 15000`
run so a long meeting cannot exhaust it.

Errors surfaced rather than swallowed: `not-allowed`, `network`,
`audio-capture`, `no-speech`.

## 8.4 Google STUN servers

**What STUN is.** Session Traversal Utilities for NAT. Most computers sit behind
a router doing Network Address Translation, so a browser does not know what its
own public address looks like from the outside. A STUN server answers exactly
that one question: "what address did this request appear to come from?"

| Property | Value |
|---|---|
| Servers used | `stun:stun.l.google.com:19302`, `stun:stun1.l.google.com:19302` |
| Configured in | `.env` → `VITE_STUN_URLS`, read by `frontend/src/hooks/useWebRTC.js` |
| Data sent | Our public IP address and port, by nature of making the request |
| Internet required | **Yes** |
| Account or key | No |
| Cost | Free |
| If unavailable | Only host candidates are gathered. The call connects if both peers are on the same local network, and fails otherwise |

Two servers are listed because any one of them may be unreachable.

## 8.5 TURN — configured but not provided

**What TURN is.** Traversal Using Relays around NAT. When two peers genuinely
cannot reach each other directly — symmetric NAT, which is common on corporate
and mobile networks — the only way through is to **relay all the media through a
third server**. That is TURN.

| Property | Value |
|---|---|
| Status | **Not configured.** `VITE_TURN_URLS`, `VITE_TURN_USERNAME`, `VITE_TURN_CREDENTIAL` are all empty in `.env.example` |
| Code support | Complete. `useWebRTC.js` adds a TURN entry to `iceServers` when the variables are set |
| Cost if added | Real money — a TURN server pays for **all** relayed call bandwidth |
| What this means today | **Calls fail to connect on any network that requires a relay.** Two laptops on one Wi-Fi network work; a laptop on mobile data talking to one behind a corporate firewall may not |

Deploying behind TURN is a `.env` change and no code change. This is the single
largest gap between the project as it stands and something deployable — see
[Section 19](#19-known-issues-limitations-and-future-work).

## 8.6 Google Fonts

| Property | Value |
|---|---|
| What it serves | **Roboto** (weights 400, 500, 700) and **Material Symbols Outlined** |
| Loaded from | `frontend/index.html`, with `preconnect` to `fonts.googleapis.com` and `fonts.gstatic.com` |
| Data sent | Standard HTTP headers, including the referring page, as with any CDN request |
| Internet required | On first load only; afterwards the browser cache serves it |
| Account or key | No |
| Cost | Free |

**If unavailable:** Roboto falls back to the system sans-serif stack, which is
cosmetic. The **icons do not**: Material Symbols is a ligature font, and with
`display=block` the glyphs render as **blank space** until it loads. Every icon
button still carries its tooltip and `aria-label`, so the interface remains
operable and accessible, but it looks broken. This is a real deployment risk for
a review on poor Wi-Fi with a cold cache, recorded as issue **K-9**.

`display=block` is nonetheless the right choice: with `display=swap` the browser
paints the literal ligature names and the control bar visibly reads "mic
videocam closed_caption" before turning into icons.

## 8.7 Hugging Face Hub

| Property | Value |
|---|---|
| What it serves | The `Systran/faster-whisper-base` model weights |
| Downloaded to | `ml/models/whisper/` (gitignored), set by `WHISPER_CACHE_DIR` |
| When | Once, on the first backend start that loads Whisper |
| Data sent | Nothing — it is a download |
| Internet required | At first load only |
| Account or key | No |
| Cost | Free |
| If unavailable | Whisper does not load. This is **not fatal**: `/health` reports `whisper_error`, and `/ws/transcribe` closes with `MODEL_NOT_LOADED`. Web Speech is unaffected |

`HF_HUB_DISABLE_XET=1` is required. Without it, the Xet storage backend stalls
the download at 0 bytes with no error — this was diagnosed and is documented in
`backend/requirements.txt`.

The cache is kept **inside the repository** rather than in `~/.cache` so the
download is visible, obviously disposable, and cannot silently happen twice.

## 8.8 ffmpeg

| Property | Value |
|---|---|
| What it does | Decodes browser audio (WebM/Opus, MP4/AAC, Ogg) to 16 kHz mono float32 PCM for Whisper |
| How it is called | A **subprocess**, via `shutil.which("ffmpeg")` and a pipe — not a Python library |
| Version on this machine | **9.0.1** (measured now with `ffmpeg -version`) |
| Pinned | **No.** Whatever is on `PATH` |
| Internet required | No |
| Account or key | No |
| Cost | Free |
| If unavailable | `/ws/transcribe` sends `{"code": "FFMPEG_MISSING"}` and closes with 1008. Whisper is unavailable; Web Speech is unaffected |

A subprocess rather than a library because ffmpeg handles every container and
codec any browser produces, which otherwise means pulling in a stack of Python
decoders that each cover one format.

## 8.9 Kaggle API

| Property | Value |
|---|---|
| What it does | Downloads the training datasets |
| Used by | `ml/scripts/download_datasets.py` |
| Account or key | **Yes — the user's own Kaggle API token**, plus accepting each dataset's terms |
| Data sent | Your Kaggle credentials |
| Internet required | Only when downloading |
| Cost | Free |
| If unavailable | Datasets cannot be downloaded. The **trained models are committed**, so the application still runs; only retraining is blocked |

## 8.10 Browser APIs used directly

| API | Used in | What for | Fallback |
|---|---|---|---|
| `navigator.mediaDevices.getUserMedia` | `Lobby.jsx`, `MeetingRoom.jsx` | Camera and microphone | Per-error recovery steps: denied, in-use-elsewhere and not-found need different fixes, so `describeMediaError` gives different instructions |
| `navigator.mediaDevices.enumerateDevices` | `useMediaDevices.js` | List cameras, microphones, speakers | Labels are empty until permission is granted once — a deliberate anti-fingerprinting measure, which is why the lobby requests a stream **before** enumerating |
| `navigator.mediaDevices.getDisplayMedia` | `useScreenShare.js` | Screen sharing | A cancelled picker throws `NotAllowedError` and is treated as a **cancel, not an error** |
| `RTCPeerConnection` | `useWebRTC.js` | The peer-to-peer call | No video or audio; captions still work |
| `MediaRecorder` | `WhisperProvider.js` | Record Opus for Whisper | `isSupported()` returns false; `resolveAuto` picks Web Speech |
| `SpeechRecognition` / `webkitSpeechRecognition` | `WebSpeechProvider.js` | Speech engine 1 | Falls back to Whisper |
| `AudioContext` + `AnalyserNode` | `useMicLevel.js` | The lobby level meter | Wrapped in try/catch; the meter stays at zero and the lobby still works |
| `requestFullscreen` / `exitFullscreen` | `useInterviewMode.js`, `MeetingRoom.jsx` | Interview Mode enforcement and the Full screen menu item | `capabilities.fullscreen` is false; `reducedEnforcement` is reported to the host |
| `navigator.keyboard.lock` | `useInterviewMode.js` | Capture Escape so it cannot silently exit fullscreen | **Chromium only.** `capabilities.keyboardLock` is false elsewhere |
| `document.visibilityState` + `visibilitychange` | `useInterviewMode.js` | Detect tab switching | — |
| `window.blur` / `focus` | `useInterviewMode.js` | Detect switching to another application | — |
| `navigator.clipboard.writeText` | `DetailsPanel.jsx`, `Home.jsx` | Copy the joining link | Unavailable over plain HTTP from a non-localhost origin. Fails silently; the link is selectable text |
| `localStorage` / `sessionStorage` | `api.js`, `devicePreferences.js`, `useMeetingPreferences.js` | Token, device choices, preferences | Every access is wrapped in try/catch — these throw in a private window with site data blocked |
| `HTMLMediaElement.setSinkId` | `Lobby.jsx` | Route preview audio to the chosen speaker | **Chromium only.** The speaker dropdown is **hidden** where no output devices are exposed, rather than shown doing nothing |
| `requestAnimationFrame` | `useMicLevel.js`, `MeetingRoom.jsx`, `SignDetection.jsx` | The detection loop and the level meter | Paused by the browser in a background tab, which is desirable |
| Canvas 2D (`getContext('2d')`) | `HandOverlayCanvas.jsx` | Draw the hand skeleton | **Guarded for null.** It returns null when the GPU context is lost, and the throw would otherwise escalate to the error boundary and take down the whole meeting |

## 8.11 What leaves the machine, in one place

Because this is the project's central claim, here it is stated exactly.

| Direction | What leaves the browser | Where it goes |
|---|---|---|
| **Sign → text** | **Only landmark coordinates.** 21 × 3 floats per hand, ~500 bytes per frame at 10 Hz | Our own backend, over `/ws/predict` |
| **Sign → text** | **No video, ever.** No code path sends a frame; the socket accepts only a `landmarks` message | — |
| **Speech → text, Web Speech** | **The microphone audio** | **Google's servers** |
| **Speech → text, Whisper** | The microphone audio, as Opus | Our own backend, over `/ws/transcribe` |
| **The call itself** | Camera video and microphone audio | **Directly to the other browser**, peer-to-peer. Never through our server |
| **Call setup** | SDP and ICE candidates, which contain IP addresses | Our own backend, relayed verbatim |
| **Captions and transcript** | Recognised text only | Our own backend and MySQL |
| **Fonts** | HTTP headers | Google Fonts CDN, first load only |

The honest summary: **the sign-language direction genuinely keeps video on the
device. The speech direction does not keep audio on the device unless Whisper is
selected.** The interface says so.

---

# 9. Database

## 9.1 Engine and connection

| Item | Value |
|---|---|
| Engine | **MySQL 9.7.1** — measured now with `SELECT VERSION()` on the live server |
| Storage engine | InnoDB, on every table |
| Character set | `utf8mb4`, collation `utf8mb4_0900_ai_ci` |
| Database name | `bridgetalk` |
| Driver | **PyMySQL 1.1.1** (pure Python — no C compiler needed at install) |
| ORM | **SQLAlchemy 2.0.36** |
| Connection string | `DATABASE_URL` in `.env`, read **only** by `backend/app/config.py` |
| Engine created in | `backend/app/database.py` |
| Session factory | `SessionLocal`, in `backend/app/database.py` |
| Tables | **5** |
| Columns | **34** |

`utf8mb4` is the real Unicode character set in MySQL. The older `utf8` alias
stores at most 3 bytes per character and cannot hold emoji or many non-Latin
scripts — a genuine problem for a multilingual accessibility tool.

**SQLite fallback.** Setting `DATABASE_URL=sqlite:///./bridgetalk.db` is a
documented one-line change with no other code change;
`config.py::is_sqlite` adjusts the engine arguments. The backend test suite uses
in-memory SQLite, so no MySQL is needed to run the tests.

**Startup behaviour** (`backend/app/main.py::lifespan`): the backend executes
`SELECT 1` before serving anything and **refuses to start** if it fails, with a
message naming `DATABASE_URL` and the SQLite fallback. Without that check the
server starts happily and every request dies with a stack trace — much harder to
debug ten minutes before a review.

## 9.2 ER diagram

```mermaid
erDiagram
    users ||--o{ meetings : "hosts (host_id)"
    users ||--o{ meeting_participants : "attends (user_id)"
    users ||--o{ transcripts : "speaks or signs (user_id)"
    users ||--o{ focus_events : "generates (user_id)"
    meetings ||--o{ meeting_participants : "has attendance log (meeting_id)"
    meetings ||--o{ transcripts : "accumulates captions (meeting_id)"
    meetings ||--o{ focus_events : "records focus changes (meeting_id)"

    users {
        INT id PK "AUTO_INCREMENT"
        VARCHAR_120 name "NOT NULL"
        VARCHAR_255 email UK "NOT NULL, UNIQUE"
        VARCHAR_255 password_hash "NOT NULL, bcrypt"
        ENUM role "deaf|hearing, default hearing"
        DATETIME created_at "NOT NULL, default CURRENT_TIMESTAMP"
    }

    meetings {
        INT id PK "AUTO_INCREMENT"
        VARCHAR_16 code UK "NOT NULL, UNIQUE"
        VARCHAR_200 title "NOT NULL"
        INT host_id FK "NOT NULL, to users.id"
        TINYINT is_interview_mode "NOT NULL, default 0"
        DATETIME interview_mode_started_at "NULL"
        DATETIME started_at "NULL until first join"
        DATETIME ended_at "NULL while live"
        DATETIME created_at "NOT NULL, default CURRENT_TIMESTAMP"
    }

    meeting_participants {
        INT id PK "AUTO_INCREMENT"
        INT meeting_id FK "NOT NULL, to meetings.id"
        INT user_id FK "NOT NULL, to users.id"
        DATETIME joined_at "NOT NULL, default CURRENT_TIMESTAMP"
        DATETIME left_at "NULL while present"
    }

    transcripts {
        INT id PK "AUTO_INCREMENT"
        INT meeting_id FK "NOT NULL, to meetings.id"
        INT user_id FK "NOT NULL, to users.id"
        VARCHAR_64 segment_id "NULL, UNIQUE with meeting_id"
        ENUM source "sign|speech, NOT NULL"
        TEXT content "NOT NULL"
        FLOAT confidence "NULL"
        DATETIME created_at "NOT NULL, default CURRENT_TIMESTAMP"
    }

    focus_events {
        INT id PK "AUTO_INCREMENT"
        INT meeting_id FK "NOT NULL, to meetings.id"
        INT user_id FK "NOT NULL, to users.id"
        ENUM event_type "blur|hidden|return, NOT NULL"
        INT duration_away_ms "NULL, set on return rows only"
        DATETIME created_at "NOT NULL, default CURRENT_TIMESTAMP"
    }
```

Every relationship is one-to-many from `users` or `meetings`. There are no
many-to-many join tables: `meeting_participants` looks like one but is
deliberately an **attendance log**, not a set — see below.

## 9.3 Table: `users`

**Purpose.** One row per account. Holds credentials and the role that decides
which side of the interface is pre-configured.

| Column | Type | Nullable | Default | Key / index | What it stores |
|---|---|---|---|---|---|
| `id` | `int` | NO | — | **PRIMARY KEY**, `AUTO_INCREMENT` | Surrogate key, referenced by all four other tables |
| `name` | `varchar(120)` | NO | — | — | Display name, shown beside every caption and avatar |
| `email` | `varchar(255)` | NO | — | **UNIQUE** `uq_users_email` | Login identifier. The UNIQUE constraint is the real guarantee two accounts cannot share an email — an application check alone loses a race between two simultaneous registrations |
| `password_hash` | `varchar(255)` | NO | — | — | A **bcrypt hash**, never a password. 60 characters today; sized at 255 for a future switch to argon2 without a migration |
| `role` | `enum('deaf','hearing')` | NO | `'hearing'` | — | Which side of the UI is pre-configured. **A UI hint, not a permission boundary** — both roles may use both translation directions |
| `created_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | — | Registration time |

**Foreign keys out:** none. **Referenced by:** `meetings.host_id`,
`meeting_participants.user_id`, `transcripts.user_id`, `focus_events.user_id` —
all `ON DELETE CASCADE`, so deleting a user removes everything they hosted,
attended, said and generated, rather than leaving rows pointing at an id that no
longer exists.

**Reads:** login, `GET /api/auth/me`, every authenticated request (via
`get_current_user`), every caption (for the speaker's name), the lobby, every
avatar.
**Writes:** `POST /api/auth/register` only. Nothing in the application updates
or deletes a user.

**Example row** (made-up data)

| id | name | email | password_hash | role | created_at |
|---|---|---|---|---|---|
| 42 | Swarna Rathna A | swarna@example.com | `$2b$12$K3f…` (60 chars, truncated here) | `deaf` | 2026-10-05 09:14:22 |

## 9.4 Table: `meetings`

**Purpose.** One row per meeting. Holds the join code, who hosts it, the
Interview Mode state, and the three timestamps that define its lifecycle.

| Column | Type | Nullable | Default | Key / index | What it stores |
|---|---|---|---|---|---|
| `id` | `int` | NO | — | **PRIMARY KEY**, `AUTO_INCREMENT` | Surrogate key. Used by `transcripts`, `focus_events` and the transcript endpoints |
| `code` | `varchar(16)` | NO | — | **UNIQUE** `uq_meetings_code` | The human-typable join code, e.g. `K7Q-2M4`. Every join looks a meeting up by this, never by id |
| `title` | `varchar(200)` | NO | — | — | What the meeting is called. Defaults to `"BridgeTalk meeting"` when created from Home |
| `host_id` | `int` | NO | — | **FK** → `users.id`, index `ix_meetings_host` | Who created it. Only this user may end the meeting, toggle Interview Mode, or read the focus log |
| `is_interview_mode` | `tinyint(1)` | NO | `0` | — | Whether Interview Mode is on. Stored on the **meeting record** rather than in browser state, so reloading the page is not a way out |
| `interview_mode_started_at` | `datetime` | YES | `NULL` | — | When the mode was switched on, or NULL if off. **Load-bearing:** the rollup in `get_focus_events` ignores events before this, so a tab switch from when it was allowed is not reported as a violation |
| `started_at` | `datetime` | YES | `NULL` | — | Set when the **first participant joins**, not at creation — so a meeting created on Monday for Friday does not report a Monday start |
| `ended_at` | `datetime` | YES | `NULL` | — | NULL while the meeting is live. This single column is the source of truth for `is_active`, which is a **computed property** on the ORM model (`ended_at is None`) rather than a stored boolean that could drift |
| `created_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | — | When the meeting was created |

**Foreign keys out:** `host_id` → `users.id`, **ON DELETE CASCADE**.
**Referenced by:** `meeting_participants.meeting_id`, `transcripts.meeting_id`,
`focus_events.meeting_id` — all **ON DELETE CASCADE**, so deleting a meeting
removes its attendance log, its transcript and its focus events.

**Reads:** Home (recent meetings), History, the lobby, the meeting room, the
transcript page, every caption persistence (to resolve code → id), every
`/ws/predict` and `/ws/signal` connection.
**Writes:** `POST /api/meetings` (insert), `POST .../join` (sets `started_at` if
first), `POST .../end` (sets `ended_at`), `PATCH .../interview-mode` (sets
`is_interview_mode` and `interview_mode_started_at`).

**Example row**

| id | code | title | host_id | is_interview_mode | interview_mode_started_at | started_at | ended_at | created_at |
|---|---|---|---|---|---|---|---|---|
| 139 | `K7Q-2M4` | Project review with guide | 42 | 1 | 2026-10-05 09:20:11 | 2026-10-05 09:18:03 | 2026-10-05 09:52:40 | 2026-10-05 09:17:55 |

## 9.5 Table: `meeting_participants`

**Purpose.** An **attendance log**, not a set of current members. Rejoining
after a dropped connection inserts a **new row** rather than updating the old
one, so the history stays truthful about disconnections.

| Column | Type | Nullable | Default | Key / index | What it stores |
|---|---|---|---|---|---|
| `id` | `int` | NO | — | **PRIMARY KEY**, `AUTO_INCREMENT` | Surrogate key |
| `meeting_id` | `int` | NO | — | **FK** → `meetings.id`, index `ix_participants_meeting`, composite `ix_participant_meeting_user` | Which meeting |
| `user_id` | `int` | NO | — | **FK** → `users.id`, index `ix_participants_user`, composite `ix_participant_meeting_user` | Which person |
| `joined_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | — | When they arrived |
| `left_at` | `datetime` | YES | `NULL` | — | When they left. NULL means still present — or that the tab was closed without a clean leave |

The composite index `ix_participant_meeting_user (meeting_id, user_id)` exists
because "is this user currently in this meeting?" filters on both columns at
once, and is the membership check behind every transcript read.

**Foreign keys out:** both **ON DELETE CASCADE**. **Referenced by:** nothing.

**Reads:** the membership check in `_load_meeting_for_member` (every transcript
read and export), history (participant avatars), the lobby ("who is already in
this call"), the transcript page header.
**Writes:** `POST .../join` (insert), `POST .../leave` (sets `left_at`),
`POST .../end` (sets `left_at` on every open row).

**Known consequence.** Because a join always inserts, a participant who
reconnects several times appears several times. The live database currently has a
meeting with **17** participant rows for two people — see issue **K-8**.

**Example row**

| id | meeting_id | user_id | joined_at | left_at |
|---|---|---|---|---|
| 157 | 139 | 42 | 2026-10-05 09:18:03 | 2026-10-05 09:52:40 |

## 9.6 Table: `transcripts`

**Purpose.** One row per **utterance segment** — the saved record of everything
signed or spoken. This is the table that makes the transcript, the search and
the downloads possible.

| Column | Type | Nullable | Default | Key / index | What it stores |
|---|---|---|---|---|---|
| `id` | `int` | NO | — | **PRIMARY KEY**, `AUTO_INCREMENT` | Surrogate key |
| `meeting_id` | `int` | NO | — | **FK** → `meetings.id`; index `ix_transcripts_meeting`; composite `ix_transcript_meeting_created`; **UNIQUE** with `segment_id` | Which meeting |
| `user_id` | `int` | NO | — | **FK** → `users.id`, index `ix_transcripts_user` | Who said or signed it. Always the **authenticated** caller, never a value from the request body |
| `segment_id` | `varchar(64)` | YES | `NULL` | **UNIQUE** `uq_transcript_segment (meeting_id, segment_id)` | The producing client's id for one utterance, stable across every interim and the final. **This column is what stopped the transcript storing "a", "a b", "a b c"** |
| `source` | `enum('sign','speech')` | NO | — | — | Which translation direction produced it. Keeping them distinguishable is what lets the panel label entries and what allows sign accuracy to be reported separately from speech accuracy |
| `content` | `text` | NO | — | — | The text of **this segment only** — never the accumulated history. Stored stripped; 1–5000 characters enforced by Pydantic |
| `confidence` | `float` | YES | `NULL` | — | The model's softmax probability for sign rows. **NULL for speech** — the Web Speech API reports a confidence, but it is not comparable to a softmax probability, so averaging the two would produce a meaningless number |
| `created_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | — | **Server** time, set explicitly by the persistence path. Two clients with skewed clocks would otherwise produce a transcript that does not sort into the order the conversation happened in |

**The UNIQUE index is the idempotency guarantee.** It is `UNIQUE`, not an
ordinary index, so a client retry or a reconnect replaying its tail **collides**
rather than inserting a second copy. `persist_final_caption` catches the
resulting `IntegrityError`, rolls back, and returns `False`.

MySQL exempts `NULL` from `UNIQUE`, which is deliberate here: rows predating the
column (and rows created through `POST /api/transcripts`, which discards the
field — issue **K-2**) do not conflict with each other.

`ix_transcript_meeting_created (meeting_id, created_at)` exists because every
read is "meeting X's lines in time order".

**Foreign keys out:** both **ON DELETE CASCADE**. **Referenced by:** nothing.

**Reads:** the transcript page, the live transcript panel, both export
endpoints, and the grouped `COUNT` plus the search subquery in
`GET /api/meetings/history`.
**Writes:** `persist_final_caption` from `/ws/predict` (the path the application
actually uses), and `POST /api/transcripts` (which no page calls).

**Example rows**

| id | meeting_id | user_id | segment_id | source | content | confidence | created_at |
|---|---|---|---|---|---|---|---|
| 318 | 139 | 42 | `sign-m1k2j3-a8f2c1d9` | `sign` | good morning | 0.91 | 2026-10-05 09:19:02 |
| 319 | 139 | 43 | `speech-m1k2k0-77be31aa` | `speech` | good morning, shall we start? | NULL | 2026-10-05 09:19:08 |

## 9.7 Table: `focus_events`

**Purpose.** The Interview Mode log. One row per focus change, so a host can see
when a participant left the meeting tab and for how long.

| Column | Type | Nullable | Default | Key / index | What it stores |
|---|---|---|---|---|---|
| `id` | `int` | NO | — | **PRIMARY KEY**, `AUTO_INCREMENT` | Surrogate key |
| `meeting_id` | `int` | NO | — | **FK** → `meetings.id`, index `ix_focus_meeting`, composite `ix_focus_meeting_user` | Which meeting |
| `user_id` | `int` | NO | — | **FK** → `users.id`, index `ix_focus_user`, composite `ix_focus_meeting_user` | Which participant |
| `event_type` | `enum('blur','hidden','return')` | NO | — | — | `blur` = the window lost focus (another application); `hidden` = the tab was switched away; `return` = they came back. **These three are genuinely everything the browser will tell us** |
| `duration_away_ms` | `int` | YES | `NULL` | — | How long they were away. Set on **`return` rows only**, because that is the first moment the duration is known. A 300 ms notification steal and a two-minute absence must be distinguishable, or the host's log is not worth reading |
| `created_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | — | When the event happened |

The composite index `ix_focus_meeting_user` exists because the host's view counts
events per participant.

**Foreign keys out:** both **ON DELETE CASCADE**. **Referenced by:** nothing.

**Reads:** `GET /api/meetings/{code}/focus-events` — the host's live panel
(polled every 5 s) and the host-only "Interview mode log" on the transcript page.
**Writes:** `POST /api/meetings/{code}/focus-events`, called by
`useInterviewMode` on every detected focus change.

**Example rows**

| id | meeting_id | user_id | event_type | duration_away_ms | created_at |
|---|---|---|---|---|---|
| 25 | 139 | 43 | `hidden` | NULL | 2026-10-05 09:31:14 |
| 26 | 139 | 43 | `return` | 4200 | 2026-10-05 09:31:18 |

## 9.8 Live schema versus the repository

**Method.** `SHOW TABLES` and `SHOW FULL COLUMNS` were read from the live MySQL
server and compared programmatically with the `CREATE TABLE` statements parsed
out of `database/schema.sql`.

**Result:**

```
LIVE:        5 tables, 34 columns
schema.sql:  5 tables, 34 columns
DIFFERENCES: NONE — column sets match exactly
```

Per table, both sources agree on: `users` 6, `meetings` 9,
`meeting_participants` 5, `transcripts` 8, `focus_events` 6.

Types, nullability, defaults, keys, foreign keys and `ON DELETE CASCADE` were
compared by reading the live `SHOW CREATE TABLE` output against `schema.sql` and
also match. The only differences are ones MySQL adds itself and which
`schema.sql` does not spell out:

| Difference | Live | `schema.sql` | Significance |
|---|---|---|---|
| Collation | `utf8mb4_0900_ai_ci` on every table | Declares `DEFAULT CHARSET=utf8mb4` and sets the collation on the **database**, not per table | None — the table inherits it |
| `AUTO_INCREMENT` counters | `users`=107, `meetings`=139, `meeting_participants`=157, `transcripts`=51, `focus_events`=25 | Not present | None — runtime state, not schema |
| `BOOLEAN` | Stored as `tinyint(1)` | Written as `BOOLEAN` | None — MySQL's `BOOLEAN` *is* `tinyint(1)` |

**The two migration files are already applied.** `001_interview_mode_enforcement.sql`
adds `meetings.interview_mode_started_at`, `focus_events.duration_away_ms` and the
`'return'` enum value; `002_caption_segments.sql` adds `transcripts.segment_id`
and its UNIQUE index. All of these are present live **and** in `schema.sql`, so
`schema.sql` is the full current schema and a fresh install needs no migrations.

There is also an automated guard: `backend/tests/test_schema_parity.py` (4 tests)
fails if `schema.sql` and the SQLAlchemy ORM models describe different tables,
columns or enum values.

## 9.9 Which features read and write each table

| Table | Written by | Read by |
|---|---|---|
| `users` | Registration | Login, `/api/auth/me`, every authenticated request, every caption's speaker name, avatars, the lobby, the People panel |
| `meetings` | Create, join (`started_at`), end (`ended_at`), interview-mode toggle | Home, History, lobby, meeting room, transcript page, meeting-ended page, caption persistence, both WebSocket authentications |
| `meeting_participants` | Join, leave, end | Transcript access control, History avatars, lobby "who is here", transcript page header |
| `transcripts` | `persist_final_caption` (WebSocket); `POST /api/transcripts` (unused by the UI) | Transcript page, live transcript panel, TXT export, PDF export, history caption count, history search |
| `focus_events` | `POST .../focus-events` from `useInterviewMode` | Host's live violation panel, host-only interview log on the transcript page |

---

# 10. Machine learning: datasets and models

## 10.1 The approach, in plain language

A neural network could be trained on **pictures** of hands. This project does
not do that. Instead:

1. **MediaPipe** turns each picture (or video frame) into **21 points per hand** —
   the wrist, plus four points along each finger — each with an `x`, `y` and `z`
   coordinate.
2. Those numbers are **normalised**: the wrist is moved to the origin, and
   everything is scaled so the furthest landmark sits at a distance of exactly 1.
3. A small neural network learns to map that short list of numbers to a letter
   or a word.

**Why not learn from pixels directly?** Three reasons:

| Reason | Detail |
|---|---|
| **It generalises** | A pixel model learns skin tone, sleeve colour, lighting and background along with handshape. A landmark model cannot see any of those — they are not in its input. |
| **It is tiny** | The ASL model has **60,892 parameters** and a 753 KB file. A comparable image CNN is tens of millions of parameters. |
| **It is fast** | Median server-side inference is **0.7 ms** for the letter models. |

The cost is that MediaPipe becomes a hard dependency, and anything it cannot see
— a hand too far from the camera, heavy occlusion — is invisible to the model
too.

**Three models exist**, because three different problems are being solved:

| Model | Internal name | Problem | Input | Architecture |
|---|---|---|---|---|
| **A** | `static` | ASL letters (one hand) | 63 numbers, one frame | MLP |
| **B** | `dynamic` | ISL **words** (movement matters) | 30 frames × 132 numbers | Bidirectional LSTM |
| **C** | `isl` | ISL letters (two hands) | 126 numbers, one frame | MLP |

## 10.2 Datasets

### 10.2.1 ASL Alphabet — trains Model A

| Property | Value | Source |
|---|---|---|
| Name | **ASL Alphabet** (`grassknoted/asl-alphabet`) | `ml/models/dataset_manifest.json` |
| Source link | https://www.kaggle.com/datasets/grassknoted/asl-alphabet | manifest + `download_datasets.py` |
| Citation | Akash. *ASL Alphabet*. Kaggle, 2018. | `download_datasets.py::ASL_ALPHABET` |
| Licence | **GPL 2** per the dataset's Kaggle page — research/education use | `download_datasets.py::ASL_ALPHABET.licence` |
| **Recorded by us?** | **No.** `self_recorded_data: false` | `dataset_manifest.json` |
| Format of one sample | A colour JPEG of one hand making one letter, in a folder named for that letter |
| Classes | **28** | manifest |
| Full class list | `A B C D E F G H I J K L M N O P Q R S T U V W X Y Z del space` | manifest |
| Samples after landmark extraction | **41,609** usable rows… | see note below |

**Class counts before balancing** (rows that survived landmark extraction):

| | | | | | | | |
|---|---|---|---|---|---|---|---|
| A 2295 | B 2250 | C 2119 | D 2583 | E 2344 | F 2907 | G 2562 | H 2472 |
| I 2473 | J 2647 | K 2742 | L 2599 | M 1957 | **N 1529** | O 2349 | P 2127 |
| Q 2229 | R 2617 | S 2640 | T 2403 | U 2557 | V 2596 | W 2519 | X 2237 |
| Y 2637 | Z 2429 | del 2042 | space 1983 | | | | |

**One class was dropped: `nothing`.** The dataset ships a `nothing` class of
images containing no hand. MediaPipe finds no landmarks in them, so there is
nothing to classify — 99.9 % of the class was discarded during extraction, and
the 14 rows that survived are false detections. The manifest records this
explicitly. The neutral state is handled **in the pipeline instead**: when no
hand is detected the backend emits `nothing` without calling the model at all.

**Balancing.** Mode `min`: every class is reduced to the size of the smallest,
**N at 1529**, giving 28 × 1529 = **42,812**… and the manifest records a
post-balancing total of **42,812** rows before splitting.

**Split.** `contiguous_by_capture_order`, fractions 0.7 / 0.15 / 0.15:

| Split | Samples | Note |
|---|---|---|
| Train | **29,960** before augmentation → **119,840** after | ×4 from augmentation |
| Validation | **6,412** | |
| Test | **6,440** | |

The split is **contiguous, not random**, and the manifest states why: *"ASL
Alphabet frames are consecutive video frames, so a random split leaks
near-duplicate images across train and test and inflates accuracy."* Contiguous
blocks keep neighbouring frames together. The manifest is also explicit that
*"the dataset has no signer metadata, so no split can guarantee an unseen signer
in test."*

**Augmentation** (train split only, seed 42): 2 rotation rounds up to ±12°,
coordinate noise σ = 0.015, horizontal mirroring. **Scale jitter is deliberately
omitted** — normalisation divides by the largest distance from the wrist, so
scaling a sample and re-normalising returns the original vector. Scale jitter is
a mathematical no-op under this representation.

### 10.2.2 Indian Sign Language alphabet — trains Model C

| Property | Value | Source |
|---|---|---|
| Name | **not recorded** | see below |
| Source link | **not recorded** | |
| Citation | **not recorded** — `download_datasets.py` holds the placeholder *"Record the dataset's own citation here once one is chosen."* | `download_datasets.py::ISL_ALPHABET` |
| Licence | **not recorded** — the spec says *"Varies by dataset — check the Kaggle page before use"* | same |
| **Recorded by us?** | **No.** `self_recorded_data: false` | `isl_dataset_manifest.json` |
| On-disk location | `ml/data/raw/isl_alphabet/`, **35 class folders** (verified by listing it now) | |
| Format of one sample | A colour image of two hands making one ISL letter or digit, in a folder named for that class |
| Classes | **35** | `isl_dataset_manifest.json`, `labels_isl.json` |
| Full class list | `1 2 3 4 5 6 7 8 9 A B C D E F G H I J K L M N O P Q R S T U V W X Y Z` | `labels_isl.json` |
| Samples after extraction | **41,609** | `isl_dataset_manifest.json` |

> **This is the most significant "not recorded" in the project.**
> `ISL_ALPHABET` in `ml/scripts/download_datasets.py` has `kaggle_slug=""` on
> purpose, with a comment explaining that several ISL alphabet datasets exist
> with different class sets and very different quality, and that naming one the
> script had not verified would be an invented path. The dataset was then chosen
> and downloaded by hand, and **its identity was never written back**.
>
> Worse, `isl_dataset_manifest.json` records
> `"source_dataset": "ASL Alphabet (grassknoted/asl-alphabet)"` and the ASL
> Kaggle URL — inherited from the shared preprocessing template — while its
> `alphabet`, `classes` (35) and `feature_count` (126) are unmistakably the ISL
> ones. The `split.rationale` text also still talks about "ASL Alphabet frames".
>
> **To obtain it:** the person who downloaded the dataset must identify it. Its
> name, URL and licence should then be written into `ISL_ALPHABET` and the
> manifest regenerated. Recorded as issue **K-5**. **Until then, no licence
> claim can be made for Model C's training data, and the model's provenance
> cannot be fully defended.**

**Class counts before balancing** — 33 classes at or near 1200, with
`C` 1104, `O` 1151, `P` 1199, `Q` 1171, **`S` 988**, `U` 1199, `V` 1197.
Total **41,609**.

**Balancing.** Mode `min` → every class reduced to **988** (the size of `S`),
giving 35 × 988 = **34,580**.

**Split.** `pose_disjoint`, `pose_threshold: 0.5`, fractions 0.7 / 0.15 / 0.15:

| Split | Samples |
|---|---|
| Train | **25,782** before augmentation → **103,128** after |
| Validation | **2,455** |
| Test | **6,343** |

**Why pose-disjoint, and what it exposed.** A random split over near-duplicate
video frames gives an inflated score. Clustering near-duplicate poses and holding
whole clusters out revealed that **7 of the 35 classes have fewer than 3 distinct
poses in the source data**, so nothing could be held out for them at all:

| Class | Distinct poses | Images |
|---|---|---|
| `1` | 1 | 988 |
| `2` | 2 | 988 |
| `3` | 1 | 988 |
| `4` | 1 | 988 |
| `5` | 1 | 988 |
| `8` | 1 | 988 |
| `L` | 1 | 988 |

Those seven are **not evaluated**, and the evaluation report says so in a
dedicated `honest_summary` block. This is the single most important honesty
measure in the project's ML work.

**Augmentation.** Identical to the ASL pipeline: 2 rotation rounds, ±12°,
noise σ = 0.015, mirroring, no scale jitter, seed 42.

### 10.2.3 INCLUDE — trains Model B

| Property | Value | Source |
|---|---|---|
| Name | **INCLUDE** (Indian Sign Language, word level) | `ml/models/dynamic_manifest.json` |
| Citation | Sridhar, A., Ganesan, R.G., Kumar, P., Khapra, M. *INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition.* ACM MM 2020. | `dynamic_manifest.json` |
| Source link | **not recorded in the manifest.** `download_datasets.py` records a Kaggle link for WLASL (`risangbaskoro/wlasl-processed`), which is a *different* dataset; the INCLUDE path has no slug recorded | |
| Licence | **not recorded** for INCLUDE. `download_datasets.py` records "Research use, per the WLASL project terms" for WLASL only | |
| **Recorded by us?** | **No.** `self_recorded_data: false` | `dynamic_manifest.json` |
| Format of one sample | A short video clip of one signer performing one word, converted to **30 frames × 132 features** |
| Classes | **41** total = **40 words** + 1 internal `__transition__` class | `labels_dynamic.json` |
| On-disk location | `ml/data/raw/include/` | verified by listing |

**Full class list (40 words):**
`bad`, `bank`, `big large`, `city`, `cold`, `cool`, `court`, `dry`, `extra`,
`fast`, `good`, `ground`, `happy`, `he`, `healthy`, `hospital`, `hot`, `house`,
`i`, `india`, `it`, `library`, `location`, `loud`, `market`, `narrow`, `new`,
`old`, `quiet`, `she`, `sick`, `slow`, `small little`, `they`, `warm`, `we`,
`wet`, `you`, `you (plural)`, `young`
— plus **`__transition__`**, an internal class taught deliberately so the model
can recognise the junk window that straddles two signs rather than being forced
to answer with a real word. It is excluded from `user_facing_classes`, which is
why `/health` reports **40** classes for a model with 41 outputs.

**Clips per class:** 19 to 21 (`house` 19, most 20 or 21). Total clips
**≈ 810**.

**Split.** `split_strategy_requested: "signer"`, `split_strategy: "random"`,
`signer_disjoint: **false**`, `signers_recorded_by_dataset: false`.

> **This is an honest, recorded limitation.** A signer-disjoint split — training
> on some people and testing on others — is the only way to know a model
> generalises to a **new signer**. The manifest records that a signer split was
> *requested* and could not be done, because this dataset as processed records no
> signer identity. `signers_per_split` is `[-1]` everywhere, a sentinel meaning
> "unknown". So **Model B's test score may be optimistic about an unseen
> signer**, and the project says so in the artefact rather than quietly using a
> random split.

| Split | Samples |
|---|---|
| Train | **8,932** (after augmentation) |
| Validation | **119** |
| Test | **149** |

**Augmentation** (train only): rotation ±12°, noise σ = 0.015, mirroring, and
**masked frames preserved** — an all-zero frame must stay all-zero or the
Masking layer would stop skipping it.

### 10.2.4 Was any data recorded by us?

**No.** All three manifests record `self_recorded_data: false`. Two scripts use
the webcam — `ml/scripts/test_realtime.py` and `ml/scripts/record_eval_clip.py` —
and both only **evaluate** an already-trained model. Neither writes a training
sample.

## 10.3 Feature extraction

### 10.3.1 The normalisation, step by step

Implemented in `backend/app/ml/normalization.py` (the canonical version) and
mirrored in `frontend/src/utils/landmarkUtils.js`.

`NORMALIZATION_VERSION = 1`. `metadata.json` records the version each model was
trained with, and `predictor.py` **refuses to load** a model whose version does
not match — turning a stale model file into a loud startup error rather than a
silent accuracy collapse.

For one hand (`normalize_hand`):

| Step | Operation | Why |
|---|---|---|
| 1 | **Validate** the input is exactly 21 × 3 | Deliberately strict. Silently padding a malformed frame would let corrupt data reach the model |
| 2 | **Translate**: subtract landmark 0 (the wrist) from all 21 points | Makes the features **position-invariant** — the letter A is the letter A wherever in frame it is signed |
| 3 | **Scale**: divide by the largest distance from the wrist, so the furthest landmark is at 1.0 | Makes the features **scale-invariant** — a hand near the camera and the same hand far away give the same vector |
| 4 | **Guard**: if that largest distance is below `1e-8`, return all zeros | Every landmark on top of the wrist is not a real hand; dividing would produce infinities |
| 5 | **Flatten** row-major: `x0,y0,z0,x1,y1,z1,…` | The order is fixed by MediaPipe's landmark indexing and must never be re-sorted |

Result: **63 float32 values** per hand.

### 10.3.2 The three feature layouts

| Function | Width | Layout | Used by |
|---|---|---|---|
| `normalize_primary_hand(hands)` | **63** | One hand's 63 values | Model A (ASL letters) |
| `normalize_hands(hands)` | **126** | `[left_hand(63), right_hand(63)]` | Model C (ISL letters) |
| `sequence_frame_features(hands)` | **132** | `[0:126]` two-hand shape · `[126:129]` left wrist `(x,y,z)` · `[129:132]` right wrist `(x,y,z)` | Model B (ISL words), one frame of 30 |

**Hand ordering.** Slots are assigned **by handedness, not by detection order**.
MediaPipe reports hands in whatever order it found them, so without this the same
letter would land in two different arrangements from frame to frame and the model
would have to learn both separately. `handedness` is matched case-insensitively
on a leading `l`, because the value crosses the network from the browser.

**Missing hand.** Zero-filled. A frame with no hands is 126 zeros (or 132 for
sequences). This is also what the training pipeline recorded for a hand-free
frame, and what Model B's Masking layer skips.

**Duplicate handedness.** If MediaPipe reports two hands with the same handedness
— which it does occasionally — the second **overwrites** the first rather than
being placed in the other slot. One duplicated hand is recoverable; a right hand
sitting in the left slot is not.

**Mirroring.** Used in two distinct ways:

| Where | What |
|---|---|
| **Training augmentation** | Horizontal mirroring doubles the training data, so a left-handed signer is not a new problem |
| **Display only** | Your own video tile and the hand-overlay canvas are mirrored, because an unmirrored self-view is disorienting to sign into. The **remote tile is not mirrored** — flipping the other person's signs could change which sign is read |

Mirroring is **not** applied to live inference input. The landmarks sent to the
server are as MediaPipe produced them.

### 10.3.3 Why word signs need position, and letters must not have it

`normalize_hands` **deliberately destroys position** by moving every wrist to the
origin. For fingerspelling that is exactly right and is why Model A generalises.

For word signs it throws away most of the meaning. A word sign is defined by its
**trajectory** and **location** as much as by handshape, and a wrist pinned to the
origin in every frame cannot express either — the feature vector is literally
identical for a hand held still and a hand sweeping across the body.

The docstring in `normalization.py` records that this was **measured, not
theorised**: trained on shape alone, the model's top confusions were all movement
pairs — *bad/good*, *big/small*, *dry/wet*, *they/you* — words whose handshapes
are near-identical and whose difference **is** the movement.

So `sequence_frame_features` appends the raw wrist position of each hand.
Position is left in image coordinates per frame; `center_sequence_positions`
then subtracts the mean wrist position **over the whole window**, per hand, so
what survives is movement relative to the sign's own centre. That needs the
whole window and therefore cannot happen per frame.

## 10.4 The three models

All three were loaded with TensorFlow **2.16.2** while writing this document, and
every parameter count below was measured with `model.count_params()`.

### 10.4.1 Model A — `static_model.keras` (ASL letters)

| Property | Value |
|---|---|
| Purpose | Classify one static ASL handshape into one of 28 classes |
| Framework | TensorFlow / Keras 2.16.2 |
| Training script | `ml/scripts/train_static.py` |
| File | `ml/models/static_model.keras`, **771,418 bytes** (753 KB) |
| Input shape | `(None, 63)` |
| Output shape | `(None, 28)` |
| **Total parameters** | **60,892** |
| Trainable | 60,124 |
| Non-trainable | 768 (BatchNormalization moving statistics) |
| Trained at | 2026-08-22T05:41:27 UTC |
| Training time | **62.3 seconds** |

**Architecture, layer by layer** (measured):

| # | Layer | Name | Output shape | Params | Configuration |
|---|---|---|---|---|---|
| 1 | `Dense` | `dense_256` | (None, 256) | 16,384 | 256 units, ReLU |
| 2 | `BatchNormalization` | `bn_1` | (None, 256) | 1,024 | |
| 3 | `Dropout` | `dropout_1` | (None, 256) | 0 | rate 0.3 |
| 4 | `Dense` | `dense_128` | (None, 128) | 32,896 | 128 units, ReLU |
| 5 | `BatchNormalization` | `bn_2` | (None, 128) | 512 | |
| 6 | `Dropout` | `dropout_2` | (None, 128) | 0 | rate 0.3 |
| 7 | `Dense` | `dense_64` | (None, 64) | 8,256 | 64 units, ReLU |
| 8 | `Dense` | `predictions` | (None, 28) | 1,820 | 28 units, **softmax** |

An **MLP** (multi-layer perceptron — plain fully-connected layers) is the right
shape here because a single frame's 63 numbers have no sequence and no spatial
grid; there is nothing for a convolution or a recurrence to exploit.

**Hyperparameters:** Adam, learning rate 0.001,
`sparse_categorical_crossentropy`, batch size 64, max 100 epochs,
**18 epochs actually run**, early-stopping patience 10, seed 42.

**Training metrics:** train accuracy 0.9928, validation accuracy 0.9404,
validation loss 0.3335, train–val gap 0.0523.
Samples: train 119,840, validation 6,412.

### 10.4.2 Model C — `isl_model.keras` (ISL letters)

| Property | Value |
|---|---|
| Purpose | Classify one static **two-handed** ISL handshape into one of 35 classes |
| Framework | TensorFlow / Keras 2.16.2 |
| Training script | `ml/scripts/train_static.py` (the same script, different data and width) |
| File | `ml/models/isl_model.keras`, **970,418 bytes** (948 KB) |
| Input shape | `(None, 126)` |
| Output shape | `(None, 35)` |
| **Total parameters** | **77,475** |
| Trainable | 76,707 |
| Non-trainable | 768 |
| Trained at | 2026-10-04T11:04:56 UTC |
| Training time | **85.1 seconds** |

**Architecture:** identical to Model A except the first layer's input width and
the output width.

| # | Layer | Name | Output shape | Params |
|---|---|---|---|---|
| 1 | `Dense` | `dense_256` | (None, 256) | **32,512** (vs 16,384 — twice the input) |
| 2 | `BatchNormalization` | `bn_1` | (None, 256) | 1,024 |
| 3 | `Dropout` | `dropout_1` | (None, 256) | 0 (rate 0.3) |
| 4 | `Dense` | `dense_128` | (None, 128) | 32,896 |
| 5 | `BatchNormalization` | `bn_2` | (None, 128) | 512 |
| 6 | `Dropout` | `dropout_2` | (None, 128) | 0 (rate 0.3) |
| 7 | `Dense` | `dense_64` | (None, 64) | 8,256 |
| 8 | `Dense` | `predictions` | (None, 35) | **2,275** |

**Why a separate model and not a retrained Model A.** ISL fingerspells with
**both** hands where ASL uses one. That changes the input from 63 to 126 floats,
so Model A's weights are not merely less accurate here — they are the **wrong
shape**.

**Hyperparameters:** Adam, learning rate 0.001,
`sparse_categorical_crossentropy`, batch size 64, max 100 epochs,
**20 epochs run**, patience 10, seed 42.

**Training metrics:** train accuracy 0.9997, validation accuracy 0.9919,
validation loss 0.0589, train–val gap 0.0078.
Samples: train 103,128, validation 2,455.

### 10.4.3 Model B — `dynamic_model.keras` (ISL words)

| Property | Value |
|---|---|
| Purpose | Classify a 30-frame window of two-hand motion into one of 40 words (plus a transition class) |
| Framework | TensorFlow / Keras 2.16.2 |
| Training script | `ml/scripts/train_dynamic.py` |
| File | `ml/models/dynamic_model.keras`, **5,375,649 bytes** (5.1 MB) |
| Input shape | `(None, 30, 132)` |
| Output shape | `(None, 41)` |
| **Total parameters** | **442,537** |
| Trainable | 442,537 |
| Non-trainable | 0 |
| Trained at | 2026-08-27T14:13:11 UTC |
| Training time | **451.9 seconds** (7 m 32 s — the longest run in the project, well inside the 30-minute CPU constraint) |

**Architecture, layer by layer** (measured):

| # | Layer | Name | Output shape | Params | Configuration |
|---|---|---|---|---|---|
| 1 | `Masking` | `mask_empty_frames` | (None, 30, 132) | 0 | `mask_value = 0.0` |
| 2 | `Bidirectional(LSTM)` | `bilstm_128` | (None, 30, 256) | **267,264** | 128 units each direction, `return_sequences=True` |
| 3 | `Dropout` | `dropout_1` | (None, 30, 256) | 0 | rate 0.3 |
| 4 | `Bidirectional(LSTM)` | `bilstm_64` | (None, 128) | **164,352** | 64 units each direction, `return_sequences=False` |
| 5 | `Dropout` | `dropout_2` | (None, 128) | 0 | rate 0.3 |
| 6 | `Dense` | `dense_64` | (None, 64) | 8,256 | 64 units, ReLU |
| 7 | `Dense` | `predictions` | (None, 41) | 2,665 | 41 units, **softmax** |

**Why an LSTM and not an MLP.** A word sign is a **sequence**. An LSTM (Long
Short-Term Memory — a recurrent layer that carries state across timesteps) can
represent "the hand moved from here to there"; a flat MLP over 30 concatenated
frames cannot, without learning every temporal alignment separately.

**Why bidirectional.** The clip is already complete when it is classified, so
there is no reason to read it only forwards. Reading it in both directions lets
the model use the end of the sign to interpret the beginning.

**Why Masking.** A frame with no hands is all zeros. `Masking(mask_value=0.0)`
tells the LSTM to **skip** those timesteps rather than treating "no hands" as a
meaningful posture. `masked_timestep_fraction: 0.1262` is recorded — about 13 %
of all training timesteps were masked.

**Hyperparameters:** Adam, learning rate 0.001,
`sparse_categorical_crossentropy`, batch size 32, max 150 epochs,
**34 epochs run**, patience 20, **class weights enabled**, seed 42.

**Training metrics:** train accuracy 0.8990, validation accuracy 0.8571,
validation loss 0.7313, train–val gap 0.0419.
Samples: train 8,932, validation 119.

### 10.4.4 How models are loaded and served

`backend/app/ml/predictor.py` defines `SignPredictor`, with three module-level
instances: `predictor` (static), `isl_predictor`, `dynamic_predictor`. Each:

- loads its `.keras` file **once**, during FastAPI's `lifespan` startup — never
  per request, which would add hundreds of milliseconds to a system whose point
  is sub-second response;
- **checks `normalization_version`** against the code's own and refuses to load
  on a mismatch;
- compiles a `tf.function` for inference. This matters a great deal: the commit
  log records a **75× latency improvement** (1373 ms → 18 ms) from this, because
  Masking combined with LSTM otherwise forces a per-timestep eager path;
- treats a **missing model as non-fatal**. Auth, meetings and transcripts must
  still work while someone is training a model; the socket reports
  `MODEL_NOT_LOADED` to any client that connects.

## 10.5 Evaluation

### 10.5.1 Headline results

All measured on the **held-out test split**, by `ml/scripts/evaluate.py`, and
recorded in the three `*_evaluation_report.json` files.

| Model | Split | Test samples | Top-1 | Top-3 | Macro F1 | Weighted F1 |
|---|---|---|---|---|---|---|
| **A** — ASL letters | contiguous test | **6,440** | **0.9053** | 0.9691 | 0.9055 | 0.9055 |
| **C** — ISL letters | pose-disjoint test | **6,343** | **0.9814** | 0.9820 | **0.7287** | 0.9744 |
| **B** — ISL words | random test | **149** | **0.8523** | 0.9463 | 0.8303 | 0.8533 |

### 10.5.2 Model A in detail

Macro average: precision 0.9126, recall 0.9053, F1 0.9055, support 6,440.
Weighted average is identical, which tells you the test classes are balanced.

Top-1 **0.9053** is the number to quote for Model A. Note it is **lower** than
the 0.9404 validation accuracy in `metadata.json` — the test split is contiguous
and therefore genuinely harder than validation, which is the point.

### 10.5.3 Model C — why the headline number is misleading, and what to quote instead

This is the most important subtlety in the project's ML work, and the evaluation
report addresses it in a dedicated `honest_summary` block:

```json
{
  "split": "pose_disjoint",
  "note": "Weighted top-1 is inflated by class size. The macro recall over
           classes that actually have held-out samples is the honest headline.
           Seven classes have fewer than 3 distinct poses in the source data,
           so nothing could be held out for them and they are not evaluated.",
  "classes_total": 35,
  "classes_judgeable": 28,
  "classes_not_judgeable": ["1", "2", "3", "4", "5", "8", "L"],
  "macro_recall_judgeable": 0.9204,
  "classes_at_zero_recall": ["H", "J"]
}
```

| Figure | Value | What it means |
|---|---|---|
| Weighted top-1 | 0.9814 | **Inflated.** Dominated by a few classes with hundreds of test samples |
| Macro F1 over all 35 | 0.7287 | Dragged down by nine classes at zero |
| **Macro recall over the 28 judgeable classes** | **0.9204** | **The honest headline for Model C** |
| Classes with no held-out samples | 7 — `1 2 3 4 5 8 L` | Fewer than 3 distinct poses in the source; cannot be judged at all |
| **Classes that genuinely fail** | **`H` and `J`, both at 0.0000 recall** | `H` has 94 test samples and `J` has 11, and the model gets **none** of either right |

**Per-class recall, every one of the 35 classes:**

| Class | Recall | Precision | Support | Class | Recall | Precision | Support |
|---|---|---|---|---|---|---|---|
| `1` | 0.0000 | 0.0000 | **0** | `K` | 1.0000 | 1.0000 | 62 |
| `2` | 0.0000 | 0.0000 | **0** | `L` | 0.0000 | 0.0000 | **0** |
| `3` | 0.0000 | 0.0000 | **0** | `M` | 1.0000 | 1.0000 | 541 |
| `4` | 0.0000 | 0.0000 | **0** | `N` | 1.0000 | 0.9975 | 406 |
| `5` | 0.0000 | 0.0000 | **0** | `O` | 1.0000 | 0.9942 | 172 |
| `6` | 1.0000 | 1.0000 | 740 | `P` | 1.0000 | 1.0000 | 48 |
| `7` | 1.0000 | 1.0000 | 182 | `Q` | 0.9952 | 1.0000 | 419 |
| `8` | 0.0000 | 0.0000 | **0** | `R` | 1.0000 | 0.9765 | 83 |
| `9` | 1.0000 | 1.0000 | 825 | `S` | 1.0000 | 1.0000 | 126 |
| `A` | 1.0000 | 0.7714 | 27 | `T` | 1.0000 | 1.0000 | 66 |
| `B` | 1.0000 | 1.0000 | 133 | `U` | 0.9855 | 1.0000 | 207 |
| `C` | 0.9355 | 0.7838 | 31 | `V` | 0.9231 | 1.0000 | 13 |
| `D` | 1.0000 | 1.0000 | 497 | `W` | 0.9972 | 0.7879 | 354 |
| `E` | 1.0000 | 1.0000 | 41 | `X` | 1.0000 | 1.0000 | 440 |
| `F` | 1.0000 | 1.0000 | 153 | `Y` | 1.0000 | 1.0000 | 168 |
| `G` | 1.0000 | 1.0000 | 157 | `Z` | 0.9355 | 1.0000 | 62 |
| **`H`** | **0.0000** | **0.0000** | **94** | | | | |
| `I` | 1.0000 | 1.0000 | 285 | | | | |
| **`J`** | **0.0000** | **0.0000** | **11** | | | | |

### 10.5.4 Model B in detail

Macro average: precision 0.8549, recall 0.8293, F1 0.8303, support 149.
Weighted: precision 0.8772, recall 0.8523, F1 0.8533.

**The test set is 149 clips across 41 classes** — fewer than 4 per class. A
single misclassification moves the score by about 0.7 percentage points, so this
number carries a wide confidence interval. It should be quoted as "about 85 % on
149 held-out clips", never as "85.23 %".

### 10.5.5 Continuous signing — word error rate

`ml/models/continuous_evaluation_report.json`, produced by
`ml/scripts/evaluate_continuous.py`, which strings held-out clips into one
continuous stream:

| Condition | Word error rate | Reference words | Substitutions | Deletions | Insertions | Hits |
|---|---|---|---|---|---|---|
| `gap_0` — signs run together, no pause | **0.1750** | 120 | 11 | 7 | 3 | 102 |
| `gap_10` — a 10-frame pause between signs | **0.3417** | 120 | 22 | 16 | 3 | 82 |

**The counter-intuitive result is the interesting one: pausing makes it worse.**
17.5 % error with no pause, 34.2 % with one. The cause is recorded in
`.env.example`: `DYNAMIC_BUFFER_RESET_FRAMES` used to be 8, so a pause cleared
the 30-frame buffer and forced a full refill — exactly one sign's length — and
the sign immediately after any pause was missed entirely. Raising it to 30 cut
the no-pause rate from 23.3 % to 17.5 %.

### 10.5.6 Idle false positives — the measurement that changed the design

`ml/models/gate_measurement.json`, from `ml/scripts/measure_gates.py`. This
measures what the models do when **nobody is signing**, with the live gates
applied (`confidence_floor: 0.70`, `margin_floor: 0.15`).

**Accuracy of what gets accepted:**

| Model | Samples | Accepted | Rejected | Rejection rate | Accuracy **of accepted** | Accuracy overall |
|---|---|---|---|---|---|---|
| ISL words | 149 | 141 | 8 | 5.37 % | **0.8865** | 0.8389 |
| ISL letters | 6,343 | 6,327 | 16 | 0.25 % | **0.9837** | 0.9812 |

**False-positive rate on idle input** — 400 trials each:

| Model | Idle condition | Passed the gates | **False-positive rate** |
|---|---|---|---|
| ISL words | all-zero frames | 0 / 400 | **0.0 %** |
| ISL words | a frozen pose | 227 / 400 | **56.75 %** |
| ISL words | random landmarks | 209 / 400 | **52.25 %** |
| ISL letters | all-zero frames | **400 / 400** | **100.0 %** |
| ISL letters | random landmarks | 327 / 400 | **81.75 %** |

**Read those numbers carefully, because they are the honest core of this
project's limitations.**

- **ISL letters fires on empty input 100 % of the time.** Fed 126 zeros — no
  hands at all — the model passes both gates every single time. The reason is in
  the data: about 31 % of the ISL training slots were legitimately empty (one
  hand absent in a two-hand vector), so the model learned that an empty slot is
  a meaningful pattern. **No confidence or margin threshold can fix this**,
  because the model is not uncertain — it is confidently wrong.
- **A frozen pose fools the word model 57 % of the time.** A hand held still in
  a valid handshape genuinely *is* a valid handshape; the model is not wrong to
  be confident about it.

**What was done about it.** Because no probability threshold can separate
"resting in this shape" from "signing this letter", and because a parked hand is
perfectly *stable* so stability gating cannot help either, the only remaining
signal is **movement**. `MOTION_LOOKBACK_FRAMES = 20` in
`frontend/src/config/recognition.js` requires real movement within the last 20
frames (2 seconds at 10 Hz) before anything is committed. The comment in that
file records this measurement as its justification.

**The practical consequence:** a hand left in frame stops producing captions
about two seconds after it stops moving. The acceptance check for this is
"hands resting in frame for 30 seconds produces zero captions", and it requires
a human at a camera.

### 10.5.7 End-to-end latency through the real code path

`ml/models/inference_path_report.json`, from
`ml/scripts/test_inference_path.py`, which feeds held-out samples through the
**live** inference functions rather than calling Keras directly:

| Model | Samples | Top-1 accuracy | **Median latency** |
|---|---|---|---|
| ASL letters | 6,440 | 0.9053 | **0.70 ms** |
| ISL fingerspelling | 6,343 | 0.9814 | **0.71 ms** |
| ISL words | 149 clips (0 skipped) | 0.8523 | **6.12 ms** |

These are server-side inference times only — not end-to-end user-perceived
latency, which also includes MediaPipe, the network, and the client-side
segmentation gates.

### 10.5.8 Confusion matrices

Full 28×28, 35×35 and 41×41 confusion matrices are stored in the three
`*_evaluation_report.json` files under `confusion_matrix`, with the 12 strongest
confusions per model under `top_confusions`. `ml/scripts/evaluate.py` also
renders them as PNGs into `docs/images/`.

## 10.6 Live inference pipeline: how a prediction becomes a caption

A prediction is **not** a caption. Between them sit two layers of gates — one on
the server, one in the browser — and the client owns the final decision.

### 10.6.1 Server-side: `PredictionSmoother`

`backend/app/ml/smoothing.py`. Four mechanisms in order:

| # | Mechanism | What it does |
|---|---|---|
| 1 | **Confidence gate** | Discard any prediction below `confidence_threshold` |
| 2 | **Majority vote** | Accept a label only if it wins `majority_min` of the last `majority_window` frames |
| 3 | **Cooldown** | After emitting a label, suppress the same label for `cooldown_ms` |
| 4 | **Neutral reset** | `neutral_reset_frames` consecutive `nothing` frames close the current word |

All four values come from `.env` via `backend/app/config.py`. **Two profiles:**

| Setting | Static / ISL letters | Dynamic (words) | Why they differ |
|---|---|---|---|
| `confidence_threshold` | **0.80** | **0.70** | 40 word classes trained on ~20 clips each produce flatter softmax output than 28 letter classes trained on thousands; reusing 0.80 would reject nearly everything |
| `cooldown_ms` | **1500** | **2500** | A word sign takes 1–2 seconds, so a 1.5 s debounce could fire twice inside one sign |
| `majority_window` | **10** | **5** | Consecutive dynamic predictions come from windows overlapping by 29/30 frames — nearly the same evidence counted again, not independent confirmation |
| `majority_min` | **7** | **3** | — |
| `neutral_reset_frames` | **8** | **8** (`DYNAMIC_RESET_FRAMES`) | Clears the debounce so a word can be repeated after a pause |

`SmoothingConfig.__post_init__` raises if `majority_min > majority_window`,
because that threshold could never be met and the system would silently never
emit anything.

### 10.6.2 Server-side: `SequenceBuffer` (word mode only)

`backend/app/ml/sequence.py`. A rolling 30-frame window with two heuristics:

| Heuristic | Setting | Effect |
|---|---|---|
| **Hands gone is a boundary** | `dynamic_buffer_reset_frames = 30` | A run of hand-free frames clears the window |
| **Enough hand to classify** | `dynamic_min_detection_rate = 0.30` | A window with less than 30 % hand-bearing frames is not classified at all — the same threshold used when deciding which training clips were usable |
| **Stride** | `dynamic_stride = 3` | Classify every 3rd frame, not every frame, since consecutive windows overlap by 29/30 |

`reset_after_empty` is deliberately as long as the window itself, making it
almost a no-op — the deque already ages frames out. It was 8, and that was
**measurably harmful**: see the continuous word error rates above.

### 10.6.3 Client-side: the four gates and segmentation

`frontend/src/hooks/useSignCaptions.js`, every threshold from
`frontend/src/config/recognition.js`. **This file is the single place these
values live.**

| Constant | Value | Purpose |
|---|---|---|
| `MIN_CONFIDENCE` | **0.70** | Softmax floor. With 40 classes, chance is 2.5 %, so 0.70 is far above "better than guessing" |
| `MIN_MARGIN` | **0.15** | Gap to the runner-up. A model can be 0.72 confident while second place is 0.70 — it cannot really tell them apart, and a clear margin is what stops near-ties being committed as fact |
| `REST_MOTION` | **0.012** | Mean per-landmark displacement between frames, in normalised units where a hand spans 1.0. Below this the hands are still |
| `MOVING_MOTION` | **0.030** | Above this the hands are travelling, which is what a word sign **is** |
| `REST_FRAMES_TO_END_SEGMENT` | **4** | Consecutive still frames that end a movement segment. 0.4 s at 10 Hz |
| `UTTERANCE_END_MS` | **1500** | Hands absent or at rest this long closes the caption segment and sends the final event |
| `LETTER_STABLE_FRAMES` | **6** | A letter must hold steady this many frames before being committed. Fingerspelling has no movement to segment on, so stability is the only signal |
| `REQUIRE_REST_BEFORE_REPEAT` | **true** | After committing a token, the same token is not committed again until the hands return to rest. **This replaced a time-based cooldown** that fired again the moment it expired even though the signer had not moved — the direct cause of "warm warm warm" |
| `ABSENT_FRAMES_TO_CLEAR` | **3** | Frames with no hands before a frame counts as genuinely empty. One dropped detection mid-sign is noise, not an absence |
| `MOTION_LOOKBACK_FRAMES` | **20** | **The parked-hand gate.** Real movement must have occurred within this many frames or nothing is committed. Justified by the 100 % idle false-positive measurement above |

`SPEECH` constants in the same file: `MAX_RESTARTS` 40,
`RESTART_BASE_MS` 300, `RESTART_MAX_MS` 5000, `HEALTHY_RUN_MS` 15000.

### 10.6.4 How letters, words and boundaries are decided

| Decision | Mode | Rule |
|---|---|---|
| **Commit a letter** | `static`, `isl` | The same label is predicted for `LETTER_STABLE_FRAMES` (6) consecutive frames, passes confidence and margin, and there was movement within `MOTION_LOOKBACK_FRAMES` (20). Not repeated until the handshape changes or the hand leaves frame |
| **Commit a word** | `dynamic` | A **movement segment** is detected — hands leave rest (motion > `MOVING_MOTION`), move, then return to rest (`REST_FRAMES_TO_END_SEGMENT` still frames) — and the window's prediction passes the gates. Committed **once per segment**, never per sliding window |
| **End a segment** | all | Hands absent or at rest for `UTTERANCE_END_MS` (1500 ms). The client then sends `is_final: true` and generates a new `segment_id` |
| **Suppress a repeat** | all | `REQUIRE_REST_BEFORE_REPEAT` — the hands must return to rest before the same token can be committed again |
| **Neutral** | all | No hands detected → the backend emits `nothing` **without calling the model**. This is why `nothing` is not a trained class |

**Why segmentation lives in the browser and not the server.** It used to be
split: a Python smoother held half the decision and a JavaScript buffer held the
other half, and the two disagreed. Everything the client needs — the per-frame
prediction, the margin, and the raw landmark motion — is available in the
browser, and the motion signal in particular never reaches the server. Keeping
the decision in one place is the point.

## 10.7 Limitations, stated plainly

| # | Limitation | The honest detail |
|---|---|---|
| 1 | **Vocabulary is 40 words plus two alphabets** | Not a translator. It recognises 40 isolated ISL words, 35 ISL letters and 28 ASL letters. Real sign language has tens of thousands of signs |
| 2 | **No grammar** | Output is recognised tokens joined together. ISL word order differs from English; nothing reorders it. "I hospital go" stays "I hospital go" |
| 3 | **Two classes genuinely do not work** | ISL letters `H` and `J` have **0.0000 recall** on 94 and 11 test samples. The model never gets them right |
| 4 | **Seven classes cannot be judged at all** | `1 2 3 4 5 8 L` have fewer than 3 distinct poses in the source data, so nothing could be held out. Their true accuracy is **unknown** |
| 5 | **Idle false positives are severe for letters** | 100 % on all-zero frames, 81.75 % on random landmarks. Mitigated by a movement gate in the client, not by the model |
| 6 | **No signer-disjoint evaluation anywhere** | Model B's data records no signer identity (`signer_disjoint: false`); the ASL and ISL letter datasets have no signer metadata either. **No model has been shown to generalise to a new signer.** This is the single biggest caveat on every accuracy figure here |
| 7 | **Continuous signing is the hard case** | 17.5 % word error rate with no pauses, 34.2 % with pauses, on a synthesised stream of held-out clips |
| 8 | **Model B's test set is tiny** | 149 clips across 41 classes — fewer than 4 each. One error moves the score ~0.7 pp |
| 9 | **Hard dependency on MediaPipe** | If MediaPipe cannot find a hand — too far away, badly lit, occluded — the model never sees anything. No fallback |
| 10 | **No facial or body grammar** | Sign languages carry grammatical meaning in facial expression, head position and body shift. Only hands are tracked, so that meaning is simply absent |
| 11 | **The ISL letters dataset's provenance is unrecorded** | Its name, source and licence are not written anywhere. Its licence compatibility therefore **cannot be confirmed** |
| 12 | **Validation accuracy is reported in the UI, not test accuracy** | The Settings dialog shows `val_accuracy` and labels it "validation accuracy". Validation is what early stopping was selected against, so it is optimistic by construction. The numbers to quote are in §10.5.1 |

