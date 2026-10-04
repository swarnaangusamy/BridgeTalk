"""Pydantic schemas for transcript lines."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.transcript import TranscriptSource


class TranscriptCreate(BaseModel):
    """Request body for POST /api/transcripts."""

    meeting_id: int
    segment_id: Optional[str] = None
    source: TranscriptSource = Field(
        description="'sign' for model output, 'speech' for Web Speech API output."
    )
    content: str = Field(min_length=1, max_length=5000)
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Softmax probability for 'sign' lines. Leave null for 'speech': the "
            "Web Speech API's confidence is not comparable to our model's, so "
            "mixing them in one column would make any average meaningless."
        ),
    )


class TranscriptPublic(BaseModel):
    """One transcript line as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    user_id: int
    # Denormalised for display so the transcript panel does not need a second
    # request per line just to render a speaker label.
    user_name: str
    segment_id: Optional[str] = None
    source: TranscriptSource
    content: str
    confidence: Optional[float] = None
    created_at: datetime
