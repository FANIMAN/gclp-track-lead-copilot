"""End-to-end smoke test: drives the real agent through a full track-lead workflow.

    python e2e_check.py

Makes real model calls. Each turn prints the tools the agent chose and its reply,
so you can see whether it is reasoning over the roster or improvising.
"""

from __future__ import annotations

import asyncio
import logging
import warnings

from dotenv import load_dotenv

load_dotenv()

# We retry 429s ourselves, so ADK's own traceback for them is just noise.
logging.getLogger("google.adk").setLevel(logging.CRITICAL)
logging.getLogger("google_genai").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from track_lead_agent.agent import root_agent  # noqa: E402
from track_lead_agent.seed import seed  # noqa: E402

BOLD, DIM, CYAN, GREEN, RED, RESET = (
    "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[31m", "\033[0m",
)

TURNS = [
    "Who do I need to reach out to this week? Give me the top 3 with reasons.",
    "Draft the message for Kwame.",
    "Mekdes just replied - she's at 52% now, still stuck on the IAM lab but she "
    "sounded more positive. Record that and tell me if her risk changed.",
    "Give me the cohort numbers for my program manager.",
]


async def main() -> int:
    seed()
    print(f"{DIM}Seeded demo cohort.{RESET}")

    runner = InMemoryRunner(agent=root_agent, app_name="track_lead_e2e")
    session = await runner.session_service.create_session(
        app_name="track_lead_e2e", user_id="nebiyu"
    )

    failures = 0
    for i, prompt in enumerate(TURNS, 1):
        print(f"\n{'=' * 74}\n{BOLD}[{i}] YOU:{RESET} {prompt}\n{'=' * 74}")
        tools_used: list[str] = []
        reply: list[str] = []

        # The AI Studio free tier allows 5 requests/minute and one turn costs
        # roughly two, so back off and retry rather than failing the check.
        for attempt in range(4):
            tools_used, reply = [], []
            try:
                async for event in runner.run_async(
                    user_id="nebiyu",
                    session_id=session.id,
                    new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
                ):
                    for part in (event.content.parts if event.content else []) or []:
                        if getattr(part, "function_call", None):
                            tools_used.append(part.function_call.name)
                        if getattr(part, "function_response", None):
                            resp = part.function_response.response or {}
                            if resp.get("status") == "error":
                                print(f"  {RED}tool error: {resp.get('message')}{RESET}")
                        if getattr(part, "text", None) and event.is_final_response():
                            reply.append(part.text)
                break
            except Exception as exc:  # noqa: BLE001
                if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
                    wait = 25 * (attempt + 1)
                    print(f"  {DIM}rate limited, waiting {wait}s...{RESET}")
                    await asyncio.sleep(wait)
                    continue
                print(f"{RED}TURN FAILED: {type(exc).__name__}: {exc}{RESET}")
                failures += 1
                break
        else:
            print(f"{RED}TURN FAILED: still rate limited after 4 attempts{RESET}")
            failures += 1
            continue

        print(f"{CYAN}tools:{RESET} {' → '.join(tools_used) if tools_used else DIM + 'none' + RESET}")
        if not tools_used:
            print(f"  {RED}warning: answered without consulting the roster{RESET}")
            failures += 1
        print(f"\n{''.join(reply).strip()}")

        if i < len(TURNS):
            await asyncio.sleep(30)  # stay under the free-tier requests/minute cap

    print(f"\n{'=' * 74}")
    if failures:
        print(f"{RED}{BOLD}{failures} problem(s).{RESET}")
    else:
        print(f"{GREEN}{BOLD}All {len(TURNS)} turns passed.{RESET}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
