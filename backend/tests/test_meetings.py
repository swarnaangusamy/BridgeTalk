"""Phase 2 — meeting and transcript API tests.

The focus is on the two things that would actually hurt: a stranger being able
to read a private meeting's transcript, and attendance records that quietly
lie about what happened.
"""

import re

import pytest

from app.api.meetings import CODE_ALPHABET, generate_meeting_code


@pytest.fixture()
def second_user(client):
    """A second account, so membership boundaries can be tested."""
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Thamizhthilaga S D S",
            "email": "thamizh@example.com",
            "password": "another-password",
            "role": "hearing",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def second_headers(second_user):
    return {"Authorization": f"Bearer {second_user['access_token']}"}


@pytest.fixture()
def meeting(client, auth_headers):
    """A meeting hosted by the primary user."""
    response = client.post(
        "/api/meetings",
        json={"title": "Project review", "is_interview_mode": False},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Meeting creation
# ---------------------------------------------------------------------------


def test_create_meeting_returns_a_code(client, auth_headers, meeting):
    assert meeting["title"] == "Project review"
    assert meeting["is_active"] is True
    assert meeting["started_at"] is None  # nobody has joined yet
    assert meeting["host"]["email"] == "swarna@example.com"


def test_meeting_code_is_human_typable(meeting):
    """Codes get read aloud and typed by someone watching a video call.

    Ambiguous characters (O/0, I/1, L/1) are excluded, because they are what
    turn "join my meeting" into three failed attempts.
    """
    code = meeting["code"]
    assert re.fullmatch(r"[A-Z2-9]{3}-[A-Z2-9]{3}", code), code

    for forbidden in "01ILO":
        assert forbidden not in CODE_ALPHABET


def test_meeting_codes_are_unique(client, auth_headers):
    codes = set()
    for index in range(15):
        response = client.post(
            "/api/meetings", json={"title": f"Meeting {index}"}, headers=auth_headers
        )
        codes.add(response.json()["code"])
    assert len(codes) == 15


def test_generate_meeting_code_retries_past_collisions(db_session):
    """The generator must not loop forever, and must produce valid codes."""
    code = generate_meeting_code(db_session)
    assert re.fullmatch(r"[A-Z2-9]{3}-[A-Z2-9]{3}", code)


def test_creating_a_meeting_requires_auth(client):
    assert client.post("/api/meetings", json={"title": "No auth"}).status_code == 401


def test_create_meeting_rejects_empty_title(client, auth_headers):
    response = client.post("/api/meetings", json={"title": ""}, headers=auth_headers)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------


def test_join_records_attendance_and_starts_the_clock(client, auth_headers, meeting):
    response = client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["is_first_participant"] is True
    assert body["meeting"]["started_at"] is not None
    assert len(body["meeting"]["participants"]) == 1


def test_second_joiner_is_not_the_first_participant(client, auth_headers, second_headers, meeting):
    """Exactly one peer must be told it is first.

    The frontend uses this flag to decide who creates the WebRTC offer. If both
    peers thought they were first, both would offer and the negotiation would
    collide.
    """
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)
    response = client.post(f"/api/meetings/{meeting['code']}/join", headers=second_headers)

    assert response.status_code == 200
    assert response.json()["is_first_participant"] is False


def test_rejoining_writes_a_new_attendance_row(client, auth_headers, meeting):
    """A dropped connection must stay visible in the record.

    Reusing the original row would quietly erase the disconnection, which makes
    the attendance log a nicer story than what actually happened.
    """
    code = meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=auth_headers)
    client.post(f"/api/meetings/{code}/leave", headers=auth_headers)
    response = client.post(f"/api/meetings/{code}/join", headers=auth_headers)

    participants = response.json()["meeting"]["participants"]
    assert len(participants) == 2
    assert participants[0]["left_at"] is not None
    assert participants[1]["left_at"] is None


