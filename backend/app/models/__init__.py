"""SQLAlchemy ORM models.

Importing this package registers every table on `Base.metadata`, which is what
`init_db()` needs in order to create them. Anything that adds a new table must
be re-exported here, or `create_all` will silently skip it.
"""

from app.models.meeting import FocusEvent, FocusEventType, Meeting, MeetingParticipant
from app.models.transcript import Transcript, TranscriptSource
from app.models.user import User, UserRole

__all__ = [
    "FocusEvent",
    "FocusEventType",
    "Meeting",
    "MeetingParticipant",
    "Transcript",
    "TranscriptSource",
    "User",
    "UserRole",
]
