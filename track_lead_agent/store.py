"""JSON-backed persistence for the roster.

Small enough to read in a text editor, diffable in git, and easy to regenerate
from a Google Forms / Sheets export.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config
from .models import Outreach, Roster, Scholar, Submission, TrackLead


def _json_default(obj: Any) -> str:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


def load(path: Path | None = None) -> Roster:
    """Load the roster, returning an empty one if the file does not exist."""
    path = path or config.ROSTER_PATH
    if not path.exists():
        return Roster()
    return Roster.model_validate_json(path.read_text(encoding="utf-8"))


def save(roster: Roster, path: Path | None = None) -> Path:
    """Persist the roster, creating the data directory if needed."""
    path = path or config.ROSTER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = roster.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    return path


def find_scholar(roster: Roster, ref: str) -> Scholar | None:
    """Resolve a scholar by id, exact email, or (case-insensitive) name fragment."""
    ref_l = ref.strip().lower()
    for s in roster.scholars:
        if s.id.lower() == ref_l or (s.email or "").lower() == ref_l:
            return s
    matches = [s for s in roster.scholars if ref_l in s.name.lower()]
    return matches[0] if len(matches) == 1 else None


def submissions_for(roster: Roster, scholar_id: str) -> list[Submission]:
    """All submissions for a scholar, oldest first."""
    subs = [s for s in roster.submissions if s.scholar_id == scholar_id]
    return sorted(subs, key=lambda s: (s.submitted_on, s.week))


def latest_submission(roster: Roster, scholar_id: str) -> Submission | None:
    subs = submissions_for(roster, scholar_id)
    return subs[-1] if subs else None


def outreach_for(roster: Roster, scholar_id: str) -> list[Outreach]:
    """All outreach to a scholar, oldest first."""
    items = [o for o in roster.outreach if o.scholar_id == scholar_id]
    return sorted(items, key=lambda o: o.sent_on)


def unanswered_outreach(roster: Roster, scholar_id: str) -> int:
    """Count outreach attempts since the scholar last responded."""
    streak = 0
    for o in reversed(outreach_for(roster, scholar_id)):
        if o.responded:
            break
        streak += 1
    return streak


# --- CSV import -------------------------------------------------------------

def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    # Google Forms timestamps, e.g. "8/12/2026 14:03:11"
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"yes", "y", "true", "1", "booked", "done"}


def _parse_float(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = value.strip().rstrip("%").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(value: str | None) -> int:
    return int(_parse_float(value))


def import_scholars_csv(roster: Roster, csv_path: Path, cohort: str | None = None) -> int:
    """Upsert scholars from a CSV export. Returns the number of rows applied.

    Recognised columns (case-insensitive, extras ignored):
    id, name, email, cohort, timezone, country, slack_handle, lead_id,
    status, enrolled_on, exam_deadline, notes
    """
    added = 0
    by_id = {s.id: s for s in roster.scholars}
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            name = row.get("name") or row.get("full name") or ""
            email = row.get("email") or row.get("email address") or None
            sid = row.get("id") or email or name.lower().replace(" ", "-")
            if not sid:
                continue
            existing = by_id.get(sid)
            scholar = Scholar(
                id=sid,
                name=name or (existing.name if existing else sid),
                email=email or (existing.email if existing else None),
                track=row.get("track") or config.TRACK_NAME,
                cohort=row.get("cohort") or cohort or (existing.cohort if existing else None),
                timezone=row.get("timezone") or (existing.timezone if existing else None),
                country=row.get("country") or (existing.country if existing else None),
                slack_handle=row.get("slack_handle") or (existing.slack_handle if existing else None),
                lead_id=row.get("lead_id") or (existing.lead_id if existing else None),
                status=row.get("status") or (existing.status if existing else "active"),  # type: ignore[arg-type]
                enrolled_on=_parse_date(row.get("enrolled_on")) or (existing.enrolled_on if existing else None),
                exam_deadline=_parse_date(row.get("exam_deadline")) or (existing.exam_deadline if existing else None),
                notes=row.get("notes") or (existing.notes if existing else ""),
            )
            if existing:
                roster.scholars[roster.scholars.index(existing)] = scholar
            else:
                roster.scholars.append(scholar)
            by_id[sid] = scholar
            added += 1
    return added


def import_submissions_csv(roster: Roster, csv_path: Path, week: int | None = None) -> int:
    """Import progress submissions from a Google Forms CSV export.

    Idempotent: a submission already stored for the same scholar, week, and date
    is skipped, so you can re-import the same growing Forms export every week
    without duplicating history. Returns the number of *new* rows added.

    Recognised columns (case-insensitive): scholar_id / email, week,
    submitted_on / timestamp, course_pct, labs_completed, skill_badges,
    exam_booked, hours_last_week, confidence, blockers, wins.
    Unrecognised columns are preserved in `raw`.
    """
    known = {
        "scholar_id", "email", "email address", "week", "submitted_on", "timestamp",
        "course_pct", "labs_completed", "skill_badges", "exam_booked",
        "hours_last_week", "confidence", "blockers", "wins",
    }
    seen = {(s.scholar_id, s.week, s.submitted_on) for s in roster.submissions}
    count = 0
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            ref = row.get("scholar_id") or row.get("email") or row.get("email address") or ""
            scholar = find_scholar(roster, ref) if ref else None
            if scholar is None:
                continue
            submitted = (
                _parse_date(row.get("submitted_on"))
                or _parse_date(row.get("timestamp"))
                or date.today()
            )
            row_week = _parse_int(row.get("week")) or week or 0
            fingerprint = (scholar.id, row_week, submitted)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            roster.submissions.append(
                Submission(
                    scholar_id=scholar.id,
                    week=row_week,
                    submitted_on=submitted,
                    course_pct=_parse_float(row.get("course_pct")),
                    labs_completed=_parse_int(row.get("labs_completed")),
                    skill_badges=_parse_int(row.get("skill_badges")),
                    exam_booked=_parse_bool(row.get("exam_booked")),
                    hours_last_week=_parse_float(row.get("hours_last_week")) or None,
                    confidence=_parse_int(row.get("confidence")) or None,
                    blockers=row.get("blockers", ""),
                    wins=row.get("wins", ""),
                    raw={k: v for k, v in row.items() if k not in known and v},
                )
            )
            count += 1
    return count