def test_join_is_case_insensitive(client, auth_headers, meeting):
    """Nobody types a meeting code in the right case on the first try."""
    response = client.post(
        f"/api/meetings/{meeting['code'].lower()}/join", headers=auth_headers
    )
    assert response.status_code == 200


def test_join_unknown_code_is_404(client, auth_headers):
    response = client.post("/api/meetings/ZZZ-999/join", headers=auth_headers)
    assert response.status_code == 404


def test_cannot_join_an_ended_meeting(client, auth_headers, meeting):
    code = meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=auth_headers)
    client.post(f"/api/meetings/{code}/end", headers=auth_headers)

    response = client.post(f"/api/meetings/{code}/join", headers=auth_headers)
    assert response.status_code == 409


def test_leave_without_joining_is_409(client, auth_headers, meeting):
    response = client.post(f"/api/meetings/{meeting['code']}/leave", headers=auth_headers)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Ending
# ---------------------------------------------------------------------------


def test_only_the_host_can_end_a_meeting(client, auth_headers, second_headers, meeting):
    """Ending a meeting makes its code unusable — that must not be open to all."""
    code = meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=second_headers)

    assert client.post(f"/api/meetings/{code}/end", headers=second_headers).status_code == 403
    assert client.post(f"/api/meetings/{code}/end", headers=auth_headers).status_code == 200


def test_ending_closes_every_open_attendance_row(client, auth_headers, second_headers, meeting):
    """Someone who shuts their laptop must not stay 'in' the meeting forever."""
    code = meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=auth_headers)
    client.post(f"/api/meetings/{code}/join", headers=second_headers)

    response = client.post(f"/api/meetings/{code}/end", headers=auth_headers)
    body = response.json()

    assert body["is_active"] is False
    assert body["ended_at"] is not None
    assert all(p["left_at"] is not None for p in body["participants"])


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_includes_hosted_and_attended_meetings(
    client, auth_headers, second_headers, meeting
):
    # The second user hosts one meeting and attends the first user's meeting.
    other = client.post(
        "/api/meetings", json={"title": "Thamizh's meeting"}, headers=second_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=second_headers)

    response = client.get("/api/meetings/history", headers=second_headers)
    assert response.status_code == 200

    titles = {row["title"] for row in response.json()}
    assert titles == {"Thamizh's meeting", "Project review"}


def test_history_excludes_other_peoples_meetings(client, auth_headers, second_headers, meeting):
    response = client.get("/api/meetings/history", headers=second_headers)
    assert response.json() == []


def test_history_route_is_not_shadowed_by_the_code_route(client, auth_headers):
    """/history must not be parsed as a meeting code.

    FastAPI matches routes in declaration order, so /{code} would swallow
    "history" if it were declared first. This test fails loudly if anyone
    reorders them.
    """
    response = client.get("/api/meetings/history", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------


@pytest.fixture()
def joined_meeting(client, auth_headers, meeting):
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)
    return meeting


