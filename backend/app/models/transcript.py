"""The `transcripts` table."""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from app.models.meeting import Meeting
    from app.models.user import User


class TranscriptSource(str, enum.Enum):
    """Which of BridgeTalk's two translation directions produced this line.

    Keeping the two directions distinguishable is what lets the transcript
    panel label speakers correctly, and what makes it possible to report sign
    recognition accuracy separately from speech recognition accuracy.
    """

    SIGN = "sign"
    SPEECH = "speech"


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source: Mapped[TranscriptSource] = mapped_column(
        Enum(
            TranscriptSource,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    # NULL for speech lines: the Web Speech API does expose a confidence value,
    # but it is not comparable to our model's softmax probability, so mixing
    # them in one column would produce a meaningless average. Only sign lines
    # carry a confidence here.
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="transcripts")
    user: Mapped["User"] = relationship(back_populates="transcripts")

    # Every read of this table is "give me meeting X's lines in time order",
    # so index the pair rather than the columns separately.
    __table_args__ = (Index("ix_transcript_meeting_created", "meeting_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        preview = self.content[:30] + ("…" if len(self.content) > 30 else "")
        return f"<Transcript meeting={self.meeting_id} source={self.source.value} {preview!r}>"
