"""The unified caption protocol — one shape, one broadcast, one row.

WHAT WENT WRONG BEFORE, AND WHAT THESE TESTS PIN
------------------------------------------------
Sign and speech captions travelled two different code paths. The sign path
broadcast `result.sentence`, the whole ACCUMULATED sentence, and wrote one
transcript row per emitted word. A three-word utterance therefore produced
three rows reading "a", "a b", "a b c", and the live caption grew without
bound. The sender was also excluded from its own broadcast, so the two
participants built their caption lists from different code and disagreed.

Each of those is a test below.
"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


@pytest.fixture()
def second_user(client):
    """A second participant, so broadcast fan-out can be observed."""
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Thamizhthilaga S D S",
            "email": "thamizh.captions@example.com",
            "password": "another-password",
            "role": "hearing",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def meeting(client, auth_headers):
    created = client.post(
        "/api/meetings", json={"title": "Caption protocol"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{created['code']}/join", headers=auth_headers)
    return created


# Errors the server emits on CONNECT, about models rather than about anything
# the test sent. The test process does not run the app's lifespan (that would
# connect to real MySQL), so no models are loaded and these always appear.
# An earlier version of this helper returned them as if they were the
# validation error under test, which made three tests pass or fail for the
# wrong reason.
CONNECT_TIME_ERRORS = {"MODEL_NOT_LOADED", "NORMALIZATION_VERSION_MISMATCH"}


def drain_until(socket, message_type, limit=8):
    """Read until a message of `message_type` that is not connect-time noise."""
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") != message_type:
            continue
        if message_type == "error" and message.get("code") in CONNECT_TIME_ERRORS:
            continue
        return message
    return None


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_a_caption_without_a_segment_id_is_rejected(client, registered_user):
    """segment_id is what makes a row idempotent. Without it there is no key."""
    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        socket.receive_json()
        socket.send_json({"type": "caption", "source": "speech", "text": "hello"})
        error = drain_until(socket, "error")

    assert error is not None
    assert error["code"] == "INVALID_MESSAGE"
    assert "segment_id" in error["message"]


def test_an_unknown_source_is_rejected(client, registered_user):
    """Only sign and speech. A third kind nothing can render must not be stored."""
    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        socket.receive_json()
        socket.send_json(
            {"type": "caption", "segment_id": "s1", "source": "video", "text": "x"}
        )
        error = drain_until(socket, "error")

    assert error is not None
    assert error["code"] == "INVALID_MESSAGE"


# --------------------------------------------------------------------------- #
# The sender sees its own caption
# --------------------------------------------------------------------------- #


def test_the_sender_receives_its_own_caption(client, registered_user):
    """The bug this fixes made the two participants disagree.

    The sender used to be EXCLUDED from the broadcast, so it rendered its own
    words from local state and everyone else's from the socket. Two code paths
    assembling the same list is how they drifted apart.
    """
    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/predict/DEMO?token={token}") as socket:
        socket.receive_json()
        socket.send_json(
            {
                "type": "caption",
                "segment_id": "seg-1",
                "source": "speech",
                "text": "hello there",
                "is_final": False,
            }
        )
        caption = drain_until(socket, "caption")

    assert caption is not None, "the sender did not receive its own caption"
    assert caption["segment_id"] == "seg-1"
    assert caption["text"] == "hello there"
    assert caption["is_final"] is False
    assert caption["speaker"]["name"] == "Swarna Rathna A"
    assert caption["source"] == "speech"
    assert "timestamp" in caption


def test_a_caption_reaches_the_other_participant(client, registered_user, second_user, meeting):
    code = meeting["code"]
    guest_token = second_user["access_token"]
    client.post(
        f"/api/meetings/{code}/join",
        headers={"Authorization": f"Bearer {guest_token}"},
    )

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as host:
        host.receive_json()
        with client.websocket_connect(f"/ws/predict/{code}?token={guest_token}") as guest:
            guest.receive_json()

            host.send_json(
                {
                    "type": "caption",
                    "segment_id": "seg-fanout",
                    "source": "sign",
                    "text": "hospital",
                    "is_final": True,
                    "confidence": 0.91,
                }
            )

            received = drain_until(guest, "caption")

    assert received is not None, "the other participant never got the caption"
    assert received["text"] == "hospital"
    assert received["source"] == "sign"
    assert received["confidence"] == 0.91


# --------------------------------------------------------------------------- #
# One row per segment — the repeated-transcript bug
# --------------------------------------------------------------------------- #


def test_interim_captions_are_not_persisted(client, registered_user, auth_headers, meeting):
    """Interim text is revised word by word. Storing it fills the transcript
    with fragments of sentences nobody finished saying."""
    code, meeting_id = meeting["code"], meeting["id"]

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as socket:
        socket.receive_json()
        for text in ("hello", "hello there", "hello there friend"):
            socket.send_json(
                {
                    "type": "caption",
                    "segment_id": "seg-interim",
                    "source": "speech",
                    "text": text,
                    "is_final": False,
                }
            )
            drain_until(socket, "caption")

    rows = client.get(f"/api/transcripts/{meeting_id}", headers=auth_headers).json()
    assert rows == [], "interim captions were written to the transcript"


def test_one_row_per_segment_no_matter_how_many_interims(
    client, registered_user, auth_headers, meeting
):
    """The exact bug observed in testing, as a test.

    Three interims then a final must produce ONE row holding only the final
    text — not three rows holding "a", "a b", "a b c".
    """
    code, meeting_id = meeting["code"], meeting["id"]

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as socket:
        socket.receive_json()
        for text, final in (
            ("hello", False),
            ("hello there", False),
            ("hello there friend", True),
        ):
            socket.send_json(
                {
                    "type": "caption",
                    "segment_id": "seg-once",
                    "source": "speech",
                    "text": text,
                    "is_final": final,
                }
            )
            drain_until(socket, "caption")

    rows = client.get(f"/api/transcripts/{meeting_id}", headers=auth_headers).json()
    assert len(rows) == 1, f"expected exactly one row, got {[r['content'] for r in rows]}"
    assert rows[0]["content"] == "hello there friend"
    assert rows[0]["segment_id"] == "seg-once"


def test_replaying_a_final_event_does_not_duplicate_the_row(
    client, registered_user, auth_headers, meeting
):
    """A retry after a dropped acknowledgement, or a reconnect replaying its
    tail, must collide rather than insert a second line."""
    code, meeting_id = meeting["code"], meeting["id"]

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as socket:
        socket.receive_json()
        for _ in range(3):
            socket.send_json(
                {
                    "type": "caption",
                    "segment_id": "seg-retry",
                    "source": "sign",
                    "text": "market",
                    "is_final": True,
                }
            )
            drain_until(socket, "caption")

    rows = client.get(f"/api/transcripts/{meeting_id}", headers=auth_headers).json()
    assert len(rows) == 1, f"the same segment was stored {len(rows)} times"


def test_separate_segments_each_get_their_own_row(
    client, registered_user, auth_headers, meeting
):
    """And the text is only that segment's — never the accumulated history."""
    code, meeting_id = meeting["code"], meeting["id"]

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as socket:
        socket.receive_json()
        for index, word in enumerate(("hospital", "market", "india")):
            socket.send_json(
                {
                    "type": "caption",
                    "segment_id": f"seg-{index}",
                    "source": "sign",
                    "text": word,
                    "is_final": True,
                }
            )
            drain_until(socket, "caption")

    rows = client.get(f"/api/transcripts/{meeting_id}", headers=auth_headers).json()
    contents = [r["content"] for r in rows]
    assert contents == ["hospital", "market", "india"], contents
    # The decisive assertion: no row contains more than its own segment's text.
    assert not any(" " in c for c in contents), (
        f"a row carries accumulated history: {contents}"
    )


def test_an_empty_final_segment_is_not_stored(client, registered_user, auth_headers, meeting):
    """A recogniser can close a segment it never got words for."""
    code, meeting_id = meeting["code"], meeting["id"]

    with client.websocket_connect(f"/ws/predict/{code}?token={registered_user['access_token']}") as socket:
        socket.receive_json()
        socket.send_json(
            {
                "type": "caption",
                "segment_id": "seg-empty",
                "source": "speech",
                "text": "   ",
                "is_final": True,
            }
        )
        drain_until(socket, "caption")

    rows = client.get(f"/api/transcripts/{meeting_id}", headers=auth_headers).json()
    assert rows == []
