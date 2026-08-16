"""Phase 5 — smoothing algorithm tests.

Every test drives a synthetic stream of (label, confidence) pairs, so the whole
algorithm is verified without a webcam, a model, or a WebSocket. Time is
injected rather than slept on, which keeps the cooldown tests instant and
deterministic.

The scenarios are written to mirror what actually happens in front of a camera:
a held handshape, a single-frame flicker, a transition between two letters, a
hand lowered and raised again.
"""

import pytest

from app.ml.smoothing import (
    NEUTRAL_LABEL,
    PredictionSmoother,
    SmoothingConfig,
)


@pytest.fixture()
def config():
    """The defaults from the build spec, stated explicitly for readability."""
    return SmoothingConfig(
        confidence_threshold=0.80,
        cooldown_ms=1500,
        majority_window=10,
        majority_min=7,
        neutral_reset_frames=8,
    )


@pytest.fixture()
def smoother(config):
    return PredictionSmoother(config)


def feed(smoother, label, confidence, count, start_ms=0.0, step_ms=100.0):
    """Push `count` identical frames, 100ms apart (i.e. 10 FPS)."""
    result = None
    for index in range(count):
        result = smoother.push(label, confidence, now_ms=start_ms + index * step_ms)
    return result


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


def test_majority_min_above_window_is_rejected():
    """A threshold larger than the window means nothing could ever be emitted.

    Silently never producing output is the worst possible failure here, so it
    is caught at construction rather than at 2am during a demo.
    """
    with pytest.raises(ValueError, match="cannot exceed"):
        SmoothingConfig(majority_window=5, majority_min=9)


@pytest.mark.parametrize("threshold", [-0.1, 1.5])
def test_confidence_threshold_must_be_a_probability(threshold):
    with pytest.raises(ValueError):
        SmoothingConfig(confidence_threshold=threshold)


# ---------------------------------------------------------------------------
# Filter 1 — confidence gate
# ---------------------------------------------------------------------------


def test_low_confidence_never_reaches_the_sentence(smoother):
    """Transition frames between two signs are exactly this case."""
    result = feed(smoother, "A", confidence=0.50, count=20)

    assert result.stable is False
    assert result.emitted is None
    assert result.sentence == ""


def test_confidence_exactly_at_the_threshold_is_accepted(smoother):
    """The gate is >=, not >. Pinned so nobody 'tidies' it into a bug.

    Asserted on the sentence rather than the last frame's `emitted`: the letter
    is emitted partway through the run, and later frames are correctly
    suppressed by the debounce.
    """
    feed(smoother, "A", confidence=0.80, count=10)
    assert smoother.sentence == "A"


def test_rejected_frames_still_dilute_the_vote(smoother):
    """A rejected frame occupies a window slot rather than being invisible.

    Six good frames plus four uncertain ones must not reach the 7-vote bar,
    even though the six are unanimous.
    """
    for index in range(6):
        smoother.push("A", 0.95, now_ms=index * 100)
    for index in range(6, 10):
        smoother.push("A", 0.40, now_ms=index * 100)

    assert smoother.sentence == ""


# ---------------------------------------------------------------------------
# Filter 2 — majority vote
# ---------------------------------------------------------------------------


def test_six_frames_is_not_enough(smoother):
    result = feed(smoother, "B", confidence=0.99, count=6)
    assert result.emitted is None
    assert result.sentence == ""


def test_seven_frames_is_enough(smoother):
    result = feed(smoother, "B", confidence=0.99, count=7)
    assert result.emitted == "B"
    assert result.sentence == "B"


def test_a_single_flicker_cannot_outvote_a_held_sign(smoother):
    """One stray frame in the middle of a held letter must be ignored.

    This is the single most common real-world noise pattern, and the reason
    the majority vote exists at all.
    """
    for index in range(5):
        smoother.push("A", 0.95, now_ms=index * 100)
    smoother.push("S", 0.93, now_ms=500)  # the flicker
    for index in range(6, 12):
        smoother.push("A", 0.95, now_ms=index * 100)

    assert smoother.sentence == "A"
    assert "S" not in smoother.sentence


