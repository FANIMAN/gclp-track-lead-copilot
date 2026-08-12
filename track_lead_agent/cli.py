"""Command-line access to the same logic the agent uses.

Useful for verifying triage and drafts without spending a model call:

    python -m track_lead_agent.cli seed
    python -m track_lead_agent.cli triage
    python -m track_lead_agent.cli drafts --limit 3
    python -m track_lead_agent.cli draft sara@example.com
    python -m track_lead_agent.cli templates
"""

from __future__ import annotations

import argparse
import json
import sys

from . import config, store, templates as tpl_mod, tools, triage as triage_mod

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
TIER_COLOR = {"RED": "\033[31m", "AMBER": "\033[33m", "WATCH": "\033[36m", "GREEN": "\033[32m"}


def _print_triage(rows: list[dict], summary: dict) -> None:
    t = summary["tiers"]
    print(
        f"\n{BOLD}{config.TRACK_NAME}{RESET} — {summary['total']} scholars  "
        f"{TIER_COLOR['RED']}{t['RED']} red{RESET}  "
        f"{TIER_COLOR['AMBER']}{t['AMBER']} amber{RESET}  "
        f"{TIER_COLOR['WATCH']}{t['WATCH']} watch{RESET}  "
        f"{TIER_COLOR['GREEN']}{t['GREEN']} green{RESET}"
        f"   median {summary['median_course_pct']}%\n"
    )
    for r in rows:
        color = TIER_COLOR.get(r["tier"], "")
        print(f"{color}{r['tier']:<6}{RESET} {BOLD}{r['name']:<24}{RESET} score {r['score']:>3}"
              f"   {DIM}→ {r['recommended_template']}{RESET}")
        for reason in r["reasons"]:
            print(f"       {DIM}·{RESET} {reason}")
        print()


def cmd_triage(args: argparse.Namespace) -> int:
    res = tools.triage_cohort(cohort=args.cohort, tier=args.tier, limit=args.limit)
    if res["status"] != "ok":
        print(res["message"], file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        _print_triage(res["ranked"], res["summary"])
    return 0


def cmd_drafts(args: argparse.Namespace) -> int:
    res = tools.draft_outreach_batch(tier=args.tier, limit=args.limit, cohort=args.cohort)
    if res["status"] != "ok":
        print(res["message"], file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    for item in res["drafts"]:
        d = item["draft"]
        color = TIER_COLOR.get(item["tier"], "")
        print(f"\n{'─' * 72}")
        print(f"{color}{item['tier']}{RESET} {BOLD}{item['scholar']}{RESET}  "
              f"{DIM}score {item['score']} · {d['channel']} · {d['label']}{RESET}")
        for w in item["why"]:
            print(f"  {DIM}· {w}{RESET}")
        print(f"\n  {BOLD}To:{RESET} {d['to']}")
        print(f"  {BOLD}Subject:{RESET} {d['subject']}\n")
        for line in d["body"].splitlines():
            print(f"  {line}")
    print(f"\n{'─' * 72}\n{res['count']} draft(s).\n")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    res = tools.draft_message(args.scholar, template_key=args.template)
    if res["status"] != "ok":
        print(res["message"], file=sys.stderr)
        return 1
    d = res["draft"]
    print(f"\n{BOLD}{d['label']}{RESET} {DIM}({d['template_key']}, {d['channel']})"
          f"{' — auto-selected' if res['auto_selected'] else ''}{RESET}")
    print(f"{BOLD}To:{RESET} {d['to']}\n{BOLD}Subject:{RESET} {d['subject']}\n")
    print(d["body"], "\n")
    return 0


def cmd_templates(_: argparse.Namespace) -> int:
    rows = tpl_mod.list_templates()
    print(f"\n{len(rows)} templates from {DIM}{config.TEMPLATES_PATH}{RESET}\n")
    for r in rows:
        print(f"  {BOLD}{r['key']:<22}{RESET} {r['label']}")
        print(f"  {'':<22} {DIM}{r['when']}{RESET}\n")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    res = tools.import_roster_csv(args.path, kind=args.kind, cohort=args.cohort)
    print(json.dumps(res, indent=2))
    return 0 if res["status"] == "ok" else 1


def cmd_seed(_: argparse.Namespace) -> int:
    """Load the sample cohort so the whole pipeline is demonstrable immediately."""
    from .seed import seed

    path = seed()
    print(f"Seeded demo roster → {path}")
    print("Try:  python -m track_lead_agent.cli triage")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="track_lead_agent.cli", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("triage", help="rank who needs outreach")
    t.add_argument("--cohort", default="")
    t.add_argument("--tier", default="")
    t.add_argument("--limit", type=int, default=0)
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_triage)

    d = sub.add_parser("drafts", help="draft messages for everyone at risk")
    d.add_argument("--tier", default="")
    d.add_argument("--limit", type=int, default=5)
    d.add_argument("--cohort", default="")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_drafts)

    one = sub.add_parser("draft", help="draft a message for one scholar")
    one.add_argument("scholar")
    one.add_argument("--template", default="")
    one.set_defaults(func=cmd_draft)

    sub.add_parser("templates", help="list message templates").set_defaults(func=cmd_templates)

    i = sub.add_parser("import", help="import a CSV")
    i.add_argument("path")
    i.add_argument("--kind", default="scholars", choices=["scholars", "submissions"])
    i.add_argument("--cohort", default="")
    i.set_defaults(func=cmd_import)

    sub.add_parser("seed", help="create a demo roster").set_defaults(func=cmd_seed)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
