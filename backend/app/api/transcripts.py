"""Transcript endpoints: append, fetch, export."""

import io
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import Transcript
from app.models.user import User
from app.schemas.transcript import TranscriptCreate, TranscriptPublic

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


def _load_meeting_for_member(db: Session, meeting_id: int, user: User) -> Meeting:
    """Fetch a meeting, refusing callers who are not part of it.

    A meeting transcript is a record of a private conversation. Being logged in
    is not sufficient to read one — membership is the boundary, and it is
    enforced here rather than trusted to the frontend.
    """
    meeting = db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants))
    )

    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No meeting with id {meeting_id}",
        )

    is_host = meeting.host_id == user.id
    is_participant = any(p.user_id == user.id for p in meeting.participants)

    if not (is_host or is_participant):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this meeting",
        )

    return meeting


def _to_public(transcript: Transcript) -> TranscriptPublic:
    """Attach the speaker's display name to a transcript row."""
    return TranscriptPublic(
        id=transcript.id,
        meeting_id=transcript.meeting_id,
        user_id=transcript.user_id,
        user_name=transcript.user.name,
        # Was missing: the column is written but was never serialised, so a
        # client could not tell which utterance a row belonged to and the
        # idempotency key was invisible from outside the database.
        segment_id=transcript.segment_id,
        source=transcript.source,
        content=transcript.content,
        confidence=transcript.confidence,
        created_at=transcript.created_at,
    )


