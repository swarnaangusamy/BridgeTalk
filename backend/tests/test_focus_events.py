"""Phase 7 — Interview Mode focus event tests.

Interview Mode is the feature most likely to be over-claimed in a review, so
the tests pin down exactly what it does: it records tab-focus transitions for
participants of a meeting that opted into it, readable only by the host.
"""

import pytest


@pytest.fixture()
def second_user(client):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Thamizhthilaga S D S",
            "email": "thamizh@example.com",
            "password": "another-password",
            "role": "hearing",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture()
def second_headers(second_user):
    return {"Authorization": f"Bearer {second_user['access_token']}"}


@pytest.fixture()
def interview_meeting(client, auth_headers):
    response = client.post(
        "/api/meetings",
        json={"title": "Technical interview", "is_interview_mode": True},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture()
def normal_meeting(client, auth_headers):
    response = client.post(
        "/api/meetings",
        json={"title": "Ordinary chat", "is_interview_mode": False},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ["blur", "hidden", "return"])
def test_each_event_type_can_be_logged(client, auth_headers, interview_meeting, event_type):
    """These three are everything the browser will tell us — no more."""
    response = client.post(
        f"/api/meetings/{interview_meeting['code']}/focus-events",
        json={"event_type": event_type},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["event_type"] == event_type


def test_invalid_event_type_is_rejected(client, auth_headers, interview_meeting):
    response = client.post(
        f"/api/meetings/{interview_meeting['code']}/focus-events",
        json={"event_type": "screenshotted-the-answers"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_logging_requires_interview_mode(client, auth_headers, normal_meeting):
    """A meeting that did not opt in must not silently collect focus data.

    Accepting the write would mean attention logging could be switched on
    without the participants ever being told.
    """
    response = client.post(
        f"/api/meetings/{normal_meeting['code']}/focus-events",
        json={"event_type": "blur"},
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_non_participants_cannot_log_events(client, second_headers, interview_meeting):
    response = client.post(
        f"/api/meetings/{interview_meeting['code']}/focus-events",
        json={"event_type": "blur"},
        headers=second_headers,
    )
    assert response.status_code == 403


def test_logging_requires_auth(client, interview_meeting):
    response = client.post(
        f"/api/meetings/{interview_meeting['code']}/focus-events",
        json={"event_type": "blur"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_host_can_read_the_summary(client, auth_headers, interview_meeting):
    code = interview_meeting["code"]
    for event_type in ["blur", "return", "hidden", "return"]:
        client.post(
            f"/api/meetings/{code}/focus-events",
            json={"event_type": event_type},
            headers=auth_headers,
        )

    response = client.get(f"/api/meetings/{code}/focus-events", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["total_events"] == 4
    # A `return` is the recovery, not another offence. Counting all four would
    # report twice as many incidents as actually happened.
    assert body["away_count"] == 2
    assert len(body["events"]) == 4
    assert body["events"][0]["user_name"] == "Swarna Rathna A"


def test_events_are_returned_in_chronological_order(client, auth_headers, interview_meeting):
    code = interview_meeting["code"]
    for event_type in ["blur", "return", "hidden"]:
        client.post(
            f"/api/meetings/{code}/focus-events",
            json={"event_type": event_type},
            headers=auth_headers,
        )

    events = client.get(f"/api/meetings/{code}/focus-events", headers=auth_headers).json()["events"]
    assert [event["event_type"] for event in events] == ["blur", "return", "hidden"]


def test_participants_cannot_read_each_others_focus_events(
    client, auth_headers, second_headers, interview_meeting
):
    """Only the host may read this.

    It is a record *about* the participants; letting everyone read everyone
    else's attention log would be participants surveilling each other rather
    than a tool for whoever is running the interview.
    """
    code = interview_meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=second_headers)

    response = client.get(f"/api/meetings/{code}/focus-events", headers=second_headers)
    assert response.status_code == 403


def test_summary_is_empty_for_a_meeting_with_no_events(client, auth_headers, interview_meeting):
    response = client.get(
        f"/api/meetings/{interview_meeting['code']}/focus-events", headers=auth_headers
    )
    assert response.status_code == 200

    body = response.json()
    assert body["total_events"] == 0
    assert body["away_count"] == 0
    assert body["events"] == []


def test_a_joined_participant_can_log_their_own_events(
    client, auth_headers, second_headers, interview_meeting
):
    code = interview_meeting["code"]
    client.post(f"/api/meetings/{code}/join", headers=second_headers)

    response = client.post(
        f"/api/meetings/{code}/focus-events",
        json={"event_type": "hidden"},
        headers=second_headers,
    )
    assert response.status_code == 201
    assert response.json()["user_name"] == "Thamizhthilaga S D S"

    summary = client.get(f"/api/meetings/{code}/focus-events", headers=auth_headers).json()
    assert summary["events"][0]["user_name"] == "Thamizhthilaga S D S"
