"""Pydantic schemas for Interview Mode focus events."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.meeting import FocusEventType


class FocusEventCreate(BaseModel):
    """Request body for POST /api/meetings/{code}/focus-events."""

    event_type: FocusEventType


class FocusEventPublic(BaseModel):
    """One logged focus change."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    user_id: int
    user_name: str
    event_type: FocusEventType
    created_at: datetime


class FocusSummary(BaseModel):
    """Aggregate view for the host.

    `away_count` counts only the events that represent leaving — a `return`
    event is the recovery, not another offence, so counting all three types
    would roughly double the apparent number of incidents.
    """

    meeting_id: int
    total_events: int
    away_count: int
    events: list[FocusEventPublic]
