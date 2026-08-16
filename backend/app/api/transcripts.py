"""Transcript endpoints: append, fetch, export."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
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

    rows = db.scalars(
        select(Transcript)
        .where(Transcript.meeting_id == meeting_id)
        .options(selectinload(Transcript.user))
        .order_by(Transcript.created_at.asc(), Transcript.id.asc())
    ).all()

    lines = [
        "BridgeTalk meeting transcript",
        "=" * 60,
        f"Meeting:  {meeting.title}",
        f"Code:     {meeting.code}",
        f"Started:  {meeting.started_at.isoformat() if meeting.started_at else 'not started'}",
        f"Ended:    {meeting.ended_at.isoformat() if meeting.ended_at else 'still active'}",
        f"Lines:    {len(rows)}",
        "=" * 60,
        "",
    ]

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