def test_a_genuine_change_of_letter_does_get_through(smoother):
    """The vote must not be so sticky that real letters are lost."""
    feed(smoother, "H", 0.95, count=10, start_ms=0)
    assert smoother.sentence == "H"

    feed(smoother, "I", 0.95, count=10, start_ms=1000)
    assert smoother.sentence == "HI"


# ---------------------------------------------------------------------------
# Filter 3 — debounce
# ---------------------------------------------------------------------------


def test_holding_a_handshape_does_not_spell_aaaaaa(smoother):
    """The headline bug this whole module exists to prevent.

    Three seconds of a held 'A' at 10 FPS is 30 frames. Without debouncing
    that is 24 letters.
    """
    result = feed(smoother, "A", 0.99, count=30, start_ms=0, step_ms=100)

    # 3 seconds at a 1500ms cooldown permits at most 3 emissions.
    assert smoother.sentence in ("A", "AA", "AAA")
    assert len(smoother.sentence) <= 3
    # Still locked on, even while suppressed — the UI should show that.
    assert result.stable is True


def test_the_same_letter_is_allowed_again_after_the_cooldown(smoother):
    """Deliberately signing a double letter must remain possible."""
    feed(smoother, "L", 0.99, count=10, start_ms=0)
    assert smoother.sentence == "L"

    # Well past the 1500ms cooldown.
    feed(smoother, "L", 0.99, count=10, start_ms=3000)
    assert smoother.sentence == "LL"


def test_a_letter_is_not_emitted_twice_across_a_transition(smoother):
    """Regression: signing A then B must give 'AB', never 'AAB'.

    The bug this pins down was subtle and was found by these tests rather than
    by watching the demo. After A is emitted, the vote window still holds
    mostly A's. As B's frames arrive, A keeps winning the vote — harmlessly,
    because the debounce suppresses it. But if the 1500ms cooldown expires
    while those stale A votes are still in the window, A gets emitted a SECOND
    time, mid-transition.

    Live, that would have looked like random letter duplication with no
    reproducible trigger. The fix is to clear the window on every emission, so
    votes cannot be spent twice.
    """
    feed(smoother, "A", 0.99, count=10, start_ms=0)  # emits A at 600ms
    assert smoother.sentence == "A"

    # B arrives starting at 1400ms, so the cooldown (expiring at 2100ms) lapses
    # partway through the transition — exactly the window where A could
    # re-emit.
    feed(smoother, "B", 0.99, count=10, start_ms=1400)

    assert smoother.sentence == "AB", "stale votes re-emitted the previous letter"


def test_a_different_letter_is_not_debounced(smoother):
    """The cooldown applies per-label, not globally.

    A global cooldown would throttle normal fingerspelling to under one letter
    per 1.5 seconds, which is unusably slow.
    """
    feed(smoother, "C", 0.99, count=10, start_ms=0)
    feed(smoother, "A", 0.99, count=10, start_ms=1000)  # inside the cooldown
    feed(smoother, "T", 0.99, count=10, start_ms=2000)

    assert smoother.sentence == "CAT"


# ---------------------------------------------------------------------------
# Filter 4 — neutral reset
# ---------------------------------------------------------------------------


def test_lowering_the_hand_clears_the_debounce(smoother):
    """Sign L, drop the hand, sign L again — that must give 'LL' immediately.

    Without the neutral reset the user would have to wait out the full
    cooldown, which feels broken rather than deliberate.
    """
    feed(smoother, "L", 0.99, count=10, start_ms=0)
    assert smoother.sentence == "L"

    # Hand lowered: 8 frames of nothing.
    for index in range(8):
        smoother.push(None, 0.0, now_ms=1000 + index * 100)

    # Raised again, still inside the 1500ms cooldown window.
    feed(smoother, "L", 0.99, count=10, start_ms=1800)
    assert smoother.sentence == "LL"


def test_a_brief_gap_does_not_reset(smoother):
    """Momentary tracking loss must not be treated as a deliberate pause.

    The second run is kept inside the 1500ms cooldown window on purpose. Hold
    the same letter for longer than the cooldown and it *should* repeat — that
    is the documented behaviour, tested separately above.
    """
    feed(smoother, "L", 0.99, count=10, start_ms=0)  # emits at 600ms

    for index in range(3):  # below the 8-frame reset threshold
        smoother.push(None, 0.0, now_ms=1000 + index * 100)

    # 7 frames spanning 1300-1900ms: enough votes, but still within cooldown.
    feed(smoother, "L", 0.99, count=7, start_ms=1300)
    assert smoother.sentence == "L"


