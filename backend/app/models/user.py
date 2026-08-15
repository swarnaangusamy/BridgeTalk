"""The `users` table."""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from app.models.meeting import FocusEvent, Meeting, MeetingParticipant
    from app.models.transcript import Transcript


class UserRole(str, enum.Enum):
    """Which side of the conversation this user is on.

    The role drives the meeting-room UI: a `DEAF` user gets the camera-facing
    sign-detection panel, a `HEARING` user gets the speech-to-text microphone
    path. It is a UI hint, not a permission boundary — both roles may use both
    features, because a mixed-ability user is a real user.

    Inheriting from `str` means `user.role == "deaf"` works and the value
    serialises to JSON as a plain string.
    """

    DEAF = "deaf"
    HEARING = "hearing"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Unique + indexed: email is the login identifier, so every login does a
    # lookup on it. The database constraint is the real guarantee here — an
    # application-level "is this email taken?" check races under concurrency.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Never the password itself. A bcrypt hash is 60 characters; the column is
    # sized generously so switching to argon2 later needs no migration.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        # values_callable makes SQLAlchemy store the enum *value* ('deaf')
        # rather than its *name* ('DEAF'). Without it the column contents would
        # not match database/schema.sql, and rows written by the ORM would look
        # different from rows written by seed.sql.
        Enum(UserRole, values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=False,
        default=UserRole.HEARING,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        # `default` is applied by Python on insert; `server_default` means rows
        # inserted directly in Workbench also get a timestamp.
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # --- Relationships ----------------------------------------------------
    # `back_populates` keeps both sides of each relationship in sync in memory.
    # Deletes cascade so removing a user does not leave orphaned meeting rows
    # pointing at a user id that no longer exists.
    hosted_meetings: Mapped[list["Meeting"]] = relationship(
        back_populates="host", cascade="all, delete-orphan"
    )
    participations: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    focus_events: Mapped[list["FocusEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
