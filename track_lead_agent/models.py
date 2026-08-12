"""Data models for the GCLP Cloud Cybersecurity track-lead copilot."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

ScholarStatus = Literal["active", "at_risk", "inactive", "completed", "withdrawn"]
Channel = Literal["email", "slack", "discord", "whatsapp", "linkedin", "call", "other"]


class TrackLead(BaseModel):
    """A track lead (mentor) responsible for a slice of the cohort."""

    id: str
    name: str
    email: str | None = None
    track: str = "Cloud Cybersecurity"
    cohort: str | None = None
    timezone: str | None = None
    slack_handle: str | None = None
    is_me: bool = False
    notes: str = ""


class Scholar(BaseModel):
    """A GCLP scholar enrolled in a track."""

    id: str
    name: str
    email: str | None = None
    track: str = "Cloud Cybersecurity"
    cohort: str | None = None
    timezone: str | None = None
    country: str | None = None
    slack_handle: str | None = None
    lead_id: str | None = None
    status: ScholarStatus = "active"
    enrolled_on: date | None = None
    exam_deadline: date | None = None
    notes: str = ""


class Submission(BaseModel):
    """One progress check-in submitted by a scholar."""

    scholar_id: str
    week: int
    submitted_on: date
    course_pct: float = 0.0
    labs_completed: int = 0
    skill_badges: int = 0
    exam_booked: bool = False
    hours_last_week: float | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    blockers: str = ""
    wins: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class Outreach(BaseModel):
    """A message you sent to a scholar, and whether they answered."""

    scholar_id: str
    sent_on: date
    channel: Channel = "email"
    template_key: str = "custom"
    responded: bool = False
    notes: str = ""


class Roster(BaseModel):
    """The whole persisted state."""

    leads: list[TrackLead] = Field(default_factory=list)
    scholars: list[Scholar] = Field(default_factory=list)
    submissions: list[Submission] = Field(default_factory=list)
    outreach: list[Outreach] = Field(default_factory=list)
