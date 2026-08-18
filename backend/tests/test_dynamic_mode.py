"""Tests for word-sign (Model B) mode: smoothing, sentence assembly, routing.

The static and dynamic modes share a smoother class but need different
behaviour from it, and the differences are exactly the kind that look fine in
review and fail in a demo: letters that run together into "bookhelp", a
sentence that vanishes when the user changes mode, or a mode string the server
quietly ignores.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.ml.smoothing import PredictionSmoother, SmoothingConfig


def word_smoother(**overrides) -> PredictionSmoother:
    config = SmoothingConfig(
        confidence_threshold=0.7,
        cooldown_ms=1000,
        majority_window=5,
        majority_min=3,
        neutral_reset_frames=4,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return PredictionSmoother(config, word_mode=True)


def emit(smoother: PredictionSmoother, label: str, *, now_ms: float, count: int = 5):
    """Push `count` confident frames of one label and return the last result."""
    result = None
    for _ in range(count):
        result = smoother.push(label, 0.95, now_ms=now_ms)
    return result


# --------------------------------------------------------------------------- #
# Sentence assembly
# --------------------------------------------------------------------------- #


def test_words_are_separated_by_spaces():
    """The difference between "book help" and "bookhelp"."""
    smoother = word_smoother()

    emit(smoother, "book", now_ms=0)
    emit(smoother, "help", now_ms=5_000)

    assert smoother.sentence == "book help"


def test_the_first_word_has_no_leading_space():
    smoother = word_smoother()
    emit(smoother, "again", now_ms=0)
    assert smoother.sentence == "again"


def test_letters_still_concatenate_in_static_mode():
    """The word-mode flag must not change fingerspelling behaviour."""
    smoother = PredictionSmoother(
        SmoothingConfig(confidence_threshold=0.7, cooldown_ms=1000,
                        majority_window=5, majority_min=3, neutral_reset_frames=4)
    )

    emit(smoother, "H", now_ms=0)
    emit(smoother, "I", now_ms=5_000)

    assert smoother.sentence == "HI"


def test_backspace_removes_one_character_not_one_word():
    """Deliberate: a mis-recognised word should be correctable by editing."""
    smoother = word_smoother()
    emit(smoother, "book", now_ms=0)

    assert smoother.backspace() == "boo"


# --------------------------------------------------------------------------- #
# Dynamic tuning
# --------------------------------------------------------------------------- #


def test_dynamic_config_is_more_permissive_than_the_static_one():
    """Reusing the static 0.80 threshold would reject nearly every word sign.

    Twenty word classes trained on roughly twenty clips each produce far less
    peaked softmax output than 28 letter classes trained on thousands.
    """
    static = SmoothingConfig()
    dynamic = SmoothingConfig.for_dynamic()

    assert dynamic.confidence_threshold < static.confidence_threshold
    # A word sign takes one to two seconds, so a 1.5s debounce could fire twice
    # inside a single sign.
    assert dynamic.cooldown_ms > static.cooldown_ms
    # Sliding windows overlap by 29/30 frames, so successive votes are nearly
    # the same evidence counted again. Demanding 7 of 10 adds delay, not proof.
    assert dynamic.majority_window < static.majority_window


def test_dynamic_config_reads_from_settings():
    dynamic = SmoothingConfig.for_dynamic()
    assert dynamic.confidence_threshold == settings.dynamic_confidence_threshold
    assert dynamic.cooldown_ms == settings.dynamic_cooldown_ms
    assert dynamic.majority_min == settings.dynamic_majority_min


# --------------------------------------------------------------------------- #
# Mode switching
# --------------------------------------------------------------------------- #


def test_switching_modes_carries_the_sentence_across():
    """Changing input method must not delete what the user has written."""
    letters = PredictionSmoother()
    words = PredictionSmoother(SmoothingConfig.for_dynamic(), word_mode=True)

    letters._sentence = "HELLO"
    words.adopt(letters.sentence)

    assert words.sentence == "HELLO"


def test_switching_modes_discards_the_vote_history():
    """Votes cast by the letter model mean nothing to the word model.

    Without this, a letter still winning the majority could be emitted by the
    word smoother immediately after the switch — a letter appearing in the
    middle of a sentence of words, with no obvious cause.
    """
    words = PredictionSmoother(
        SmoothingConfig(confidence_threshold=0.7, cooldown_ms=0,
                        majority_window=5, majority_min=3, neutral_reset_frames=4),
        word_mode=True,
    )

    # Build up a near-majority, then switch.
    for _ in range(4):
        words.push("book", 0.95, now_ms=0)
    words.adopt("HELLO")

    # One more frame must not be enough to emit — the window was cleared.
    result = words.push("book", 0.95, now_ms=100)
    assert result.emitted is None


def test_adopt_respects_the_sentence_length_bound():
    words = PredictionSmoother(SmoothingConfig.for_dynamic(), word_mode=True)
    words.adopt("x" * 5_000)
    assert len(words.sentence) <= 500


# --------------------------------------------------------------------------- #
# WebSocket routing
# --------------------------------------------------------------------------- #


def test_socket_rejects_an_unknown_mode(client, registered_user):
    """An unrecognised mode is an error, not a silent fallback to static.

    A client sending "STATIC" or "letters" should be told it is wrong rather
    than quietly given behaviour it did not ask for.
    """
    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        socket.receive_json()  # connected
        socket.send_json(
            {"type": "landmarks", "mode": "interpretive-dance", "timestamp": 0, "hands": []}
        )

        for _ in range(4):
            message = socket.receive_json()
            if message.get("code") == "INVALID_MESSAGE":
                assert "interpretive-dance" in message["message"]
                return
        pytest.fail("An unknown mode was not rejected")


def test_connect_frame_advertises_dynamic_availability(client, registered_user):
    """The UI must be able to hide a mode this deployment cannot serve.

    Model B is a stretch goal, so a backend without one is a normal
    configuration — the toggle should not be offered in that case.
    """
    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        hello = socket.receive_json()

        assert "dynamic_model" in hello
        assert "loaded" in hello["dynamic_model"]
        assert hello["dynamic_model"]["mode"] == "dynamic"
        # And the buffer geometry, so the UI can show real filling progress.
        assert hello["dynamic_config"]["length"] == settings.sequence_length


def test_dynamic_frames_report_model_not_loaded_when_there_is_no_model(
    client, registered_user
):
    """Without a trained Model B, dynamic mode must fail clearly, not silently."""
    from app.ml.predictor import dynamic_predictor

    if dynamic_predictor.is_loaded:
        pytest.skip("A dynamic model is loaded, so this failure path cannot be exercised")

    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        socket.receive_json()  # connected
        socket.send_json(
            {"type": "landmarks", "mode": "dynamic", "timestamp": 0, "hands": []}
        )

        for _ in range(4):
            message = socket.receive_json()
            if message.get("code") == "MODEL_NOT_LOADED":
                return
        pytest.fail("Dynamic mode did not report a missing model")
