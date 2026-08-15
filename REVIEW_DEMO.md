# BridgeTalk — Review Demo Guide

> **Phase 0 skeleton.** The demo script depends on what actually works, so it is
> written for real at the end of Phase 6 and rehearsed in Phase 7. The
> pre-demo checklist and the viva questions below are already usable.

---

## 1. Pre-demo checklist

Run through this **the evening before**, not ten minutes before.

- [ ] MySQL is running and `bridgetalk` database exists with seeded demo users
- [ ] `ml/models/static_model.keras`, `labels.json` and `metadata.json` are present
- [ ] `frontend/public/models/hand_landmarker.task` is present
- [ ] `.env` is filled in (database URL, JWT secret)
- [ ] Backend starts clean and `/docs` loads
- [ ] Frontend starts clean with **no red errors** in the browser console
- [ ] No other application is holding the webcam (close Zoom, Teams, Photo Booth)
- [ ] Lighting: light on your face and hands, not behind you. A window behind
      you turns your hand into a silhouette and MediaPipe will lose it.
- [ ] Plain background behind your signing hand
- [ ] Laptop plugged in — CPU throttling on battery visibly slows inference
- [ ] **Backup screen recording of a working demo saved locally**, in case the
      college Wi-Fi, the projector or the camera misbehaves on the day

---

## 2. Five-minute demo script

_(Phase 6 / 7 — exact click-by-click sequence, which signs to perform in which
order, and what to say while things load.)_

---

## 3. Anticipated review questions

Answers are filled in with real numbers as the phases complete; the questions
are listed now so they can be prepared for.

**On the design**

1. Why send landmarks instead of raw video?
   _(Answer drafted in [ARCHITECTURE.md](ARCHITECTURE.md) §1 — bandwidth,
   privacy, server cost, and the browser-support trade-off.)_
2. Why MediaPipe rather than training our own CNN on images?
3. Why FastAPI rather than Flask or Django?
4. Why is the backend only a signalling server for the video call?

**On the machine learning**

5. Why an MLP for static signs and an LSTM for dynamic ones?
6. What is your accuracy, and why is it not higher? _(Phase 4.)_
7. Which classes does the model confuse, and why? _(Phase 4 — M/N/S/T in ASL
   fingerspelling are near-identical once reduced to landmarks, because the
   distinguishing feature is thumb position against fingers that are all
   folded.)_
8. Why train only on public datasets?
9. How do you handle prediction flicker? _(Phase 5 — confidence gate, majority
   vote over a rolling window, debounce cooldown, neutral reset.)_
10. Your validation accuracy is high but live performance is worse. Why?
    _(Domain gap: dataset lighting, cameras and framing differ from ours.)_
11. How does this scale beyond fingerspelling?

**On the system**

12. What happens on a slow network?
13. How is this different from Google Meet's captions?
14. Is Interview Mode real proctoring? _(No. It is a deterrent that logs tab
    switches and window blur. It cannot see a second device, a second person in
    the room, or a phone. Say this plainly — claiming otherwise is the fastest
    way to lose credibility in a review.)_

---

## 4. Known weak spots — and how to answer honestly

_(Phase 7. The rule: if the demo misbehaves, name the cause out loud and move
on. "The lighting in here is flattening my hand so the landmarks are noisy" is
a competent answer. Silently repeating the gesture until it works is not.)_
