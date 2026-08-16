# BridgeTalk — Review Demo Guide

Everything you need on the day: a checklist, a five-minute script, and prepared
answers with real numbers.

---

## 1. Pre-demo checklist

Run through this **the evening before**, not ten minutes before.

**Software**

- [ ] MySQL running — `mysqladmin -u root -p ping` prints `mysqld is alive`
- [ ] `ml/models/static_model.keras`, `labels.json`, `metadata.json` present
- [ ] `frontend/public/models/hand_landmarker.task` present (~7.5 MB)
- [ ] `.env` filled in (database URL, JWT secret)
- [ ] Backend starts clean; `/health` shows `"model": {"loaded": true}`
- [ ] Frontend starts with **no red errors** in the browser console
- [ ] `pytest backend/tests -q` → 136 passed
- [ ] Log in once with each demo account so you know the passwords work

**Physical**

- [ ] No other app holding the camera (quit Zoom, Teams, Photo Booth)
- [ ] Light **on** your face and hands, not behind you — a window behind you
      turns your hand into a silhouette and MediaPipe loses it
- [ ] Plain background behind your signing hand
- [ ] Laptop plugged in — CPU throttling on battery visibly slows inference
- [ ] Browser zoom at 100%

**Insurance**

- [ ] **A screen recording of a working demo saved locally.** If the projector,
      the Wi-Fi or the camera misbehaves, you show the recording and talk over
      it. This costs ten minutes the night before and saves the review.
- [ ] `docs/images/confusion_matrix.png` open in a tab, ready to show

---

## 2. Five-minute demo script

### 0:00 — Frame the problem (30 seconds, no screen)

> "Zoom and Meet already caption speech, so a deaf person can read what a
> hearing person says. There's no reverse channel — a hearing person can't
> understand sign language without an interpreter. BridgeTalk builds that
> missing direction."

### 0:30 — The standalone model (60 seconds)

```bash
python ml/scripts/test_realtime.py
```

Sign **A**, **B**, **L**, **Y**. Point at the skeleton as it tracks.

> "Hand tracking is MediaPipe, running locally. It gives 21 joint positions.
> We classify those 21 points — not the image. That's why this trains in a
> minute on a CPU and why it doesn't care about my lighting or skin tone."

Point at the latency figure.

> "Six milliseconds per prediction."

**Why start here:** it proves the model works before any web plumbing is
involved. If the browser demo later misbehaves, you have already shown the hard
part working.

### 1:30 — The web app, two windows (90 seconds)

Normal window: log in as `deaf.demo@example.com`. Create a meeting. Read out
the code.

Incognito window: log in as `hearing.demo@example.com`, join by code.

> "Two participants, one machine. The video call is peer-to-peer WebRTC — our
> server only introduces them and then steps out. It never sees a video frame."

### 3:00 — Both directions (90 seconds)

Sign **H-E-L-L-O** slowly in the deaf window. Hold each letter about a second.

> "Watch the confidence bar. A letter is only accepted when it wins seven of
> the last ten frames — otherwise the output would flicker between letters on
> every frame."

Point at the other window as the text appears.

Turn on speech captions in the hearing window, say a sentence, point at the deaf
window.

> "And that's the direction that already exists — but now both are in one room,
> in one transcript."

Open the transcript panel.

### 4:30 — The honest number (30 seconds)

> "90.5% on a held-out test split, 96.9% top-three. It's lower live, and I can
> tell you exactly why."

Show the confusion matrix.

> "N and M. Both are a closed fist with the thumb tucked among the fingers, and
> the thumb is the landmark most often hidden by exactly those fingers. We saw
> it twice, independently: those two letters also had the highest discard rates
> when we extracted landmarks in the first place. It's a property of reducing
> a hand to 21 points, not a training bug."

---

## 3. Anticipated questions, with answers

### On the design

**Why send landmarks instead of raw video?**
Bandwidth: ~5 KB/s instead of 500 KB/s to 2 MB/s. Privacy: the video never
leaves the user's machine. Server cost: one small matrix multiply per frame
instead of the full MediaPipe pipeline per user. And it scales — tracking cost
sits with the client. The trade-off is that a browser without WebAssembly can't
run it at all, which for a laptop conferencing tool is an easy trade.

**Why MediaPipe rather than training your own CNN?**
Google trained that hand model on far more data than we could gather. More
importantly it gives us a representation that is already invariant to lighting
and skin tone. A CNN trained on ASL Alphabet would also memorise its
backgrounds and lighting and would fall apart in this room.

**Why FastAPI over Flask or Django?**
Native async WebSockets, which are the core of this project — Flask needs an
extension and Django Channels needs extra infrastructure. Plus Pydantic
validation and automatic OpenAPI docs, which is the `/docs` page.

