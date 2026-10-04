"""The one caption protocol, shared by sign and speech.

WHY THIS MODULE EXISTS
----------------------
Captions used to travel two different ways. Sign predictions were broadcast
from the inference loop carrying `result.sentence` — the whole ACCUMULATED
sentence — while speech was relayed as a separate message type carrying just
the phrase. Three bugs followed directly from that:

  * the caption text grew without bound, reading
    "BBBD location location warm warm fast we we we" after a few commits;
  * the transcript stored one row per emitted word, each containing everything
    said so far, so it read "a", "a b", "a b c";
  * the sender was EXCLUDED from its own broadcast, so the two participants
    were looking at state assembled by different code paths and disagreed.

The fix is a single event shape with a producer-generated `segment_id`:

    interim  -> carries the FULL CURRENT text of that segment.
                Receivers REPLACE the line with that id. They never append.
    final    -> closes the segment. The producer then starts a new id.

A segment's text is only what was said in that segment. Never history.

Persistence happens once, on the final event, keyed by `segment_id`. The
database has a UNIQUE constraint on (meeting_id, segment_id), so a retry or a
reconnect that replays the final event collides instead of duplicating.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError

from app.models.transcript import Transcript, TranscriptSource

logger = logging.getLogger("bridgetalk.ws.captions")

# The two caption sources. Anything else is rejected rather than stored, so a
# typo cannot create a third kind of caption nothing knows how to render.
VALID_SOURCES = frozenset({"sign", "speech"})


def build_caption_event(
    *,
    meeting_code: str,
    segment_id: str,
    speaker_id: int,
    speaker_name: str,
    source: str,
    text: str,
    is_final: bool,
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    """The wire shape every caption takes, whichever source produced it.

    One shape for both sources is what lets the caption area, the transcript
    panel and the persistence path each have a single code path instead of a
    branch per source — and a branch per source is where the two drifted apart
    before.
    """
    return {
        "type": "caption",
        "meeting_code": meeting_code,
        "segment_id": segment_id,
        "speaker": {"id": speaker_id, "name": speaker_name},
        "source": source,
        "text": text,
        "is_final": is_final,
        "confidence": confidence,
        # Server time, deliberately. Two clients with skewed clocks would
        # otherwise produce a transcript that does not sort into the order the
        # conversation actually happened in.
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def validate_caption(message: dict[str, Any]) -> Optional[str]:
    """Return an error string, or None when the message is usable."""
    segment_id = message.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        return "segment_id is required and must be a non-empty string"
    if len(segment_id) > 64:
        return "segment_id must be 64 characters or fewer"

    source = message.get("source")
    if source not in VALID_SOURCES:
        return f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}"

    text = message.get("text")
    if not isinstance(text, str):
        return "text must be a string"

    confidence = message.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        return "confidence must be a number or null"

    return None


def persist_final_caption(
    session,
    *,
    meeting_id: int,
    user_id: int,
    segment_id: str,
    source: str,
    text: str,
    confidence: Optional[float],
) -> bool:
    """Write one row for a finished segment. Returns True if a row was created.

    Idempotent by database constraint, not by hope. The caller may legitimately
    deliver the same final event twice — a client retry after a dropped
    acknowledgement, or a reconnect that replays its tail — and the second
    attempt must be a no-op rather than a duplicate line in someone's
    transcript.
    """
    cleaned = text.strip()
    if not cleaned:
        # An empty final segment is not worth a row. This happens when a
        # speech recogniser closes a segment it never got words for.
        return False

    row = Transcript(
        meeting_id=meeting_id,
        user_id=user_id,
        segment_id=segment_id,
        source=TranscriptSource(source),
        content=cleaned,
        confidence=confidence,
    )
    session.add(row)

    try:
        session.commit()
        return True
    except IntegrityError:
        # The UNIQUE constraint fired: this segment is already stored.
        session.rollback()
        logger.debug("segment %s already persisted for meeting %s", segment_id, meeting_id)
        return False
