"""Build a demo cohort that exercises every triage path.

Replace with your real roster via `cli import` once you have the cohort sheet.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from . import store
from .models import Outreach, Roster, Scholar, Submission, TrackLead


def seed(today: date | None = None) -> Path:
    today = today or date.today()
    start = today - timedelta(weeks=7)  # cohort is in week 8 of 12

    roster = Roster(
        leads=[
            TrackLead(id="nebiyu", name="Nebiyu", email="lead@example.org",
                      cohort="2026-Q3", is_me=True),
            TrackLead(id="co-lead", name="Amina Yusuf", email="amina@example.org", cohort="2026-Q3"),
        ]
    )

    def add(sid: str, name: str, email: str, lead: str = "nebiyu", **kw) -> Scholar:
        s = Scholar(id=sid, name=name, email=email, cohort="2026-Q3",
                    lead_id=lead, enrolled_on=start, **kw)
        roster.scholars.append(s)
        return s

    def sub(sid: str, week: int, days_ago: int, pct: float, **kw) -> None:
        roster.submissions.append(
            Submission(scholar_id=sid, week=week, submitted_on=today - timedelta(days=days_ago),
                       course_pct=pct, **kw)
        )

    # On pace, high confidence — GREEN
    add("sara", "Sara Tesfaye", "sara@example.com")
    sub("sara", 8, 1, 72.0, labs_completed=14, skill_badges=4, confidence=4,
        hours_last_week=9, wins="Finished the Cloud IDS lab and passed the practice exam.")

    # Slightly behind — AMBER
    add("daniel", "Daniel Okoro", "daniel@example.com")
    sub("daniel", 8, 3, 48.0, labs_completed=8, skill_badges=2, confidence=3, hours_last_week=4)

    # Blocked, low confidence — needs blocker_support
    add("mekdes", "Mekdes Alemu", "mekdes@example.com")
    sub("mekdes", 8, 2, 41.0, labs_completed=6, skill_badges=1, confidence=2, hours_last_week=3,
        blockers="Qwiklabs IAM lab keeps failing at the service-account step.")

    # Silent 17 days, well behind, two unanswered pings — ghost
    add("kwame", "Kwame Mensah", "kwame@example.com")
    sub("kwame", 5, 17, 22.0, labs_completed=3, skill_badges=0, confidence=2)
    for d in (12, 5):
        roster.outreach.append(Outreach(scholar_id="kwame", sent_on=today - timedelta(days=d),
                                        channel="slack", template_key="gentle_nudge"))

    # Voucher expiring, exam not booked
    add("liya", "Liya Bekele", "liya@example.com",
        exam_deadline=today + timedelta(days=14))
    sub("liya", 8, 4, 66.0, labs_completed=12, skill_badges=3, confidence=3, exam_booked=False)

    # Never submitted anything
    add("tomas", "Tomas Girma", "tomas@example.com", lead="co-lead")

    # Doing great, already booked — celebrate
    add("fatima", "Fatima Nasser", "fatima@example.com", lead="co-lead",
        exam_deadline=today + timedelta(days=30))
    sub("fatima", 8, 1, 88.0, labs_completed=18, skill_badges=6, confidence=5,
        exam_booked=True, hours_last_week=11, wins="Booked the exam for next month.")

    return store.save(roster)


if __name__ == "__main__":
    print(seed())
