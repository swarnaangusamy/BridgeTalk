"""Transcript export tests — the .txt and .pdf download paths.

Transcript CRUD and its access-control boundary are covered in
test_meetings.py. This file covers only the two export formats, which were
added later and have their own failure modes: a PDF that is really an error
page, an empty meeting that errors instead of producing a file, and the
member-only check being forgotten on the newer of the two routes.
"""

import pytest


@pytest.fixture()
def second_user(client):
    """A second account, so the membership boundary can be tested.

    Defined locally, matching test_meetings.py and test_focus_events.py. These
    files each need one and the project has kept them local rather than in
    conftest, so this follows the existing pattern instead of changing it.
    """
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Thamizhthilaga S D S",
            "email": "thamizh.export@example.com",
            "password": "another-password",
            "role": "hearing",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# PDF export
# --------------------------------------------------------------------------- #
#
# The .txt export remains the accessible default — every screen reader handles
# it with no extra dependency. The PDF is what gets emailed or handed in, and
# it is generated on the SERVER so the member-only access check cannot be
# bypassed by a client that decides to render its own.


def test_pdf_export_returns_a_real_pdf(client, auth_headers):
    meeting = client.post(
        "/api/meetings", json={"title": "PDF test"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)
    client.post(
        "/api/transcripts",
        json={"meeting_id": meeting["id"], "source": "sign", "content": "HELLO", "confidence": 0.9},
        headers=auth_headers,
    )

    response = client.get(f"/api/transcripts/{meeting['id']}/export.pdf", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert ".pdf" in response.headers["content-disposition"]
    # %PDF is the format's magic number. Asserting on it rather than on length
    # is what distinguishes a real document from an error page served with the
    # wrong content type.
    assert response.content.startswith(b"%PDF")


def test_pdf_export_works_for_an_empty_transcript(client, auth_headers):
    """A meeting nobody signed in must still produce a valid file.

    Returning an error here would make "nothing was said" look like a bug.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Silent"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)

    response = client.get(f"/api/transcripts/{meeting['id']}/export.pdf", headers=auth_headers)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_pdf_export_is_member_only(client, auth_headers, second_user):
    """Same boundary as every other transcript endpoint.

    A transcript is the record of a private conversation, so being logged in is
    deliberately not sufficient — and the PDF route must not be the one that
    forgot to check.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Private"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)

    outsider = {"Authorization": f"Bearer {second_user['access_token']}"}
    response = client.get(f"/api/transcripts/{meeting['id']}/export.pdf", headers=outsider)

    assert response.status_code in (403, 404), "a non-member reached a private transcript"


def test_txt_export_contains_every_header_field(client, auth_headers):
    """The .txt header is built from _transcript_header, so all fields appear.

    Asserted on the text export rather than the PDF because reportlab
    compresses its content stream — the strings are genuinely not present as
    raw bytes, which an earlier version of this test wrongly assumed.
    """
    meeting = client.post(
        "/api/meetings", json={"title": "Header parity"}, headers=auth_headers
    ).json()
    client.post(f"/api/meetings/{meeting['code']}/join", headers=auth_headers)

    text = client.get(f"/api/transcripts/{meeting['id']}/export", headers=auth_headers).text

    for label in ("Meeting", "Code", "Started", "Ended", "Lines"):
        assert f"{label}:" in text, f"the .txt header lost its {label} field"
    assert meeting["code"] in text
    assert "Header parity" in text


def test_both_formats_are_built_from_one_header_builder():
    """Where the drift this guards against would actually happen.

    The two exports share `_transcript_header`. Testing that shared function
    directly is the honest level for this invariant: asserting on rendered PDF
    bytes tests reportlab's compression settings, not our code.
    """
    import inspect

    from app.api import transcripts as module

    txt_source = inspect.getsource(module.export_transcript)
    pdf_source = inspect.getsource(module.export_transcript_pdf)

    assert "_transcript_header" in txt_source, ".txt export stopped using the shared header"
    assert "_transcript_header" in pdf_source, ".pdf export stopped using the shared header"
    assert "_transcript_rows" in txt_source and "_transcript_rows" in pdf_source

    # And the builder returns the fields both formats rely on.
    labels = [label for label, _ in module._transcript_header(
        type("M", (), {"title": "t", "code": "C", "started_at": None, "ended_at": None})(), 0
    )]
    assert labels == ["Meeting", "Code", "Started", "Ended", "Lines"]
