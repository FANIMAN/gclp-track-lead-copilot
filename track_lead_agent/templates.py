"""Load handbook templates and render them against a scholar's real numbers."""

from __future__ import annotations

import string
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from . import config, store
from .models import Roster, Scholar
from .triage import Triage, assess, program_week


class _Missing(dict):
    """Render unknown merge fields as an em dash instead of raising."""

    def __missing__(self, key: str) -> str:  # noqa: D105
        return "—"


_FORMATTER = string.Formatter()


def load_templates(path: Path | None = None) -> dict[str, Any]:
    """Read templates.yaml. Returns {'defaults': {...}, 'templates': {...}}."""
    path = path or config.TEMPLATES_PATH
    if not path.exists():
        return {"defaults": {}, "templates": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("defaults", {})
    data.setdefault("templates", {})
    return data


def list_templates(path: Path | None = None) -> list[dict[str, str]]:
    """Summarise available templates for the agent to choose from."""
    data = load_templates(path)
    return [
        {
            "key": key,
            "label": tpl.get("label", key),
            "when": tpl.get("when", ""),
            "channel": tpl.get("channel", ""),
            "tone": tpl.get("tone", ""),
        }
        for key, tpl in data["templates"].items()
    ]


def build_context(
    roster: Roster,
    scholar: Scholar,
    triage: Triage | None = None,
    today: date | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble every merge field available to a template."""
    today = today or date.today()
    triage = triage or assess(roster, scholar, today)
    latest = triage.latest
    data = load_templates()

    lead = next((l for l in roster.leads if l.id == scholar.lead_id), None)
    if lead is None:
        lead = next((l for l in roster.leads if l.is_me), None)

    ctx: dict[str, Any] = dict(data["defaults"])
    if lead:
        ctx["lead_name"] = lead.name

    ctx.update(
        {
            "name": scholar.name,
            "first_name": scholar.name.split()[0] if scholar.name else "there",
            "track": scholar.track,
            "cohort": scholar.cohort or "—",
            "week": program_week(scholar, today) or (latest.week if latest else "—"),
            "course_pct": f"{latest.course_pct:.0f}" if latest else "—",
            "expected_pct": f"{triage.expected_pct:.0f}" if triage.expected_pct is not None else "—",
            "pace_gap": f"{triage.pace_gap:.0f}" if triage.pace_gap is not None else "—",
            "days_silent": triage.days_silent if triage.days_silent is not None else "—",
            "labs_completed": latest.labs_completed if latest else "—",
            "skill_badges": latest.skill_badges if latest else "—",
            "blockers": (latest.blockers.strip() if latest and latest.blockers.strip() else "none reported"),
            "wins": (latest.wins.strip() if latest and latest.wins.strip() else "—"),
            "exam_deadline": scholar.exam_deadline.isoformat() if scholar.exam_deadline else "—",
            "days_to_exam": (scholar.exam_deadline - today).days if scholar.exam_deadline else "—",
        }
    )
    if extra:
        ctx.update(extra)
    return ctx


def render(
    roster: Roster,
    scholar: Scholar,
    template_key: str,
    triage: Triage | None = None,
    today: date | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render one template for one scholar. Raises KeyError on unknown key."""
    data = load_templates()
    tpl = data["templates"].get(template_key)
    if tpl is None:
        raise KeyError(
            f"Unknown template '{template_key}'. Available: {sorted(data['templates'])}"
        )

    ctx = build_context(roster, scholar, triage=triage, today=today, extra=extra)
    safe = _Missing(ctx)

    subject = _FORMATTER.vformat(tpl.get("subject", ""), (), safe)
    body = _FORMATTER.vformat(tpl.get("body", ""), (), safe)

    return {
        "template_key": template_key,
        "label": tpl.get("label", template_key),
        "channel": tpl.get("channel", "email"),
        "tone": tpl.get("tone", ""),
        "to": scholar.email or scholar.slack_handle or scholar.name,
        "subject": subject.strip(),
        "body": body.strip(),
        "merge_context": {k: v for k, v in ctx.items() if not k.endswith("_link")},
    }