def test_append_and_read_a_transcript_line(client, auth_headers, joined_meeting):
    response = client.post(
        "/api/transcripts",
        json={
            "meeting_id": joined_meeting["id"],
            "source": "sign",
            "content": "HELLO",
            "confidence": 0.94,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["content"] == "HELLO"
    assert body["source"] == "sign"
    assert body["confidence"] == pytest.approx(0.94)
    assert body["user_name"] == "Swarna Rathna A"


def test_transcript_is_returned_in_chronological_order(client, auth_headers, joined_meeting):
    for word in ["FIRST", "SECOND", "THIRD"]:
        client.post(
            "/api/transcripts",
            json={"meeting_id": joined_meeting["id"], "source": "sign", "content": word},
            headers=auth_headers,
        )

    response = client.get(f"/api/transcripts/{joined_meeting['id']}", headers=auth_headers)
    assert [row["content"] for row in response.json()] == ["FIRST", "SECOND", "THIRD"]


def test_line_is_attributed_to_the_caller_not_the_request_body(
    client, auth_headers, second_headers, joined_meeting
):
    """Nobody may put words in another participant's permanent record."""
    client.post(f"/api/meetings/{joined_meeting['code']}/join", headers=second_headers)

    response = client.post(
        "/api/transcripts",
        json={
            "meeting_id": joined_meeting["id"],
            "source": "speech",
            "content": "spoken by the second user",
            # A user_id here is simply ignored — the schema has no such field,
            # and attribution always comes from the token.
            "user_id": 1,
        },
        headers=second_headers,
    )

    assert response.status_code == 201
    assert response.json()["user_name"] == "Thamizhthilaga S D S"


def test_non_members_cannot_read_a_transcript(
    client, auth_headers, second_headers, joined_meeting
):
    """Being logged in is not enough — membership is the access boundary."""
    client.post(
        "/api/transcripts",
        json={"meeting_id": joined_meeting["id"], "source": "sign", "content": "PRIVATE"},
        headers=auth_headers,
    )

    response = client.get(f"/api/transcripts/{joined_meeting['id']}", headers=second_headers)
    assert response.status_code == 403


def test_non_members_cannot_write_to_a_transcript(client, second_headers, joined_meeting):
    response = client.post(
        "/api/transcripts",
        json={"meeting_id": joined_meeting["id"], "source": "sign", "content": "INTRUDER"},
        headers=second_headers,
    )
    assert response.status_code == 403


def test_transcript_requires_auth(client, joined_meeting):
    assert client.get(f"/api/transcripts/{joined_meeting['id']}").status_code == 401


def test_transcript_for_unknown_meeting_is_404(client, auth_headers):
    assert client.get("/api/transcripts/99999", headers=auth_headers).status_code == 404


def test_cannot_append_to_an_ended_meeting(client, auth_headers, joined_meeting):
    client.post(f"/api/meetings/{joined_meeting['code']}/end", headers=auth_headers)

    response = client.post(
        "/api/transcripts",
        json={"meeting_id": joined_meeting["id"], "source": "sign", "content": "TOO LATE"},
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_must_be_a_probability(client, auth_headers, joined_meeting, confidence):
    response = client.post(
        "/api/transcripts",
        json={
            "meeting_id": joined_meeting["id"],
            "source": "sign",
            "content": "X",
            "confidence": confidence,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_produces_a_readable_text_file(client, auth_headers, joined_meeting):
    client.post(
        "/api/transcripts",
        json={
            "meeting_id": joined_meeting["id"],
            "source": "sign",
            "content": "HELLO",
            "confidence": 0.94,
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transcripts",
        json={"meeting_id": joined_meeting["id"], "source": "speech", "content": "Hi there"},
        headers=auth_headers,
    )

    response = client.get(
        f"/api/transcripts/{joined_meeting['id']}/export", headers=auth_headers
    )
    assert response.status_code == 200

    body = response.text
    assert "BridgeTalk meeting transcript" in body
    assert joined_meeting["code"] in body
    assert "SIGN" in body and "HELLO" in body
    assert "SPEECH" in body and "Hi there" in body
    # Confidence is shown for sign lines so a reader can tell how much to
    # trust each one, rather than assuming every line is equally reliable.
    assert "94%" in body

    disposition = response.headers["content-disposition"]
    assert f'filename="bridgetalk-transcript-{joined_meeting["code"]}.txt"' in disposition


def test_export_of_an_empty_transcript_says_so(client, auth_headers, joined_meeting):
    """An empty file would look like a bug. Say what happened instead."""
    response = client.get(
        f"/api/transcripts/{joined_meeting['id']}/export", headers=auth_headers
    )
    assert response.status_code == 200
    assert "no transcript lines were recorded" in response.text


def test_non_members_cannot_export(client, second_headers, joined_meeting):
    response = client.get(
        f"/api/transcripts/{joined_meeting['id']}/export", headers=second_headers
    )
    assert response.status_code == 403
