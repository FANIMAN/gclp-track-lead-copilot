"""Risk scoring: turn progress submissions into a ranked outreach list.

Deliberately deterministic and pure. The LLM decides *what to say*; this module
decides *who needs saying to*, so the ranking is reproducible and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import config, store
from .models import Roster, Scholar, Submission


@dataclass
class Signal:
    """One reason a scholar scored points."""

    code: str
    points: int
    detail: str


@dataclass
class Triage:
    """The verdict for a single scholar."""

    scholar_id: str
    name: str
    score: int
    tier: str
    signals: list[Signal] = field(default_factory=list)
    recommended_template: str = "checkin_request"
    days_silent: int | None = None
    pace_gap: float | None = None
    expected_pct: float | None = None
    course_pct: float | None = None
    latest: Submission | None = None
    is_ghost: bool = False

    @property
    def reasons(self) -> list[str]:
        return [s.detail for s in self.signals]

    def to_dict(self) -> dict:
        return {
            "scholar_id": self.scholar_id,
            "name": self.name,
            "score": self.score,
            "tier": self.tier,
            "reasons": self.reasons,
            "recommended_template": self.recommended_template,
            "days_silent": self.days_silent,
            "pace_gap": round(self.pace_gap, 1) if self.pace_gap is not None else None,
            "expected_pct": round(self.expected_pct, 1) if self.expected_pct is not None else None,
            "course_pct": self.course_pct,
            "is_ghost": self.is_ghost,
            "last_submission_week": self.latest.week if self.latest else None,
            "blockers": self.latest.blockers if self.latest else "",
        }


def program_week(scholar: Scholar, today: date) -> int | None:
    """Which week of the program the scholar should be in."""
    if not scholar.enrolled_on:
        return None
    return max(1, ((today - scholar.enrolled_on).days // 7) + 1)


def expected_pct(week: int | None) -> float | None:
    """Straight-line expected completion for a given program week."""
    if week is None:
        return None
    return min(100.0, 100.0 * week / config.PROGRAM_WEEKS)


def assess(roster: Roster, scholar: Scholar, today: date | None = None) -> Triage:
    """Score one scholar and recommend an opening move."""
    today = today or date.today()
    signals: list[Signal] = []

    latest = store.latest_submission(roster, scholar.id)
    unanswered = store.unanswered_outreach(roster, scholar.id)
    week = program_week(scholar, today)
    exp = expected_pct(week)

    # --- Silence -----------------------------------------------------------
    days_silent: int | None = None
    if latest:
        days_silent = (today - latest.submitted_on).days
        if days_silent >= config.SILENT_DAYS_CRITICAL:
            signals.append(Signal("silent_critical", 35, f"No check-in for {days_silent} days"))
        elif days_silent >= config.SILENT_DAYS_HARD:
            signals.append(Signal("silent_hard", 26, f"No check-in for {days_silent} days"))
        elif days_silent >= config.SILENT_DAYS_SOFT + 3:
            signals.append(Signal("silent_soft", 16, f"No check-in for {days_silent} days"))
        elif days_silent >= config.SILENT_DAYS_SOFT:
            signals.append(Signal("silent_mild", 8, f"Last check-in {days_silent} days ago"))
    elif scholar.enrolled_on and (today - scholar.enrolled_on).days >= 10:
        days_silent = (today - scholar.enrolled_on).days
        # Someone who has never once checked in is the hardest case to recover,
        # and gets harder the longer it runs.
        points = 70 if days_silent >= 42 else 55 if days_silent >= 28 else 32
        signals.append(
            Signal("never_submitted", points, f"Never submitted a check-in ({days_silent} days enrolled)")
        )

    # --- Pace --------------------------------------------------------------
    gap: float | None = None
    if latest and exp is not None:
        gap = exp - latest.course_pct
        detail = f"{gap:.0f} points behind pace ({latest.course_pct:.0f}% vs {exp:.0f}% expected)"
        if gap >= config.PACE_GAP_LARGE:
            signals.append(Signal("pace_large", 42, detail))
        elif gap >= config.PACE_GAP_MEDIUM:
            signals.append(Signal("pace_medium", 30, detail))
        elif gap >= config.PACE_GAP_SMALL:
            signals.append(Signal("pace_small", 12, f"Slightly behind pace ({latest.course_pct:.0f}% vs {exp:.0f}% expected)"))

    # --- Self-reported trouble ---------------------------------------------
    if latest and latest.blockers.strip():
        signals.append(Signal("blocker", 15, f"Reported a blocker: {latest.blockers.strip()[:120]}"))
    if latest and latest.confidence is not None and latest.confidence <= 2:
        signals.append(Signal("low_confidence", 12, f"Low self-reported confidence ({latest.confidence}/5)"))
    if latest and latest.hours_last_week is not None and latest.hours_last_week < 2:
        signals.append(Signal("low_hours", 8, f"Only {latest.hours_last_week:g}h logged last week"))

    # --- Exam / voucher ----------------------------------------------------
    if scholar.exam_deadline:
        days_left = (scholar.exam_deadline - today).days
        booked = bool(latest and latest.exam_booked)
        if not booked and days_left <= config.EXAM_URGENT_DAYS:
            label = f"{days_left} days" if days_left >= 0 else f"{-days_left} days PAST"
            # A voucher deadline is immovable, so it alone must clear AMBER.
            points = 60 if days_left <= 7 else 32
            signals.append(Signal("exam_urgent", points, f"Exam not booked, voucher deadline in {label}"))
        elif not booked and days_left <= config.EXAM_SOON_DAYS:
            signals.append(Signal("exam_soon", 10, f"Exam not booked, {days_left} days to voucher deadline"))

    # --- Ghosting ----------------------------------------------------------
    is_ghost = unanswered >= config.GHOST_UNANSWERED and (days_silent or 0) >= config.SILENT_DAYS_HARD
    if unanswered >= config.GHOST_UNANSWERED:
        signals.append(Signal("unanswered", 20, f"{unanswered} outreach attempts with no reply"))

    # --- Status overrides --------------------------------------------------
    if scholar.status == "inactive":
        signals.append(Signal("status_inactive", 40, "Marked inactive"))
    elif scholar.status == "at_risk":
        signals.append(Signal("status_at_risk", 15, "Manually flagged at risk"))
    elif scholar.status in {"completed", "withdrawn"}:
        signals = [Signal(f"status_{scholar.status}", 0, f"Status: {scholar.status}")]

    score = min(100, sum(s.points for s in signals))
    if scholar.status in {"completed", "withdrawn"}:
        score = 0

    if score >= config.TIER_RED:
        tier = "RED"
    elif score >= config.TIER_AMBER:
        tier = "AMBER"
    elif score >= config.TIER_WATCH:
        tier = "WATCH"
    else:
        tier = "GREEN"

    result = Triage(
        scholar_id=scholar.id,
        name=scholar.name,
        score=score,
        tier=tier,
        signals=signals,
        days_silent=days_silent,
        pace_gap=gap,
        expected_pct=exp,
        course_pct=latest.course_pct if latest else None,
        latest=latest,
        is_ghost=is_ghost,
    )
    result.recommended_template = recommend_template(result, scholar)
    return result


def recommend_template(t: Triage, scholar: Scholar) -> str:
    """Pick the opening move. Most specific situation wins."""
    codes = {s.code for s in t.signals}

    if scholar.status in {"completed", "withdrawn"}:
        return "celebrate_milestone" if scholar.status == "completed" else "checkin_request"
    if t.is_ghost or "status_inactive" in codes:
        return "reengage_ghost"
    if "never_submitted" in codes:
        return "onboarding_nudge"
    if "exam_urgent" in codes:
        return "exam_deadline_nudge"
    if "blocker" in codes:
        return "blocker_support"
    if t.tier == "RED":
        return "one_on_one_invite"
    if "low_confidence" in codes:
        return "encouragement"
    if t.tier == "AMBER":
        return "gentle_nudge"
    if t.tier == "WATCH":
        return "checkin_request"
    if t.latest and t.latest.wins.strip():
        return "celebrate_milestone"
    return "checkin_request"


def assess_all(
    roster: Roster,
    today: date | None = None,
    lead_id: str | None = None,
    cohort: str | None = None,
    include_done: bool = False,
) -> list[Triage]:
    """Score everyone, highest risk first."""
    today = today or date.today()
    results = []
    for scholar in roster.scholars:
        if lead_id and scholar.lead_id != lead_id:
            continue
        if cohort and scholar.cohort != cohort:
            continue
        if not include_done and scholar.status in {"completed", "withdrawn"}:
            continue
        results.append(assess(roster, scholar, today))
    return sorted(results, key=lambda r: (-r.score, r.name))


def cohort_summary(results: list[Triage]) -> dict:
    """Roll-up stats for a stand-up or a report to the program manager."""
    tiers = {"RED": 0, "AMBER": 0, "WATCH": 0, "GREEN": 0}
    for r in results:
        tiers[r.tier] += 1
    with_pct = [r.course_pct for r in results if r.course_pct is not None]
    return {
        "total": len(results),
        "tiers": tiers,
        "ghosts": sum(1 for r in results if r.is_ghost),
        "median_course_pct": round(sorted(with_pct)[len(with_pct) // 2], 1) if with_pct else None,
        "no_submission": sum(1 for r in results if r.latest is None),
        "blocked": sum(1 for r in results if r.latest and r.latest.blockers.strip()),
    }
