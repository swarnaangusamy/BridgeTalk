"""The `meetings`, `meeting_participants` and `focus_events` tables."""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from app.models.transcript import Transcript
    from app.models.user import User


class FocusEventType(str, enum.Enum):
    """What the browser reported during Interview Mode.

    - `BLUR`   — the window lost keyboard focus (user clicked another app)
    - `HIDDEN` — the tab became invisible (user switched tabs or minimised)
    - `RETURN` — focus/visibility came back

    Being precise about what these mean matters, because Interview Mode is a
    deterrent and not proctoring: these three events are genuinely all the
    browser will tell us. It cannot see a second monitor, a phone, or another
    person in the room.
    """

    BLUR = "blur"
    HIDDEN = "hidden"
    RETURN = "return"


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # A short, human-typable join code (e.g. "K7Q-2M4"). Indexed and unique
    # because every join hits the database by code, never by id.
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    host_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    is_interview_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # `started_at` is set when the first participant joins, not at creation —
    # a meeting created on Monday for Friday should not report a Monday start.
    # `ended_at` stays NULL while the meeting is live, which is exactly the
    # filter the history endpoint uses to separate active from past meetings.
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # --- Relationships ----------------------------------------------------
    host: Mapped["User"] = relationship(back_populates="hosted_meetings")
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    focus_events: Mapped[list["FocusEvent"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        """A meeting is active until someone ends it."""
        return self.ended_at is None

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<Meeting id={self.id} code={self.code!r} active={self.is_active}>"


class MeetingParticipant(Base):
    """Join table recording who was in a meeting and when.

    This is a log, not a set: rejoining after a dropped connection writes a new
    row rather than mutating the old one, so the attendance history stays
    truthful about disconnections.
    """

    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship(back_populates="participations")

    # "Is this user currently in this meeting?" is asked on every join request,
    # and it filters on both columns at once — hence the composite index.
    __table_args__ = (Index("ix_participant_meeting_user", "meeting_id", "user_id"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<MeetingParticipant meeting={self.meeting_id} user={self.user_id}>"


class FocusEvent(Base):
    """One Interview Mode focus change, logged against the meeting.

    Stored server-side rather than kept in browser state so that the record
    survives a page reload — a tab switch the user then refreshes away should
    still appear in the meeting record.
    """

    __tablename__ = "focus_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[FocusEventType] = mapped_column(
        Enum(
            FocusEventType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="focus_events")
    user: Mapped["User"] = relationship(back_populates="focus_events")

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<FocusEvent meeting={self.meeting_id} type={self.event_type.value}>"
