"""Turns flickering per-frame predictions into readable text.

THE PROBLEM
-----------
Raw argmax output is unusable as text. At 10 frames per second the model emits
10 letters a second, so holding one handshape for two seconds spells `AAAAAAAA`.
Worse, the frames *between* two deliberate signs contain a hand in transition,
which the model dutifully classifies as some third letter.

Feeding that straight to a subtitle bar produces garbage, and no amount of
extra model accuracy fixes it — the model is answering the question it was
asked ("what letter is this frame?"), which is simply not the question a
conversation needs answered.

THE ALGORITHM (build spec, section 9)
-------------------------------------
Four filters in series, each removing a different kind of noise:

1. **Confidence gate** — discard anything below CONFIDENCE_THRESHOLD (0.80).
   Removes transition frames, where the model is genuinely uncertain.

2. **Majority vote** — a label must win at least MAJORITY_MIN (7) of the last
   MAJORITY_WINDOW (10) frames. Removes single-frame flickers: one stray `S`
   in the middle of a held `A` cannot outvote the `A`s around it.

3. **Debounce** — after a label is emitted, suppress that same label for
   COOLDOWN_MS (1500). This is what stops `AAAAAAAA`. The cooldown is why
   deliberately signing a double letter needs a brief pause between them —
   a real trade-off, and the alternative (no debounce) is far worse.

4. **Neutral reset** — NEUTRAL_RESET_FRAMES (8) consecutive frames with no
   hand clears the debounce, so lowering your hand and raising it again lets
   you repeat a letter immediately without waiting out the cooldown.

Then sentence assembly: accepted letters append to a buffer, `space` inserts a
space, `del` removes the last character.

All of this is deliberately pure Python with no framework or model dependency,
so it can be unit-tested against a synthetic stream of predictions without a
webcam, a WebSocket, or TensorFlow. See backend/tests/test_smoothing.py.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings

# Labels that are commands rather than characters.
SPACE_LABEL = "space"
DELETE_LABEL = "del"
NEUTRAL_LABEL = "nothing"

# Model B can be trained with a class meaning "this window sits between two
# signs". It is a real prediction and a useful one, but it is never a word, so
# it is treated exactly like the no-hand neutral state: it resets, it never
# appends, and the user never sees the string.
TRANSITION_LABEL = "__transition__"

MAX_SENTENCE_LENGTH = 500


@dataclass
class SmoothingConfig:
    """Tunable parameters, defaulting to the values in .env."""

    confidence_threshold: float = field(default_factory=lambda: settings.confidence_threshold)
    cooldown_ms: int = field(default_factory=lambda: settings.cooldown_ms)
    majority_window: int = field(default_factory=lambda: settings.majority_window)
    majority_min: int = field(default_factory=lambda: settings.majority_min)
    neutral_reset_frames: int = field(default_factory=lambda: settings.neutral_reset_frames)

    def __post_init__(self) -> None:
        # A majority threshold larger than the window can never be met, so the
        # system would silently never emit anything. Catch it at construction.
        if self.majority_min > self.majority_window:
            raise ValueError(
                f"majority_min ({self.majority_min}) cannot exceed "
                f"majority_window ({self.majority_window}) — no label could ever win"
            )
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")

    @classmethod
    def for_dynamic(cls) -> "SmoothingConfig":
        """Settings tuned for word signs rather than letters.

        The four numbers differ for reasons explained in config.py, but the one
        worth restating here is the majority window. Dynamic predictions come
        from sliding windows that overlap by 29 frames out of 30, so successive
        votes are nearly the same evidence counted repeatedly. Demanding 7 of 10
        of them would delay every word by most of a second while adding almost
        no independent confirmation.
        """
        return cls(
            confidence_threshold=settings.dynamic_confidence_threshold,
            cooldown_ms=settings.dynamic_cooldown_ms,
            majority_window=settings.dynamic_majority_window,
            majority_min=settings.dynamic_majority_min,
            neutral_reset_frames=settings.dynamic_reset_frames,
        )


@dataclass
class SmoothingResult:
    """What the smoother concluded about one frame."""

    label: str  # this frame's raw prediction, or "nothing"
    confidence: float
    stable: bool  # did a label survive all four filters?
    emitted: Optional[str] = None  # the label actually appended, if any
    sentence: str = ""


class PredictionSmoother:
    """Per-connection smoothing state.

    One instance per WebSocket. State is deliberately not shared between
    connections: two people signing simultaneously must not have their letters
    interleaved into one sentence.
    """

    def __init__(
        self,
        config: Optional[SmoothingConfig] = None,
        word_mode: bool = False,
    ) -> None:
        self.config = config or SmoothingConfig()
        # Letters concatenate ("H" + "I" = "HI"); words must not ("book" +
        # "help" = "bookhelp"). The separator is the only difference between
        # assembling fingerspelling and assembling word signs, so it is a flag
        # rather than a second smoother class.
        self.word_mode = word_mode
        self._recent: deque[Optional[str]] = deque(maxlen=self.config.majority_window)
        self._sentence: str = ""
        self._last_emitted: Optional[str] = None
        self._last_emit_ms: float = 0.0
        self._neutral_streak: int = 0

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def push(
        self,
        label: Optional[str],
        confidence: float,
        now_ms: Optional[float] = None,
    ) -> SmoothingResult:
        """Feed one frame's prediction and get the current state back.

        Args:
            label: the model's argmax label, or None when no hand was detected.
            confidence: softmax probability for that label. Ignored when
                label is None.
            now_ms: current time in milliseconds. Injectable so tests can drive
                the cooldown deterministically instead of calling sleep().
        """
        if now_ms is None:
            now_ms = time.monotonic() * 1000.0

        # --- no hand, or an explicit boundary: filter 4, the neutral reset ---
        # A boundary prediction is the model telling us the window straddles two
        # signs. Treating it as neutral is what stops that window being forced
        # into whichever real word happened to score second.
        if label is None or label in (NEUTRAL_LABEL, TRANSITION_LABEL):
            self._neutral_streak += 1
            self._recent.append(None)

            if self._neutral_streak >= self.config.neutral_reset_frames:
                # Clearing the debounce is what lets "LL" be signed as
                # L, hand down, L — rather than forcing a 1.5s wait.
                self._last_emitted = None

            return SmoothingResult(
                label=NEUTRAL_LABEL, confidence=0.0, stable=False, sentence=self._sentence
            )

        self._neutral_streak = 0

        # --- filter 1: confidence gate --------------------------------------
        # A rejected frame still occupies a slot in the window. That matters:
        # it means a run of uncertain frames dilutes the majority rather than
        # being invisible to it.
        if confidence < self.config.confidence_threshold:
            self._recent.append(None)
            return SmoothingResult(
                label=label, confidence=confidence, stable=False, sentence=self._sentence
            )

        self._recent.append(label)

        # --- filter 2: majority vote ----------------------------------------
        votes = Counter(item for item in self._recent if item is not None)
        if not votes:
            return SmoothingResult(
                label=label, confidence=confidence, stable=False, sentence=self._sentence
            )

        winner, count = votes.most_common(1)[0]
        if count < self.config.majority_min:
            return SmoothingResult(
                label=label, confidence=confidence, stable=False, sentence=self._sentence
            )

        # --- filter 3: debounce ---------------------------------------------
        is_repeat = winner == self._last_emitted
        cooled_down = (now_ms - self._last_emit_ms) >= self.config.cooldown_ms

        if is_repeat and not cooled_down:
            # Stable, but suppressed. Reporting stable=True here is deliberate:
            # the UI should show that recognition is locked on, even though
            # nothing new is being appended.
            return SmoothingResult(
                label=label, confidence=confidence, stable=True, sentence=self._sentence
            )

        # --- accepted: assemble ---------------------------------------------
        self._apply(winner)
        self._last_emitted = winner
        self._last_emit_ms = now_ms

        # Clear the window after emitting, so the next label needs a fresh
        # majority rather than inheriting votes that have already been spent.
        #
        # Without this there is a genuine bug, and it is not obvious: sign A,
        # then move to B. The window still holds mostly A's, so A keeps winning
        # the vote for several frames. It is suppressed by the debounce — until
        # the cooldown expires mid-transition, at which point A is emitted a
        # SECOND time, and the user gets "AAB" for a deliberate "AB". A unit
        # test caught this; a live demo would have looked like random
        # duplication.
        self._recent.clear()

        return SmoothingResult(
            label=label,
            confidence=confidence,
            stable=True,
            emitted=winner,
            sentence=self._sentence,
        )

    # ------------------------------------------------------------------ #
    # Sentence assembly
    # ------------------------------------------------------------------ #

    def _apply(self, label: str) -> None:
        """Append an accepted label to the sentence buffer."""
        if label == SPACE_LABEL:
            # Collapse repeated spaces: a held `space` handshape should not
            # produce a run of blanks in the subtitle.
            if not self._sentence.endswith(" "):
                self._sentence += " "
        elif label == DELETE_LABEL:
            self._sentence = self._sentence[:-1]
        elif self.word_mode:
            # Word signs are whole words, so they need separating. Backspace in
            # this mode still removes one character, which is deliberate: it
            # lets a mis-recognised word be corrected by typing rather than
            # forcing the whole word to be deleted.
            self._sentence += label if not self._sentence else f" {label}"
        else:
            self._sentence += label

        # Bound the buffer. A meeting running for an hour would otherwise grow
        # this string without limit and send it on every single frame.
        if len(self._sentence) > MAX_SENTENCE_LENGTH:
            self._sentence = self._sentence[-MAX_SENTENCE_LENGTH:]

    # ------------------------------------------------------------------ #
    # Controls
    # ------------------------------------------------------------------ #

    @property
    def sentence(self) -> str:
        return self._sentence

    def clear(self) -> None:
        """Reset the sentence, for the UI's Clear button.

        The vote window is cleared too. Without that, letters already in the
        window could immediately re-trigger and partially refill a sentence the
        user just asked to empty.
        """
        self._sentence = ""
        self._last_emitted = None
        self._recent.clear()
        self._neutral_streak = 0

    def backspace(self) -> str:
        """Remove the last character, for the UI's Backspace button."""
        self._sentence = self._sentence[:-1]
        return self._sentence

    def adopt(self, sentence: str) -> None:
        """Take over an existing sentence, discarding any vote history.

        Used when the user switches between fingerspelling and word signs
        mid-conversation. Each mode has its own smoother — they need different
        thresholds and different debounce timing — but the person is writing
        one sentence, and having their text vanish because they changed input
        method would be indefensible.

        The vote window is deliberately NOT carried across. Votes cast by the
        letter model mean nothing to the word model, and letting them survive
        the switch would let a letter be emitted by the wrong smoother.
        """
        self._sentence = sentence[-MAX_SENTENCE_LENGTH:]
        self._recent.clear()
        self._last_emitted = None
        self._neutral_streak = 0
