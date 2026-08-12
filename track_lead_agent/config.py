"""Configuration for the track-lead copilot.

Everything program-specific lives here so a new cohort is a config edit, not a
code edit.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

DATA_DIR = Path(os.environ.get("GCLP_DATA_DIR", PROJECT_DIR / "data"))
ROSTER_PATH = DATA_DIR / "roster.json"
TEMPLATES_PATH = Path(os.environ.get("GCLP_TEMPLATES_PATH", DATA_DIR / "templates.yaml"))

# gemini-2.5-flash is capped at 20 requests/day on the AI Studio free tier;
# gemini-flash-latest has substantially more headroom.
MODEL = os.environ.get("GCLP_MODEL", "gemini-flash-latest")

# --- Program shape (Google Cloud Career Launchpad) -------------------------
PROGRAM_NAME = "Google Cloud Career Launchpad"
PROGRAM_WEEKS = int(os.environ.get("GCLP_PROGRAM_WEEKS", "12"))
TRACK_NAME = os.environ.get("GCLP_TRACK", "Cloud Cybersecurity")

# --- Triage thresholds -----------------------------------------------------
# Tier cutoffs on the 0-100 risk score.
TIER_RED = 60
TIER_AMBER = 30
TIER_WATCH = 10

# A scholar is "silent" after this many days with no submission.
SILENT_DAYS_SOFT = 7
SILENT_DAYS_HARD = 14
SILENT_DAYS_CRITICAL = 21

# Unanswered outreach attempts before we call someone a ghost.
GHOST_UNANSWERED = 2

# Exam-voucher urgency windows, in days remaining.
EXAM_URGENT_DAYS = 21
EXAM_SOON_DAYS = 45

# How far behind the expected pace (percentage points) counts as slipping.
PACE_GAP_SMALL = 10
PACE_GAP_MEDIUM = 20
PACE_GAP_LARGE = 30