@router.post(
    "",
    response_model=TranscriptPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Append a line to a meeting transcript",
)
def create_transcript(
    payload: TranscriptCreate, db: DbSession, current_user: CurrentUser
) -> TranscriptPublic:
    """Persist one line of recognised sign or speech.

    The line is always attributed to the authenticated caller, never to a
    user_id supplied in the request body. Trusting the body would let anyone
    put words in another participant's mouth in the permanent record.
    """
    meeting = _load_meeting_for_member(db, payload.meeting_id, current_user)

    if meeting.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add to the transcript of a meeting that has ended",
        )

    transcript = Transcript(
        meeting_id=meeting.id,
        user_id=current_user.id,
        source=payload.source,
        content=payload.content.strip(),
        confidence=payload.confidence,
        created_at=datetime.now(timezone.utc),
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    # The relationship is not loaded on a freshly inserted row, and _to_public
    # needs the speaker's name.
    transcript.user = current_user
    return _to_public(transcript)


@router.get(
    "/{meeting_id}",
    response_model=list[TranscriptPublic],
    summary="Full transcript for a meeting",
)
def get_transcript(meeting_id: int, db: DbSession, current_user: CurrentUser) -> list[TranscriptPublic]:
    """Return every line for a meeting, oldest first.

    Chronological order is the point of a transcript, and the composite index
    on (meeting_id, created_at) means the database returns it already sorted.
    """
    _load_meeting_for_member(db, meeting_id, current_user)

    rows = db.scalars(
        select(Transcript)
        .where(Transcript.meeting_id == meeting_id)
        .options(selectinload(Transcript.user))
        .order_by(Transcript.created_at.asc(), Transcript.id.asc())
    ).all()

    return [_to_public(row) for row in rows]


def _transcript_header(meeting, row_count: int) -> list[tuple[str, str]]:
    """The metadata block shown at the top of every export, in both formats.

    Built once and shared so the .txt and .pdf cannot drift apart — two copies
    of "which fields go in the header" is exactly the kind of thing that ends
    up disagreeing after one of them is edited.
    """
    return [
        ("Meeting", meeting.title),
        ("Code", meeting.code),
        ("Started", meeting.started_at.isoformat() if meeting.started_at else "not started"),
        ("Ended", meeting.ended_at.isoformat() if meeting.ended_at else "still active"),
        ("Lines", str(row_count)),
    ]


def _transcript_rows(db, meeting_id: int):
    """Transcript rows in conversation order, speaker eagerly loaded."""
    return db.scalars(
        select(Transcript)
        .where(Transcript.meeting_id == meeting_id)
        .options(selectinload(Transcript.user))
        .order_by(Transcript.created_at.asc(), Transcript.id.asc())
    ).all()


@router.get(
    "/{meeting_id}/export.pdf",
    summary="Download the transcript as a PDF file",
)
def export_transcript_pdf(
    meeting_id: int, db: DbSession, current_user: CurrentUser
) -> Response:
    """Render the transcript as a PDF.

    WHY A PDF AS WELL AS PLAIN TEXT
    -------------------------------
    The .txt export remains the accessible default: every screen reader handles
    it with no extra dependency. A PDF is what gets attached to an email or
    handed in as a record, and it is what people actually ask for.

    Generated on the SERVER rather than in the browser, for two reasons. The
    access check (`_load_meeting_for_member`) already lives here and must not be
    duplicated on the client where it could be bypassed; and the header block is
    shared with the .txt path, so the two formats cannot disagree about what a
    transcript contains.
    """
    # Imported lazily. reportlab is only needed by this one endpoint, and a
    # deployment that never exports a PDF should not pay the import cost at
    # startup — the same pattern used for TensorFlow and faster-whisper.
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    meeting = _load_meeting_for_member(db, meeting_id, current_user)
    rows = _transcript_rows(db, meeting_id)

    buffer = io.BytesIO()
    pdf = pdf_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    left = 18 * mm
    right_limit = width - 18 * mm
    y = height - 20 * mm
    line_height = 5.2 * mm

    def new_page() -> float:
        pdf.showPage()
        return height - 20 * mm

    # --- title -------------------------------------------------------------
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(left, y, "BridgeTalk meeting transcript")
    y -= line_height * 1.6

    pdf.setFont("Helvetica", 9.5)
    for label, value in _transcript_header(meeting, len(rows)):
        pdf.drawString(left, y, f"{label}:")
        pdf.drawString(left + 24 * mm, y, str(value))
        y -= line_height
    y -= line_height * 0.6

    pdf.setStrokeColorRGB(0.75, 0.75, 0.75)
    pdf.line(left, y, right_limit, y)
    y -= line_height * 1.2

    # --- lines -------------------------------------------------------------
    if not rows:
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(left, y, "(no transcript lines were recorded for this meeting)")
    else:
        for row in rows:
            if y < 22 * mm:
                y = new_page()

            timestamp = row.created_at.strftime("%H:%M:%S")
            tag = "SIGN" if row.source.value == "sign" else "SPEECH"
            confidence = f" ({row.confidence:.0%})" if row.confidence is not None else ""

            pdf.setFont("Helvetica-Bold", 8.5)
            pdf.drawString(left, y, f"[{timestamp}] {tag}")
            pdf.setFont("Helvetica", 9.5)
            pdf.drawString(left + 30 * mm, y, f"{row.user.name}:{confidence}")
            y -= line_height * 0.9

            # Wrap the content by measuring the actual rendered width, rather
            # than guessing a character count — proportional fonts make a
            # fixed-width guess wrong in both directions.
            pdf.setFont("Helvetica", 10.5)
            usable = right_limit - (left + 6 * mm)
            words = row.content.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if pdf.stringWidth(candidate, "Helvetica", 10.5) <= usable:
                    current = candidate
                    continue
                pdf.drawString(left + 6 * mm, y, current)
                y -= line_height
                if y < 22 * mm:
                    y = new_page()
                current = word
            if current:
                pdf.drawString(left + 6 * mm, y, current)
            y -= line_height * 1.3

    pdf.save()

    filename = f"bridgetalk-transcript-{meeting.code}.pdf"
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{meeting_id}/export",
    response_class=PlainTextResponse,
    summary="Download the transcript as a .txt file",
)
def export_transcript(
    meeting_id: int, db: DbSession, current_user: CurrentUser
) -> PlainTextResponse:
    """Render the transcript as a plain-text file download.

    Plain text rather than PDF on purpose: it is readable by every screen
    reader without an extra dependency, which is the right default for an
    accessibility project.
    """
    meeting = _load_meeting_for_member(db, meeting_id, current_user)
    rows = _transcript_rows(db, meeting_id)

    lines = ["BridgeTalk meeting transcript", "=" * 60]
    # Same header builder the PDF uses, so the two formats cannot disagree
    # about what a transcript header contains.
    lines += [f"{label + ':':<9} {value}" for label, value in _transcript_header(meeting, len(rows))]
    lines += ["=" * 60, ""]

    if not rows:
        lines.append("(no transcript lines were recorded for this meeting)")
    else:
        for row in rows:
            timestamp = row.created_at.strftime("%H:%M:%S")
            # The source tag is what makes the record auditable after the fact:
            # a reader can see which lines came from the sign model — and with
            # what confidence — rather than assuming every line is equally
            # reliable.
            tag = "SIGN " if row.source.value == "sign" else "SPEECH"
            confidence = f"  ({row.confidence:.0%})" if row.confidence is not None else ""
            lines.append(f"[{timestamp}] {tag} {row.user.name}: {row.content}{confidence}")

    body = "\n".join(lines) + "\n"

    # Codes contain only A-Z, 2-9 and a hyphen, so this filename is always safe
    # to put in a header without escaping.
    filename = f"bridgetalk-transcript-{meeting.code}.txt"

    return PlainTextResponse(
        content=body,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
