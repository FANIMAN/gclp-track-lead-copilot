# GCLP Track Lead Copilot

An agent that helps a **Google Cloud Career Launchpad** track lead run a cohort:
it triages scholar progress check-ins, ranks who needs outreach today, and drafts
the message for each person using your program's templates.

Built on [Google ADK](https://google.github.io/adk-docs/).

```
RED    Kwame Mensah    score 100  → reengage_ghost
       · No check-in for 17 days
       · 45 points behind pace (22% vs 67% expected)
       · 2 outreach attempts with no reply
RED    Tomas Girma     score  70  → onboarding_nudge
AMBER  Mekdes Alemu    score  57  → blocker_support
```

**You send every message.** The agent has no email, Slack, or send capability of
any kind, by design.

---

## Contents

- [Quickstart](#quickstart)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Feeding it your real data](#feeding-it-your-real-data)
- [Running it](#running-it)
- [Daily workflow](#daily-workflow)
- [How triage works](#how-triage-works)
- [Message templates](#message-templates)
- [Running it for real](#running-it-for-real)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Privacy and security](#privacy-and-security)
- [Known gaps](#known-gaps)

---

## Quickstart

Five commands from clone to a working agent:

```bash
git clone https://github.com/<you>/gclp-track-lead-copilot.git
cd gclp-track-lead-copilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then paste your GOOGLE_API_KEY into it
```

Then load the demo cohort and look at it — no API key needed for this part:

```bash
python -m track_lead_agent.cli seed
python -m track_lead_agent.cli triage
```

If that prints a ranked list, the logic works. Now start the agent:

```bash
adk web
```

Open **http://127.0.0.1:8000**, pick **`track_lead_agent`** from the top-left
dropdown, and ask *"Who do I need to reach out to this week?"*

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Developed on 3.12 |
| A Gemini API key | Free from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Your cohort roster | A spreadsheet with names, emails, enrolment dates |
| A weekly check-in form | Google Form, or any CSV source — see [below](#step-2-set-up-the-weekly-check-in-form) |

You do **not** need a Google Cloud project, billing, or Vertex AI. An AI Studio
key is enough (mind the [quota](#model-choice-and-quota)).

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Verify:

```bash
python -m pytest tests/ -q         # 17 passing
adk --version                      # 2.6.3 or later
```

---

## Configuration

Copy `.env.example` to `.env` and fill it in. **`.env` is gitignored — never
commit it.**

```bash
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=your-key-here

GCLP_MODEL=gemini-flash-latest
GCLP_TRACK=Cloud Cybersecurity
GCLP_PROGRAM_WEEKS=12
```

### All settings

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_API_KEY` | — | **Required.** Your AI Studio key. |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` | Set `TRUE` to use Vertex AI instead (then set `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` and drop the API key). |
| `GCLP_MODEL` | `gemini-flash-latest` | Which model backs the agent. |
| `GCLP_TRACK` | `Cloud Cybersecurity` | Your track name. Appears in messages. |
| `GCLP_PROGRAM_WEEKS` | `12` | Program length. Drives the pace calculation. |
| `GCLP_DATA_DIR` | `./data` | Where `roster.json` lives. Point at a synced folder to share across machines. |
| `GCLP_TEMPLATES_PATH` | `./data/templates.yaml` | Where message templates live. |

`.env` is read from wherever you launch `adk`, so **always run from the project root.**

### Model choice and quota

This matters more than it sounds. On the AI Studio free tier:

- **`gemini-2.5-flash` is capped at 20 requests per day.** One conversational
  turn costs about two. You will exhaust it in roughly ten questions.
- **`gemini-flash-latest`** (the default here) has substantially more headroom.

To see what your key can actually reach:

```bash
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from google import genai
c = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
print([m.name.replace('models/','') for m in c.models.list()
       if 'generateContent' in (m.supported_actions or [])])"
```

For steady daily use, enable billing on the key's project. The workload is small
— a few dozen short calls a day.

### Tuning the scoring

Every threshold lives in `track_lead_agent/config.py`: tier cutoffs, what counts
as "silent", how close a voucher deadline has to be to matter. Edit it and re-run
`python -m track_lead_agent.cli triage` to see the effect immediately.

If you change the weights, `tests/test_triage.py` will fail — that's deliberate.
Update the tests to match your new intent.

---

## Feeding it your real data

State lives in one file: **`data/roster.json`**. It's gitignored. Everything
below is about getting your cohort into it.

### Step 1: Import your roster

Export your cohort sheet as CSV. Recognised columns (case-insensitive, extras
ignored, order irrelevant):

| Column | Required | Notes |
|---|---|---|
| `name` | yes | Full name. First name is used in messages. |
| `email` | yes | Also the join key for check-ins. |
| `enrolled_on` | **strongly** | `YYYY-MM-DD`. **Without it there is no pace scoring at all.** |
| `cohort` | no | e.g. `2026-Q3`. Lets you run several cohorts side by side. |
| `lead_id` | no | Who owns this scholar. Drives the message signature. |
| `exam_deadline` | no | `YYYY-MM-DD`. Voucher expiry. Enables deadline alerts. |
| `status` | no | `active`, `at_risk`, `inactive`, `completed`, `withdrawn`. Defaults to `active`. |
| `timezone`, `country`, `slack_handle`, `notes` | no | Context only. |

```bash
python -m track_lead_agent.cli import ~/cohort.csv --kind scholars --cohort 2026-Q3
```

Re-running this **updates** existing scholars rather than duplicating them, so
it's safe to re-import whenever your sheet changes.

See `data/scholars.sample.csv` for the exact shape. *(All names in the sample
files are fictional.)*

### Step 2: Set up the weekly check-in form

Create a Google Form with these questions. The **titles must match these column
names** so the importer picks them up:

| Form question title | Type | Notes |
|---|---|---|
| *(Collect email addresses — turn this on in Form settings)* | — | **Required.** This is how check-ins match to scholars. |
| `week` | Short answer / number | Which program week this covers. |
| `course_pct` | Short answer / number | Percent complete, 0–100. |
| `labs_completed` | Short answer / number | |
| `skill_badges` | Short answer / number | |
| `exam_booked` | Yes/No | |
| `hours_last_week` | Short answer / number | |
| `confidence` | Linear scale 1–5 | Drives the low-confidence signal. |
| `blockers` | Paragraph | Free text. Routes them to `blocker_support`. |
| `wins` | Paragraph | Free text. Routes them to `celebrate_milestone`. |

Keep it short. A two-minute form gets answered; a ten-minute one gets ghosted,
and ghosting is the thing you're trying to measure.

### Step 3: Import check-ins

**File → Download → CSV** from the Form's response sheet, then:

```bash
python -m track_lead_agent.cli import ~/responses.csv --kind submissions
```

The importer handles Google Forms exports as-is — `Timestamp` and
`Email Address` are recognised automatically.

**This is idempotent.** A submission already stored for the same scholar, week,
and date is skipped, so you can re-import the same growing export every week and
it only adds what's new:

```
first import:   "rows_applied": 6
second import:  "rows_applied": 0
```

### Step 4 (alternative): just tell the agent

For one-off updates, skip the CSV entirely and talk to it:

> "Mekdes replied — she's at 52%, still stuck on the IAM lab, but sounding more positive."

It parses that into a stored check-in and re-triages her. Anything not stated is
left blank rather than guessed.

### A weekly rhythm that works

```bash
# Monday morning
python -m track_lead_agent.cli import ~/Downloads/responses.csv --kind submissions
python -m track_lead_agent.cli triage
```

Then open `adk web` and work down the list.

---

## Running it

Always from the project root.

### Browser UI

```bash
adk web
```

Open **http://127.0.0.1:8000** and select `track_lead_agent` from the top-left
dropdown — it won't respond until you do. `Ctrl+C` to stop. Use `--port 8765` if
8000 is taken.

### Terminal

```bash
adk run track_lead_agent
```

### CLI — no model, no API key, no quota

Every piece of triage and drafting logic is plain Python, so you can drive it
directly. This is the fastest way to work and it costs nothing:

```bash
python -m track_lead_agent.cli seed                    # demo cohort
python -m track_lead_agent.cli triage                  # ranked outreach list
python -m track_lead_agent.cli triage --tier RED
python -m track_lead_agent.cli triage --json           # for scripting
python -m track_lead_agent.cli drafts --limit 3        # ready-to-send messages
python -m track_lead_agent.cli draft mekdes@example.com
python -m track_lead_agent.cli draft mekdes@example.com --template one_on_one_invite
python -m track_lead_agent.cli templates               # what's available
python -m track_lead_agent.cli import FILE --kind scholars|submissions
```

### End-to-end check

```bash
python e2e_check.py
```

Drives the real agent through four turns — triage, draft, record a reply,
cohort report — and reports which tools it chose. Paces itself around free-tier
rate limits. Use this after changing the instructions or tools.

---

## Daily workflow

Things to actually type at the agent:

**Triage**
- "Who do I need to reach out to this week?"
- "Give me just the RED tier."
- "Which scholars have reported blockers I haven't resolved?"
- "How's the cohort doing overall? I need numbers for the program manager."

**Recording what people tell you**
- "Kwame finally replied. He's at 30%, lost his laptop, using a library PC now."
- "Liya booked her exam for September 3rd."
- "Just sent Kwame the re-engagement email." → logs it, keeps ghost detection honest

**Drafting**
- "Draft messages for everyone in AMBER."
- "Write Liya something about her voucher deadline, but warmer — she gets anxious."
- "Draft the weekly cohort broadcast for Week 9."
- "Tomas has ignored everything. Draft the escalation to the program manager."

**One person**
- "Give me the full picture on Mekdes before my 1:1."
- "Has Kwame ever actually responded to me?"

**Admin**
- "Add a scholar: Hanan Ahmed, hanan@example.com, cohort 2026-Q3, enrolled June 24."
- "Reassign Tomas to me."
- "How is the load split between me and Amina?"

> **Check the signature before you send.** Drafts are signed by the scholar's
> assigned `lead_id`, not by whoever is typing. If a scholar belongs to a
> co-lead, their draft will be signed by that co-lead.

---

## How triage works

Each scholar gets a 0–100 score from additive signals. It is deterministic — the
same data always produces the same ranking — and every score arrives with the
reasons that produced it, so you can defend it in a program review.

| Signal | Points |
|---|---|
| No check-in for 21+ / 14+ / 10+ / 7+ days | 35 / 26 / 16 / 8 |
| Never checked in (42+ / 28+ / 10+ days enrolled) | 70 / 55 / 32 |
| Behind pace by 30+ / 20+ / 10+ points | 42 / 30 / 12 |
| Reported a blocker | 15 |
| Confidence ≤ 2 of 5 | 12 |
| Under 2 study hours last week | 8 |
| Exam unbooked, voucher due in ≤7 / ≤21 / ≤45 days | 60 / 32 / 10 |
| 2+ unanswered outreach attempts | 20 |
| Marked inactive / at risk | 40 / 15 |

**Tiers:** RED ≥ 60 · AMBER ≥ 30 · WATCH ≥ 10 · GREEN below that.

**Pace** is straight-line against `GCLP_PROGRAM_WEEKS`: at week 8 of 12 you're
expected to be ~67% through. This requires `enrolled_on` — without it, pace
scoring is skipped entirely for that scholar.

**Ghosting** needs both 2+ unanswered messages *and* 14+ days of silence.
Recording a check-in clears it automatically. Call `log_outreach` after you send
something so the streak stays accurate — and only log what you actually sent, or
the ladder drifts and people escalate for ignoring messages that never arrived.

Scholars marked `completed` or `withdrawn` are excluded from ranking.

---

## Message templates

Templates live in **`data/templates.yaml`**. Each triage outcome maps to one,
most specific situation first:

| Situation | Template |
|---|---|
| Ghosting or inactive | `reengage_ghost` |
| Never started | `onboarding_nudge` |
| Voucher deadline imminent | `exam_deadline_nudge` |
| Named a blocker | `blocker_support` |
| RED tier | `one_on_one_invite` |
| Low confidence, on pace | `encouragement` |
| AMBER tier | `gentle_nudge` |
| Doing well, has a win | `celebrate_milestone` |
| Routine | `checkin_request` |
| Whole cohort | `cohort_broadcast` |
| Outreach ladder exhausted | `escalation_to_pm` |

> ### ⚠️ The shipped templates are placeholders
>
> They were written to make the agent runnable end to end, **not** taken from
> any official handbook. Replace the `subject` and `body` text with your
> program's real wording.
>
> **Keep the `key:` names** — triage maps to them by key. Nothing else changes.

Set your defaults at the top of the file:

```yaml
defaults:
  lead_name: "Your Name"
  office_hours_link: "https://calendar.app.google/..."
  checkin_form_link: "https://forms.gle/..."
  community_link: "https://slack.com/..."
```

### Merge fields

```
{first_name} {name} {lead_name} {track} {cohort} {program}
{week} {course_pct} {expected_pct} {pace_gap} {days_silent}
{labs_completed} {skill_badges} {blockers} {wins}
{exam_deadline} {days_to_exam}
{office_hours_link} {checkin_form_link} {community_link}
```

Unknown or missing fields render as `—` rather than crashing, so a
partially-filled roster still produces a sendable draft.

After editing, verify nothing broke:

```bash
python -m pytest tests/test_templates.py -q   # catches unfilled placeholders
python -m track_lead_agent.cli drafts --limit 2
```

---

## Running it for real

Things that matter once this stops being a demo.

### Back up your roster

`data/roster.json` is the only state. It's gitignored, so **it is not backed up
by pushing to GitHub.** Copy it somewhere:

```bash
cp data/roster.json ~/Dropbox/gclp-backups/roster-$(date +%F).json
```

Or point `GCLP_DATA_DIR` at a synced folder so it backs up continuously:

```bash
GCLP_DATA_DIR=~/Dropbox/gclp-data
```

It's plain JSON — readable and repairable in any editor if something goes wrong.

### Sharing with co-leads

Each lead runs their own copy with their own `.env`. To split a shared roster by
owner, set `lead_id` per scholar and filter:

```bash
python -m track_lead_agent.cli triage   # then ask the agent to filter by lead
```

There's no multi-user server mode and no locking — two people writing the same
`roster.json` over a synced folder will clobber each other. Keep one writer per
file.

### Chat history

`adk web` keeps conversation history in memory only; it resets when you restart
the server. **This does not affect your data** — scholars, check-ins, and
outreach logs all persist in `roster.json`. Only the chat transcript is lost.

### Multiple cohorts

Use `--cohort` on the CLI and mention the cohort to the agent. Or run fully
separate instances with different `GCLP_DATA_DIR` values.

### Scale

Everything loads the whole roster into memory on each call. That's fine into the
low thousands of scholars. Past that, move to a database.

---

## Project layout

```
track_lead_agent/
  agent.py       root_agent — instructions and tool wiring
  tools.py       the 13 ADK function tools
  triage.py      scoring engine (pure, deterministic, tested)
  templates.py   YAML loading and merge-field rendering
  store.py       JSON persistence + idempotent CSV import
  models.py      Scholar, TrackLead, Submission, Outreach
  config.py      program shape, weights, thresholds
  cli.py         model-free access to all of the above
  seed.py        demo cohort covering every triage path
data/
  templates.yaml      <- replace with your real wording
  roster.json         <- your data (gitignored, not backed up by git)
  *.sample.csv        import format examples (fictional names)
tests/                17 tests
e2e_check.py          live 4-turn agent smoke test
```

### The 13 tools

`triage_cohort` · `cohort_report` · `list_scholars` · `get_scholar` ·
`list_track_leads` · `record_progress` · `log_outreach` · `upsert_scholar` ·
`add_track_lead` · `import_roster_csv` · `list_message_templates` ·
`draft_message` · `draft_outreach_batch`

---

## Tests

```bash
python -m pytest tests/ -q
```

`test_triage.py` pins the scoring calibration — the weights are a product
decision, so changing them should require changing a test on purpose.
`test_templates.py` verifies every shipped template renders with no unfilled
merge fields, which is what catches a typo after you paste in new wording.

---

## Troubleshooting

**`429 RESOURCE_EXHAUSTED`**
Read which quota the message names. `PerMinute` clears in about a minute.
`PerDay` means you're done until reset — switch `GCLP_MODEL`, or enable billing.
See [Model choice and quota](#model-choice-and-quota).

**Agent doesn't appear in the `adk web` dropdown**
You launched from the wrong directory. `adk` scans subfolders of wherever you
run it, so run from the project root — the folder containing `track_lead_agent/`.

**`Missing key inputs argument` / auth errors**
`.env` isn't being read. It must be in the directory you launch `adk` from.
Confirm with `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(bool(os.environ.get('GOOGLE_API_KEY')))"`.

**`404 NOT_FOUND` on the model**
That model isn't available to your key. List what is — see
[Model choice and quota](#model-choice-and-quota).

**"Roster is empty"**
Run `python -m track_lead_agent.cli seed`, or import your real data.

**Everyone shows GREEN / no pace warnings**
Your scholars have no `enrolled_on` date, so pace can't be computed. Add it to
your roster CSV and re-import.

**Nobody is ever flagged as a ghost**
Ghost detection needs outreach to be logged. Tell the agent after you send, or
call `log_outreach`.

**A draft is signed by the wrong person**
The signature follows the scholar's `lead_id`. Reassign them, or set
`defaults.lead_name` in `templates.yaml`.

---

## Privacy and security

**This repo is public. Your scholar data is not.**

- `data/roster.json` — real names, emails, personal notes — is gitignored.
- `.env` is gitignored. `.env.example` never contains a real key.
- All names in the sample CSVs and `seed.py` are fictional.

Before every push:

```bash
git status --porcelain                       # nothing unexpected staged?
git diff --cached | grep -iE "AIza|AQ\.|api[_-]?key"
```

If you ever commit a key, **rotate it** at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Removing the
commit is not enough — assume anything pushed was scraped within minutes.

If you replace the placeholder templates with internal program material, check
that your organisation is happy for that wording to be public. If not, make the
repo private, or keep `templates.yaml` local via `.gitignore`.

---

## Known gaps

Honest list of what this does **not** do:

- **No cohort rituals.** Pulse checks, ice breakers, office-hours scheduling and
  similar recurring track-lead tasks are not modelled. Only individual progress
  triage and outreach.
- **No sending.** Deliberate. It drafts; you send. It cannot see replies either,
  which is why `log_outreach` is manual.
- **Templates are placeholders**, as described above.
- **Straight-line pace model.** Real programs are front- or back-loaded. If
  yours is, the pace signal will be systematically off — adjust the weights in
  `config.py`.
- **Single writer.** No locking or multi-user server mode.

---

## Licence

No licence file yet — add one before sharing this widely. Without it, default
copyright applies and others technically cannot reuse it.
