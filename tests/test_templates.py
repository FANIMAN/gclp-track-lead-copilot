"""Template rendering tests: real numbers in, no unresolved placeholders out."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from track_lead_agent import templates as tpl
from track_lead_agent.models import Roster, Scholar, Submission, TrackLead

TODAY = date(2026, 8, 12)
START = TODAY - timedelta(weeks=7)


@pytest.fixture
def roster() -> Roster:
    return Roster(
        leads=[TrackLead(id="nebiyu", name="Nebiyu", is_me=True)],
        scholars=[
            Scholar(id="s1", name="Mekdes Alemu", email="mekdes@example.com",
                    cohort="2026-Q3", lead_id="nebiyu", enrolled_on=START,
                    exam_deadline=TODAY + timedelta(days=20))
        ],
        submissions=[
            Submission(scholar_id="s1", week=8, submitted_on=TODAY - timedelta(days=2),
                       course_pct=41.0, labs_completed=6, skill_badges=1, confidence=2,
                       blockers="Qwiklabs IAM lab fails at the service-account step.")
        ],
    )


def test_every_shipped_template_renders_without_stray_placeholders(roster):
    scholar = roster.scholars[0]
    keys = [t["key"] for t in tpl.list_templates()]
    assert keys, "no templates loaded"
    for key in keys:
        out = tpl.render(roster, scholar, key, today=TODAY)
        text = out["subject"] + out["body"]
        assert not re.search(r"\{[a-z_]+\}", text), f"{key} left an unfilled merge field"
        assert out["body"].strip()


def test_merge_fields_carry_the_scholars_real_numbers(roster):
    out = tpl.render(roster, roster.scholars[0], "gentle_nudge", today=TODAY)
    assert "Mekdes" in out["body"]
    assert "41%" in out["body"]
    assert "67%" in out["body"]  # week 8 of 12


def test_blocker_template_quotes_what_they_actually_said(roster):
    out = tpl.render(roster, roster.scholars[0], "blocker_support", today=TODAY)
    assert "service-account step" in out["body"]


def test_lead_signature_comes_from_the_assigned_lead(roster):
    out = tpl.render(roster, roster.scholars[0], "one_on_one_invite", today=TODAY)
    assert "Nebiyu" in out["body"]


def test_missing_data_degrades_to_a_dash_instead_of_raising():
    bare = Roster(scholars=[Scholar(id="x", name="No Data")])
    out = tpl.render(bare, bare.scholars[0], "gentle_nudge", today=TODAY)
    assert "—" in out["body"]


def test_unknown_template_key_is_a_clear_error(roster):
    with pytest.raises(KeyError, match="Unknown template"):
        tpl.render(roster, roster.scholars[0], "nope", today=TODAY)