**Why is the backend only a signalling server for the call?**
Because WebRTC media is peer-to-peer by design. Routing video through us would
add latency, cost bandwidth, and put private video on our server for no benefit.

### On the machine learning

**Why an MLP for static signs and an LSTM for dynamic ones?**
A letter is fully determined by one frame — there is no motion to model, so a
recurrent network would add parameters and training time for nothing. A word
sign *is* a movement; one frame of it is meaningless, so you need a network that
reads a sequence and remembers what came before.

**What is your accuracy, and why isn't it higher?**
90.5% top-1, 96.9% top-3, on 6,440 held-out samples. Two honest reasons it
isn't higher. First, M/N and R/U are genuinely ambiguous from 21 points. Second,
we split the data by capture order rather than randomly — the dataset is
consecutive video frames, so a random split would put near-identical frames in
both train and test and inflate the number. Our validation accuracy is 94%; the
gap to 90.5% *is* that honesty.

**Which classes does it confuse, and why?**
N→M at 37% and R→U at 37%. M and N are both closed fists differing only in how
many fingers the thumb tucks under — and the thumb is occluded by those fingers.
R and U are both two raised fingers; R crosses them, which is nearly invisible
once you only have fingertip positions.

**Why did you train only on public datasets?**
Reproducibility — anyone can download the same data and get the same model. And
honesty: if we'd trained on our own hands in this room and then tested on our
own hands in this room, the accuracy number would mean nothing.

**How do you handle prediction flicker?**
Four filters. Confidence gate at 0.80 removes transition frames. Majority vote
needs 7 of the last 10. A 1.5-second per-label debounce stops a held handshape
spelling `AAAAAAAA`. And eight empty frames reset it, so lowering your hand lets
you repeat a letter immediately.

**Your validation accuracy is high but live is worse. Why?**
The domain gap. The model learned this dataset's cameras, lighting and framing.
Mine are different. It's the most-cited limitation in applied sign recognition,
and it's why `test_realtime.py` exists — to measure it rather than assume it
away.

**How does this scale beyond fingerspelling?**
Same pipeline, different data and labels. Landmarks are language-agnostic, which
is exactly why moving to Indian Sign Language would mean swapping the dataset,
not rewriting the system. Word-level signs need the LSTM, which is specified.

### On the system

**What happens on a slow network?**
The client drops frames rather than queueing them — if the socket's buffer grows
past 64 KB we skip that frame. A backlog would make predictions arrive seconds
late, which is worse than missing some. The socket also reconnects with
exponential backoff and jitter.

**How is this different from Google Meet captions?**
Meet captions speech. It has nothing for the sign direction — that's the entire
gap this project addresses.

**Is Interview Mode real proctoring?**
No, and we say so in the interface. The browser tells us two things: this tab
lost focus, and this tab became hidden. It cannot see a second monitor, a phone,
notes on the desk, or another person in the room. It's a deterrent. Claiming
more would be dishonest and easy to disprove.

**How do you know your normalisation is consistent?**
There's a test that runs the same landmark array through the Python and the
JavaScript implementations and asserts they agree to one part in a million. And
we verified the test can fail — injecting a 0.001% divergence makes it fail with
a message naming the cause. A test that can't catch its own bug is worse than
no test.

---

## 4. Known weak spots, and what to say

| If this happens | Say this |
|---|---|
| A letter won't register | "The lighting here is flattening my hand, so the landmarks are noisy and the confidence gate is rejecting them." Then move to a letter you know works. |
| It predicts M when you sign N | "That's the confusion I mentioned — it's in my report, at 37%." This is a strength if you predicted it. |
| The call won't connect | "We use STUN but not TURN, so peers behind restrictive NAT can't find a direct path. That's a documented limitation." Fall back to two windows on one machine. |
| Speech captions are greyed out | "Web Speech API is Chrome and Edge only." |
| Camera fails on a second laptop | "Browsers only allow camera access over HTTPS or localhost. That's browser policy, not our code." |
| Everything breaks | Show the recording. "Let me show you the recorded run and walk through the architecture." |

**The rule: name the cause out loud and move on.** "The lighting is flattening
my hand" is a competent answer. Silently repeating the gesture until it works
is not.

---

## 5. Numbers to have memorised

| | |
|---|---|
| Test accuracy (top-1 / top-3) | **90.5% / 96.9%** |
| Validation accuracy | 94.0% |
| Test set size | 6,440 samples |
| Classes | 28 |
| Training time | **62 seconds, CPU** |
| Model size | 60,892 parameters |
| Inference latency (median) | **6.2 ms** |
| Images processed | 87,000 → 66,858 landmark vectors |
| Discard rate | 23.2% overall; N worst at 49% |
| Bandwidth to the server | ~5 KB/s |
| Tests | 136, all passing |
