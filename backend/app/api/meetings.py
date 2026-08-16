"""Meeting endpoints: create, fetch, join, leave, end, history."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.meeting import Meeting, MeetingParticipant
from app.models.user import User
from app.schemas.meeting import (
    MeetingCreate,
    MeetingDetail,
    MeetingJoinResponse,
    MeetingPublic,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# Ambiguous characters are excluded on purpose. Meeting codes get read aloud,
# written on a whiteboard, and typed by someone who is watching a video call
# rather than their keyboard. O/0, I/1 and L/1 are the pairs that cause failed
# joins, so none of them appear.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_GROUP_LENGTH = 3
CODE_GROUPS = 2  # e.g. "K7Q-2M4"
MAX_CODE_ATTEMPTS = 10


def generate_meeting_code(db: Session) -> str:
    """Generate a short, unique, human-typable meeting code.

    `secrets.choice` rather than `random.choice`: meeting codes are the only
    thing standing between a stranger and a private conversation, so they must
    not be predictable from previously issued codes.

    31 characters over 6 positions is ~887 million combinations, which is
    ample for a project of this size while staying short enough to read aloud.
    """
    for _ in range(MAX_CODE_ATTEMPTS):
        code = "-".join(
            "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP_LENGTH))
            for _ in range(CODE_GROUPS)
        )
        # The UNIQUE constraint on meetings.code is the real guarantee; this
        # check just avoids surfacing an integrity error for a collision we can
        # cheaply retry past.
        if db.scalar(select(Meeting).where(Meeting.code == code)) is None:
            return code

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not allocate a unique meeting code, please retry",
    )


def _load_meeting_by_code(db: Session, code: str) -> Meeting:
    """Fetch a meeting by code with host and participants eagerly loaded.

    `selectinload` issues one extra query for the whole collection instead of
    one per row. Without it, serialising a meeting with N participants costs
    N+1 queries — the classic ORM performance trap.
    """
    meeting = db.scalar(
        select(Meeting)
        .where(Meeting.code == code.strip().upper())
        .options(
            selectinload(Meeting.host),
            selectinload(Meeting.participants).selectinload(MeetingParticipant.user),
        )
    )

    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No meeting found with code '{code}'",
        )

    return meeting


def _assert_participant_or_host(meeting: Meeting, user: User) -> None:
    """Reject callers who have nothing to do with this meeting.

    Without this check, knowing a meeting id would be enough to read a private
    conversation's transcript. Membership, not merely being logged in, is the
    access boundary.
    """
    if meeting.host_id == user.id:
        return
    if any(participant.user_id == user.id for participant in meeting.participants):
        return

    # 403 rather than 404: the caller has proven they know a valid code, so
    # hiding the meeting's existence buys nothing and makes debugging harder.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not a participant in this meeting",
    )


@router.post(
    "",
    response_model=MeetingPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a meeting",
)
def create_meeting(payload: MeetingCreate, db: DbSession, current_user: CurrentUser) -> Meeting:
    """Create a meeting and return its join code.

    The creator becomes the host but is NOT auto-joined: creating a meeting for
    later and being in it now are different things, and `started_at` should
    reflect when people actually arrived.
    """
    meeting = Meeting(
        code=generate_meeting_code(db),
        title=payload.title.strip(),
        host_id=current_user.id,
        is_interview_mode=payload.is_interview_mode,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return meeting


@router.get("/history", response_model=list[MeetingPublic], summary="Meetings you took part in")
def meeting_history(db: DbSession, current_user: CurrentUser) -> list[Meeting]:
    """Every meeting the caller hosted or attended, newest first.

    Declared before the /{code} route on purpose: FastAPI matches routes in
    declaration order, so /{code} would otherwise swallow "history" and try to
    look up a meeting whose code is literally "history".
    """
    hosted = select(Meeting.id).where(Meeting.host_id == current_user.id)
    attended = select(MeetingParticipant.meeting_id).where(
        MeetingParticipant.user_id == current_user.id
    )

    meetings = db.scalars(
        select(Meeting)
        .where(Meeting.id.in_(hosted.union(attended)))
        .options(selectinload(Meeting.host))
        .order_by(Meeting.created_at.desc())
    ).all()

    return list(meetings)


@router.get("/{code}", response_model=MeetingDetail, summary="Meeting detail")
def get_meeting(code: str, db: DbSession, current_user: CurrentUser) -> Meeting:
    """Look up a meeting by code.

    Any authenticated user holding a valid code may read this, because they
    need to see the title before deciding to join. The transcript endpoints
    are the ones that enforce membership.
    """
    return _load_meeting_by_code(db, code)


@router.post("/{code}/join", response_model=MeetingJoinResponse, summary="Join a meeting")
def join_meeting(code: str, db: DbSession, current_user: CurrentUser) -> MeetingJoinResponse:
    """Join a meeting, recording attendance.

    Rejoining after a dropped connection writes a NEW participant row rather
    than reusing the old one, so the attendance log stays truthful about
    disconnections instead of quietly pretending they never happened.
    """
    meeting = _load_meeting_by_code(db, code)

    if meeting.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This meeting has already ended",
        )

    now = datetime.now(timezone.utc)

    # "First participant" means the meeting clock had not started yet. The
    # frontend uses this to decide which peer creates the WebRTC offer; if both
    # peers offered simultaneously the negotiation would collide.
    is_first = meeting.started_at is None
    if is_first:
        meeting.started_at = now

    db.add(MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, joined_at=now))
    db.commit()
    db.refresh(meeting)

    return MeetingJoinResponse(
        meeting=MeetingDetail.model_validate(_load_meeting_by_code(db, code)),
        is_first_participant=is_first,
    )


@router.post("/{code}/leave", response_model=MeetingDetail, summary="Leave a meeting")
def leave_meeting(code: str, db: DbSession, current_user: CurrentUser) -> Meeting:
    """Stamp the caller's most recent attendance row with a leave time."""
    meeting = _load_meeting_by_code(db, code)

    open_row = db.scalar(
        select(MeetingParticipant)
        .where(
            MeetingParticipant.meeting_id == meeting.id,
            MeetingParticipant.user_id == current_user.id,
            MeetingParticipant.left_at.is_(None),
        )
        .order_by(MeetingParticipant.joined_at.desc())
    )

    if open_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are not currently in this meeting",
        )

    open_row.left_at = datetime.now(timezone.utc)
    db.commit()

    return _load_meeting_by_code(db, code)


@router.post("/{code}/end", response_model=MeetingDetail, summary="End a meeting (host only)")
def end_meeting(code: str, db: DbSession, current_user: CurrentUser) -> Meeting:
    """Close a meeting for everyone. Host only.

    Restricted to the host because ending a meeting makes its code unusable —
    any participant being able to do that would be a griefing vector.
    """
    meeting = _load_meeting_by_code(db, code)

    if meeting.host_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the meeting host can end the meeting",
        )

    if meeting.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This meeting has already ended",
        )

    now = datetime.now(timezone.utc)
    meeting.ended_at = now

    # Close every attendance row still open, so a participant who closed their
    # laptop instead of clicking Leave does not stay "in" the meeting forever.
    for participant in meeting.participants:
        if participant.left_at is None:
            participant.left_at = now

    db.commit()

    return _load_meeting_by_code(db, code)
