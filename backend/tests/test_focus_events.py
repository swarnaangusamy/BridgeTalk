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


# --------------------------------------------------------------------------- #
# Interview Mode toggle (host only)
# --------------------------------------------------------------------------- #
#
# The mode can now be switched on DURING a meeting rather than only chosen at
# creation. Two things must hold: only the host can do it, and the state lives
# on the meeting row so a participant who reloads cannot escape it.


def test_host_can_switch_interview_mode_on_and_off(client, auth_headers):
    meeting = client.post(
        "/api/meetings", json={"title": "Toggle"}, headers=auth_headers
    ).json()
    assert meeting["is_interview_mode"] is False

    on = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert on.status_code == 200, on.text
    assert on.json()["is_interview_mode"] is True

    off = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert off.status_code == 200
    assert off.json()["is_interview_mode"] is False


def test_a_participant_cannot_switch_interview_mode(client, auth_headers, second_user):
    """This changes what the OTHER participants are subject to.

    Same reasoning as only the host being able to end a meeting: a participant
    turning it on for everyone, or off for themselves, would make the feature
    meaningless.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Not yours"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)

    guest = {"Authorization": f"Bearer {second_user['access_token']}"}
    client.post(f"/api/meetings/{meeting['code']}/join", headers=guest)

    response = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": True},
        headers=guest,
    )
    assert response.status_code == 403


def test_switching_on_stamps_a_start_time(client, auth_headers):
    """Needed to tell a violation from an ordinary earlier tab switch.

    Focus events recorded before the mode was active are not offences, and
    without this timestamp there is no way to separate them.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Stamped"}, headers=auth_headers
    ).json()

    body = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": True},
        headers=auth_headers,
    ).json()
    assert body.get("interview_mode_started_at"), "switch-on did not record when"

    cleared = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": False},
        headers=auth_headers,
    ).json()
    # Cleared on switch-off so a later switch-on starts a fresh window rather
    # than inheriting the first one.
    assert cleared.get("interview_mode_started_at") is None


def test_cannot_toggle_a_meeting_that_has_ended(client, auth_headers):
    meeting = client.post(
        "/api/meetings", json={"title": "Over"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/end", headers=auth_headers)

    response = client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Duration and the per-participant rollup
# --------------------------------------------------------------------------- #


def test_duration_away_is_stored_and_rolled_up(client, auth_headers):
    """A 300 ms notification steal and a two-minute absence are different.

    The host's log is only useful if it can tell them apart, which is why the
    duration is persisted rather than just the fact of the event.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Durations", "is_interview_mode": True},
        headers=auth_headers,
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)
    client.patch(
        f"/api/meetings/{meeting['code']}/interview-mode",
        json={"enabled": True}, headers=auth_headers,
    )

    client.post(f"/api/meetings/{meeting['code']}/focus-events",
                json={"event_type": "hidden"}, headers=auth_headers)
    client.post(f"/api/meetings/{meeting['code']}/focus-events",
                json={"event_type": "return", "duration_away_ms": 42_000},
                headers=auth_headers)
    client.post(f"/api/meetings/{meeting['code']}/focus-events",
                json={"event_type": "hidden"}, headers=auth_headers)
    client.post(f"/api/meetings/{meeting['code']}/focus-events",
                json={"event_type": "return", "duration_away_ms": 8_000},
                headers=auth_headers)

    summary = client.get(
        f"/api/meetings/{meeting['code']}/focus-events", headers=auth_headers
    ).json()

    assert summary["away_count"] == 2
    rollup = summary["by_participant"]
    assert len(rollup) == 1
    assert rollup[0]["away_count"] == 2
    assert rollup[0]["total_away_ms"] == 50_000
    assert rollup[0]["longest_away_ms"] == 42_000, "longest absence not tracked"


def test_rollup_ignores_events_from_before_the_mode_was_switched_on(client, auth_headers):
    """Tab switching was allowed then, so it is not a violation now."""
    meeting = client.post(
        "/api/meetings", json={"title": "Before and after", "is_interview_mode": True},
        headers=auth_headers,
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)

    # Logged while the mode was on from creation but never explicitly started,
    # so interview_mode_started_at is null and nothing is filtered out yet.
    client.post(f"/api/meetings/{meeting['code']}/focus-events",
                json={"event_type": "hidden"}, headers=auth_headers)

    before = client.get(
        f"/api/meetings/{meeting['code']}/focus-events", headers=auth_headers
    ).json()
    assert before["by_participant"][0]["away_count"] == 1

    # Now stamp a start time LATER than that event. It must drop out.
    client.patch(f"/api/meetings/{meeting['code']}/interview-mode",
                 json={"enabled": True}, headers=auth_headers)

    after = client.get(
        f"/api/meetings/{meeting['code']}/focus-events", headers=auth_headers
    ).json()
    assert after["by_participant"] == [], (
        "an event from before the mode started was counted as a violation"
    )
