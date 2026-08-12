"""Triage calibration tests.

These pin the ranking behaviour: the scoring weights are a product decision, so
changing them should require changing a test on purpose.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from track_lead_agent import triage as T
from track_lead_agent.models import Outreach, Roster, Scholar, Submission

TODAY = date(2026, 8, 12)
START = TODAY - timedelta(weeks=7)  # week 8 of 12 -> ~67% expected


def _roster(scholar: Scholar, *items) -> Roster:
    r = Roster(scholars=[scholar])
    for item in items:
        if isinstance(item, Submission):
            r.submissions.append(item)
        else:
            r.outreach.append(item)
    return r


def _scholar(**kw) -> Scholar:
    kw.setdefault("enrolled_on", START)
    return Scholar(id="s1", name="Test Scholar", **kw)


def _sub(days_ago: int, pct: float, **kw) -> Submission:
    return Submission(
        scholar_id="s1", week=8, submitted_on=TODAY - timedelta(days=days_ago),
        course_pct=pct, **kw,
    )


def test_on_pace_scholar_is_green():
    t = T.assess(_roster(_scholar(), _sub(1, 70.0, confidence=4)), _scholar(), TODAY)
    assert t.tier == "GREEN"
    assert t.score == 0


def test_expected_pct_tracks_program_week():
    assert T.expected_pct(6) == 50.0
    assert T.expected_pct(12) == 100.0
    assert T.expected_pct(20) == 100.0  # clamped
    assert T.expected_pct(None) is None


def test_behind_pace_flags_amber_with_a_reason():
    s = _scholar()
    t = T.assess(_roster(s, _sub(2, 41.0)), s, TODAY)
    assert t.tier == "AMBER"
    assert any("behind pace" in r for r in t.reasons)
    assert t.pace_gap == pytest.approx(25.67, abs=0.1)


def test_long_silence_plus_unanswered_outreach_is_a_ghost():
    s = _scholar()
    r = _roster(
        s,
        _sub(17, 22.0, confidence=2),
        Outreach(scholar_id="s1", sent_on=TODAY - timedelta(days=12)),
        Outreach(scholar_id="s1", sent_on=TODAY - timedelta(days=5)),
    )
    t = T.assess(r, s, TODAY)
    assert t.is_ghost
    assert t.tier == "RED"
    assert t.recommended_template == "reengage_ghost"


def test_a_reply_clears_the_ghost_flag():
    s = _scholar()
    r = _roster(
        s,
        _sub(17, 22.0),
        Outreach(scholar_id="s1", sent_on=TODAY - timedelta(days=12), responded=True),
        Outreach(scholar_id="s1", sent_on=TODAY - timedelta(days=5), responded=True),
    )
    t = T.assess(r, s, TODAY)
    assert not t.is_ghost


def test_never_submitted_escalates_with_elapsed_time():
    recent = _scholar(enrolled_on=TODAY - timedelta(days=12))
    stale = _scholar(enrolled_on=TODAY - timedelta(days=49))
    assert T.assess(_roster(recent), recent, TODAY).tier == "AMBER"

    late = T.assess(_roster(stale), stale, TODAY)
    assert late.tier == "RED"
    assert late.recommended_template == "onboarding_nudge"


def test_imminent_voucher_deadline_alone_clears_amber():
    s = _scholar(exam_deadline=TODAY + timedelta(days=5))
    t = T.assess(_roster(s, _sub(1, 70.0, exam_booked=False)), s, TODAY)
    assert t.tier == "RED"
    assert t.recommended_template == "exam_deadline_nudge"


def test_booking_the_exam_removes_the_deadline_signal():
    s = _scholar(exam_deadline=TODAY + timedelta(days=5))
    t = T.assess(_roster(s, _sub(1, 70.0, exam_booked=True)), s, TODAY)
    assert not any("voucher" in r for r in t.reasons)


def test_blocker_routes_to_support_template_over_generic_nudge():
    s = _scholar()
    t = T.assess(_roster(s, _sub(2, 45.0, blockers="IAM lab fails")), s, TODAY)
    assert t.recommended_template == "blocker_support"


def test_completed_scholars_are_excluded_and_score_zero():
    s = _scholar(status="completed")
    r = _roster(s, _sub(40, 30.0))
    assert T.assess(r, s, TODAY).score == 0
    assert T.assess_all(r, TODAY) == []
    assert len(T.assess_all(r, TODAY, include_done=True)) == 1


def test_ranking_puts_highest_risk_first():
    r = Roster(
        scholars=[
            Scholar(id="ok", name="On Track", enrolled_on=START),
            Scholar(id="bad", name="At Risk", enrolled_on=START),
        ],
        submissions=[
            Submission(scholar_id="ok", week=8, submitted_on=TODAY, course_pct=70.0),
            Submission(scholar_id="bad", week=4, submitted_on=TODAY - timedelta(days=25), course_pct=15.0),
        ],
    )
    ranked = T.assess_all(r, TODAY)
    assert [x.scholar_id for x in ranked] == ["bad", "ok"]
    assert T.cohort_summary(ranked)["total"] == 2
