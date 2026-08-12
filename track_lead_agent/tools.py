"""ADK function tools.

Every tool returns a plain dict with a "status" key so the model can tell
success from failure without parsing prose. Sentinel defaults (-1 / "") are used
instead of None because function-calling schemas handle them more reliably.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from . import config, store, templates as tpl_mod, triage as triage_mod
from .models import Outreach, Scholar, Submission, TrackLead


def _err(msg: str, **extra: Any) -> dict:
    return {"status": "error", "message": msg, **extra}


def _ok(**payload: Any) -> dict:
    return {"status": "ok", **payload}


# --- Roster reads -----------------------------------------------------------

def list_scholars(cohort: str = "", lead_id: str = "", status: str = "") -> dict:
    """List scholars on the track, optionally filtered.

    Args:
        cohort: Only return this cohort. Empty string means all cohorts.
        lead_id: Only return scholars assigned to this track lead. Empty means all.
        status: Filter by status: active, at_risk, inactive, completed, withdrawn.
            Empty string means all statuses.

    Returns:
        A dict with the matching scholars and a count.
    """
    roster = store.load()
    rows = []
    for s in roster.scholars:
        if cohort and s.cohort != cohort:
            continue
        if lead_id and s.lead_id != lead_id:
            continue
        if status and s.status != status:
            continue
        latest = store.latest_submission(roster, s.id)
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "email": s.email,
                "cohort": s.cohort,
                "status": s.status,
                "lead_id": s.lead_id,
                "last_checkin_week": latest.week if latest else None,
                "last_checkin_on": latest.submitted_on.isoformat() if latest else None,
                "course_pct": latest.course_pct if latest else None,
            }
        )
    return _ok(count=len(rows), scholars=rows)


def get_scholar(scholar_ref: str) -> dict:
    """Get one scholar's full picture: profile, check-in history, outreach log, and triage.

    Args:
        scholar_ref: Scholar id, email address, or a distinctive part of their name.

    Returns:
        A dict with profile, submissions, outreach history, and the current triage verdict.
    """
    roster = store.load()
    scholar = store.find_scholar(roster, scholar_ref)
    if scholar is None:
        return _err(f"No unique scholar matched '{scholar_ref}'. Try an id or email.")

    t = triage_mod.assess(roster, scholar)
    return _ok(
        profile=scholar.model_dump(mode="json"),
        submissions=[s.model_dump(mode="json") for s in store.submissions_for(roster, scholar.id)],
        outreach=[o.model_dump(mode="json") for o in store.outreach_for(roster, scholar.id)],
        unanswered_outreach=store.unanswered_outreach(roster, scholar.id),
        triage=t.to_dict(),
    )


def list_track_leads() -> dict:
    """List the track leads and how many scholars each one carries.

    Returns:
        A dict with each lead, their assigned scholar count, and their at-risk count.
    """
    roster = store.load()
    results = triage_mod.assess_all(roster)
    by_lead: dict[str, list] = {}
    for r in results:
        scholar = next((s for s in roster.scholars if s.id == r.scholar_id), None)
        key = scholar.lead_id if scholar and scholar.lead_id else "_unassigned"
        by_lead.setdefault(key, []).append(r)

    rows = []
    for lead in roster.leads:
        mine = by_lead.get(lead.id, [])
        rows.append(
            {
                **lead.model_dump(mode="json"),
                "scholars": len(mine),
                "red": sum(1 for r in mine if r.tier == "RED"),
                "amber": sum(1 for r in mine if r.tier == "AMBER"),
            }
        )
    return _ok(
        leads=rows,
        unassigned_scholars=len(by_lead.get("_unassigned", [])),
    )


# --- Triage -----------------------------------------------------------------

def triage_cohort(cohort: str = "", lead_id: str = "", tier: str = "", limit: int = 0) -> dict:
    """Rank scholars by who most needs you to reach out, with the reasons why.

    This is the primary tool for "who should I contact today". It scores silence,
    pace against the program timeline, self-reported blockers, low confidence,
    exam-voucher deadlines, and unanswered outreach.

    Args:
        cohort: Restrict to one cohort. Empty means all.
        lead_id: Restrict to scholars assigned to one track lead. Empty means all.
        tier: Restrict to one tier: RED, AMBER, WATCH, or GREEN. Empty means all.
        limit: Maximum number of scholars to return. 0 means no limit.

    Returns:
        A dict with a cohort summary and a ranked list, each entry carrying a
        score, tier, plain-English reasons, and a recommended template key.
    """
    roster = store.load()
    if not roster.scholars:
        return _err("Roster is empty. Import scholars first with import_roster_csv.")

    results = triage_mod.assess_all(roster, lead_id=lead_id or None, cohort=cohort or None)
    summary = triage_mod.cohort_summary(results)

    if tier:
        results = [r for r in results if r.tier == tier.upper()]
    if limit and limit > 0:
        results = results[:limit]

    return _ok(summary=summary, ranked=[r.to_dict() for r in results])


def cohort_report(cohort: str = "", lead_id: str = "") -> dict:
    """Produce roll-up numbers for a stand-up or a report to the program manager.

    Args:
        cohort: Restrict to one cohort. Empty means all.
        lead_id: Restrict to one track lead's scholars. Empty means all.

    Returns:
        A dict with tier counts, median progress, blocked count, and ghost count.
    """
    roster = store.load()
    results = triage_mod.assess_all(roster, lead_id=lead_id or None, cohort=cohort or None)
    summary = triage_mod.cohort_summary(results)
    summary["needs_outreach_now"] = [
        {"name": r.name, "tier": r.tier, "top_reason": r.reasons[0] if r.reasons else ""}
        for r in results
        if r.tier in {"RED", "AMBER"}
    ]
    return _ok(**summary)


# --- Writes -----------------------------------------------------------------

def record_progress(
    scholar_ref: str,
    week: int,
    course_pct: float = -1.0,
    labs_completed: int = -1,
    skill_badges: int = -1,
    exam_booked: bool = False,
    hours_last_week: float = -1.0,
    confidence: int = -1,
    blockers: str = "",
    wins: str = "",
) -> dict:
    """Record a scholar's progress check-in, then re-triage them.

    Use this when a scholar replies with their progress, whether that arrives by
    form, chat, or email.

    Args:
        scholar_ref: Scholar id, email, or distinctive part of their name.
        week: Program week this check-in covers.
        course_pct: Percent of the course complete, 0-100. Use -1 if not reported.
        labs_completed: Number of labs finished. Use -1 if not reported.
        skill_badges: Number of skill badges earned. Use -1 if not reported.
        exam_booked: Whether they have booked their certification exam.
        hours_last_week: Study hours in the past week. Use -1 if not reported.
        confidence: Self-rated confidence 1-5. Use -1 if not reported.
        blockers: Anything they said is blocking them. Empty if none.
        wins: Anything they achieved worth celebrating. Empty if none.

    Returns:
        A dict with the stored submission and the updated triage verdict.
    """
    roster = store.load()
    scholar = store.find_scholar(roster, scholar_ref)
    if scholar is None:
        return _err(f"No unique scholar matched '{scholar_ref}'.")

    previous = store.latest_submission(roster, scholar.id)
    sub = Submission(
        scholar_id=scholar.id,
        week=week,
        submitted_on=date.today(),
        course_pct=course_pct if course_pct >= 0 else (previous.course_pct if previous else 0.0),
        labs_completed=labs_completed if labs_completed >= 0 else (previous.labs_completed if previous else 0),
        skill_badges=skill_badges if skill_badges >= 0 else (previous.skill_badges if previous else 0),
        exam_booked=exam_booked,
        hours_last_week=hours_last_week if hours_last_week >= 0 else None,
        confidence=confidence if confidence >= 1 else None,
        blockers=blockers,
        wins=wins,
    )
    roster.submissions.append(sub)

    # A reply to us means they are no longer ghosting.
    for o in store.outreach_for(roster, scholar.id):
        o.responded = True

    store.save(roster)
    t = triage_mod.assess(roster, scholar)
    return _ok(recorded=sub.model_dump(mode="json"), triage=t.to_dict())


def log_outreach(scholar_ref: str, channel: str = "email", template_key: str = "custom", notes: str = "") -> dict:
    """Record that you sent a scholar a message, so ghost detection stays accurate.

    Call this after you actually send something. Unanswered attempts accumulate
    and push a scholar toward the re-engagement path.

    Args:
        scholar_ref: Scholar id, email, or distinctive part of their name.
        channel: One of email, slack, discord, whatsapp, linkedin, call, other.
        template_key: Which template you used, or "custom".
        notes: Optional free-text note about what you sent.

    Returns:
        A dict confirming the log entry and the current unanswered streak.
    """
    roster = store.load()
    scholar = store.find_scholar(roster, scholar_ref)
    if scholar is None:
        return _err(f"No unique scholar matched '{scholar_ref}'.")

    valid = {"email", "slack", "discord", "whatsapp", "linkedin", "call", "other"}
    roster.outreach.append(
        Outreach(
            scholar_id=scholar.id,
            sent_on=date.today(),
            channel=channel if channel in valid else "other",  # type: ignore[arg-type]
            template_key=template_key,
            notes=notes,
        )
    )
    store.save(roster)
    return _ok(
        scholar=scholar.name,
        unanswered_streak=store.unanswered_outreach(roster, scholar.id),
    )


def upsert_scholar(
    name: str,
    email: str = "",
    scholar_id: str = "",
    cohort: str = "",
    lead_id: str = "",
    status: str = "",
    timezone: str = "",
    enrolled_on: str = "",
    exam_deadline: str = "",
    notes: str = "",
) -> dict:
    """Add a scholar or update an existing one. Only non-empty fields are applied.

    Args:
        name: Full name.
        email: Email address.
        scholar_id: Explicit id. Defaults to the email, then a name slug.
        cohort: Cohort label, e.g. "2026-Q3".
        lead_id: Id of the track lead who owns this scholar.
        status: active, at_risk, inactive, completed, or withdrawn.
        timezone: IANA timezone, e.g. "Africa/Addis_Ababa".
        enrolled_on: Enrolment date as YYYY-MM-DD. Drives the pace calculation.
        exam_deadline: Exam voucher expiry as YYYY-MM-DD.
        notes: Free-text notes.

    Returns:
        A dict with the stored scholar record.
    """
    roster = store.load()
    sid = scholar_id or email or name.lower().replace(" ", "-")
    existing = next((s for s in roster.scholars if s.id == sid), None)

    def pick(new: str, old: Any) -> Any:
        return new if new else old

    scholar = Scholar(
        id=sid,
        name=name or (existing.name if existing else sid),
        email=pick(email, existing.email if existing else None),
        track=config.TRACK_NAME,
        cohort=pick(cohort, existing.cohort if existing else None),
        timezone=pick(timezone, existing.timezone if existing else None),
        lead_id=pick(lead_id, existing.lead_id if existing else None),
        status=pick(status, existing.status if existing else "active"),  # type: ignore[arg-type]
        enrolled_on=store._parse_date(enrolled_on) or (existing.enrolled_on if existing else None),
        exam_deadline=store._parse_date(exam_deadline) or (existing.exam_deadline if existing else None),
        notes=pick(notes, existing.notes if existing else ""),
    )
    if existing:
        roster.scholars[roster.scholars.index(existing)] = scholar
    else:
        roster.scholars.append(scholar)
    store.save(roster)
    return _ok(scholar=scholar.model_dump(mode="json"), created=existing is None)


def add_track_lead(name: str, lead_id: str = "", email: str = "", cohort: str = "", is_me: bool = False) -> dict:
    """Add or update a track lead.

    Args:
        name: Lead's full name.
        lead_id: Explicit id. Defaults to the email, then a name slug.
        email: Email address.
        cohort: Cohort they run.
        is_me: True if this is the user of this agent. Used to sign messages.

    Returns:
        A dict with the stored track lead record.
    """
    roster = store.load()
    lid = lead_id or email or name.lower().replace(" ", "-")
    existing = next((l for l in roster.leads if l.id == lid), None)
    lead = TrackLead(
        id=lid,
        name=name,
        email=email or (existing.email if existing else None),
        track=config.TRACK_NAME,
        cohort=cohort or (existing.cohort if existing else None),
        is_me=is_me or (existing.is_me if existing else False),
    )
    if existing:
        roster.leads[roster.leads.index(existing)] = lead
    else:
        roster.leads.append(lead)
    store.save(roster)
    return _ok(lead=lead.model_dump(mode="json"), created=existing is None)


def import_roster_csv(csv_path: str, kind: str = "scholars", cohort: str = "") -> dict:
    """Bulk-import scholars or progress submissions from a CSV export.

    Works with Google Sheets / Google Forms exports. Column names are matched
    case-insensitively and unknown columns are preserved.

    Args:
        csv_path: Path to the CSV file on disk.
        kind: Either "scholars" or "submissions".
        cohort: Cohort label to stamp on imported scholars. Optional.

    Returns:
        A dict with the number of rows applied.
    """
    path = Path(csv_path).expanduser()
    if not path.exists():
        return _err(f"File not found: {path}")

    roster = store.load()
    if kind == "scholars":
        n = store.import_scholars_csv(roster, path, cohort=cohort or None)
    elif kind == "submissions":
        n = store.import_submissions_csv(roster, path)
    else:
        return _err("kind must be 'scholars' or 'submissions'")
    store.save(roster)
    return _ok(kind=kind, rows_applied=n, total_scholars=len(roster.scholars))


# --- Messaging --------------------------------------------------------------

def list_message_templates() -> dict:
    """List the message templates from the Track Lead Handbook, with when to use each.

    Returns:
        A dict with each template's key, label, trigger situation, channel, and tone.
    """
    rows = tpl_mod.list_templates()
    if not rows:
        return _err(f"No templates loaded from {config.TEMPLATES_PATH}.")
    return _ok(count=len(rows), templates=rows)


def draft_message(scholar_ref: str, template_key: str = "", extra_notes: str = "") -> dict:
    """Draft a message to one scholar, filled in with their real numbers.

    If template_key is empty, the triage engine picks the right template for
    their current situation.

    Args:
        scholar_ref: Scholar id, email, or distinctive part of their name.
        template_key: Which template to use. Empty means auto-select.
        extra_notes: Context to weave in, e.g. "she mentioned a new job".

    Returns:
        A dict with subject, body, channel, the merge values used, and the
        triage reasoning behind the template choice.
    """
    roster = store.load()
    scholar = store.find_scholar(roster, scholar_ref)
    if scholar is None:
        return _err(f"No unique scholar matched '{scholar_ref}'.")

    t = triage_mod.assess(roster, scholar)
    key = template_key or t.recommended_template
    try:
        draft = tpl_mod.render(roster, scholar, key, triage=t)
    except KeyError as exc:
        return _err(str(exc))

    return _ok(
        draft=draft,
        auto_selected=not template_key,
        triage=t.to_dict(),
        extra_notes=extra_notes,
        reminder="Personalise before sending, then call log_outreach to record it.",
    )


def draft_outreach_batch(tier: str = "", limit: int = 5, cohort: str = "", lead_id: str = "") -> dict:
    """Draft messages for everyone who needs contacting, ranked by urgency.

    This is the "give me my outreach list for today" tool: it triages, picks the
    right template per person, and renders each one.

    Args:
        tier: Restrict to RED, AMBER, WATCH, or GREEN. Empty means RED and AMBER.
        limit: Maximum number of drafts. Defaults to 5.
        cohort: Restrict to one cohort. Empty means all.
        lead_id: Restrict to one track lead's scholars. Empty means all.

    Returns:
        A dict with one ready-to-send draft per scholar, most urgent first.
    """
    roster = store.load()
    if not roster.scholars:
        return _err("Roster is empty. Import scholars first with import_roster_csv.")

    results = triage_mod.assess_all(roster, lead_id=lead_id or None, cohort=cohort or None)
    wanted = {tier.upper()} if tier else {"RED", "AMBER"}
    results = [r for r in results if r.tier in wanted][: max(1, limit)]

    drafts = []
    for r in results:
        scholar = next((s for s in roster.scholars if s.id == r.scholar_id), None)
        if scholar is None:
            continue
        try:
            draft = tpl_mod.render(roster, scholar, r.recommended_template, triage=r)
        except KeyError:
            continue
        drafts.append(
            {
                "scholar": scholar.name,
                "scholar_id": scholar.id,
                "tier": r.tier,
                "score": r.score,
                "why": r.reasons,
                "draft": draft,
            }
        )
    return _ok(count=len(drafts), drafts=drafts)