def test_no_hand_reports_the_neutral_label(smoother):
    result = smoother.push(None, 0.0)
    assert result.label == NEUTRAL_LABEL
    assert result.stable is False


def test_explicit_nothing_label_is_treated_as_no_hand(smoother):
    """Defensive: 'nothing' is not a trained class, but must be handled."""
    result = smoother.push(NEUTRAL_LABEL, 0.99)
    assert result.label == NEUTRAL_LABEL
    assert result.stable is False


# ---------------------------------------------------------------------------
# Sentence assembly
# ---------------------------------------------------------------------------


def test_space_inserts_a_word_break(smoother):
    feed(smoother, "H", 0.99, count=10, start_ms=0)
    feed(smoother, "I", 0.99, count=10, start_ms=1000)
    feed(smoother, "space", 0.99, count=10, start_ms=2000)
    feed(smoother, "U", 0.99, count=10, start_ms=4000)

    assert smoother.sentence == "HI U"


def test_repeated_spaces_are_collapsed(smoother):
    """A held 'space' handshape must not produce a run of blanks."""
    feed(smoother, "A", 0.99, count=10, start_ms=0)
    feed(smoother, "space", 0.99, count=10, start_ms=1000)
    feed(smoother, "space", 0.99, count=10, start_ms=4000)

    assert smoother.sentence == "A "


def test_del_removes_the_last_character(smoother):
    feed(smoother, "A", 0.99, count=10, start_ms=0)
    feed(smoother, "B", 0.99, count=10, start_ms=1000)
    assert smoother.sentence == "AB"

    feed(smoother, "del", 0.99, count=10, start_ms=2000)
    assert smoother.sentence == "A"


def test_del_on_an_empty_sentence_is_harmless(smoother):
    feed(smoother, "del", 0.99, count=10)
    assert smoother.sentence == ""


def test_a_full_word_is_spelled_correctly(smoother):
    """End-to-end: the stream a person signing 'HELLO' would produce.

    Each letter is held for 10 frames with 3 uncertain transition frames
    between, which is what the real pipeline sees.
    """
    now = 0.0
    for letter in "HELLO":
        for _ in range(10):
            smoother.push(letter, 0.95, now_ms=now)
            now += 100
        for _ in range(3):  # transition — rejected by the confidence gate
            smoother.push(letter, 0.40, now_ms=now)
            now += 100

    assert smoother.sentence == "HELLO"


def test_the_sentence_buffer_is_bounded(smoother):
    """An hour-long meeting must not grow this string without limit.

    It is sent on every frame, so an unbounded buffer is a bandwidth problem
    as well as a memory one.
    """
    now = 0.0
    for index in range(700):
        letter = "AB"[index % 2]  # alternate so the debounce never blocks
        for _ in range(10):
            smoother.push(letter, 0.99, now_ms=now)
            now += 100

    assert len(smoother.sentence) <= 500


# ---------------------------------------------------------------------------
# UI controls
# ---------------------------------------------------------------------------


def test_clear_empties_the_sentence(smoother):
    feed(smoother, "A", 0.99, count=10)
    smoother.clear()
    assert smoother.sentence == ""


def test_clear_also_empties_the_vote_window(smoother):
    """Otherwise letters still in the window immediately refill the sentence
    the user just asked to empty."""
    feed(smoother, "A", 0.99, count=10, start_ms=0)
    smoother.clear()

    # A few more frames must not instantly re-reach the 7-vote threshold.
    for index in range(3):
        smoother.push("A", 0.99, now_ms=2000 + index * 100)

    assert smoother.sentence == ""


def test_backspace_removes_one_character(smoother):
    feed(smoother, "A", 0.99, count=10, start_ms=0)
    feed(smoother, "B", 0.99, count=10, start_ms=2000)
    assert smoother.backspace() == "A"


def test_smoothers_do_not_share_state():
    """Two people signing at once must not interleave into one sentence."""
    first = PredictionSmoother()
    second = PredictionSmoother()

    feed(first, "A", 0.99, count=10)
    feed(second, "Z", 0.99, count=10)

    assert first.sentence == "A"
    assert second.sentence == "Z"
