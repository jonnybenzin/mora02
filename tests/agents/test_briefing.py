#!/usr/bin/env python3
"""Can a local model hold a briefing conversation, and does it leave gaps as gaps?

A scripted requester answers the catalogue while this suite watches for the four
things that decide whether the agent is usable:

  * it opens by asking WHICH kind of briefing — the one turn that is fixed
  * it asks ONE thing at a time, rather than pasting a questionnaire
  * details given in turn three survive into the document — the thread holds
  * a question answered with "I don't know" comes out as `open`, NOT as
    something plausible

The last one is the point. Two planted details and one planted non-answer make
the scoring a string comparison instead of a judgement, the same trick the tool
bench uses: an invented stopping criterion reads exactly like a real one, and
whoever executes the brief would act on it.

This spends real turns on the local model (a dozen or so, a couple of minutes)
and is therefore behind --agents in run-all.sh rather than in the default pass.

Usage:
    python3 tests/agents/test_briefing.py [--show]     (--show prints the transcript)

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
AGENT = os.environ.get("MORA02_TEST_AGENT", "briefing")
CONV = f"brieftest-{int(time.time())}"
MAX_TURNS = 20

SHOW = "--show" in sys.argv

# Planted details. None of them can be guessed from the catalogue, so finding
# them in the finished document proves the thread carried them.
ANGLES = "Bosch, Shimano, TQ"
SOURCE_RULE = "no manufacturer figures"
REGION = "Austria"

# The planted NON-answer. Question 11 of the research catalogue asks how you
# know the question is answered. This requester does not know — and the document
# must say so rather than inventing a criterion.
DONT_KNOW = "I don't know"

# Answers in the order the catalogue asks. The agent may skip or merge
# questions, so these are fed in sequence rather than matched to a question:
# a briefing conversation that needs a lockstep script is not a conversation.
ANSWERS = [
    "A research brief.",
    "Which mid-drive motors for cargo bikes last beyond 20,000 km.",
    "I want to buy one and I don't know which drive.",
    f"I know the market roughly. Angles: {ANGLES}.",
    f"Independent tests and workshop reports. {SOURCE_RULE}.",
    "Nothing older than three years.",
    f"{REGION}, German and English.",
    "Thorough, not just an overview.",
    "A comparison table with mileage, repairability and price.",
    "Batteries and frames are not part of it.",
    DONT_KNOW,
    "No, that was all.",
    "Yes, please write the brief now.",
]

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))
    mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "WARN": " warn "}[verdict]
    print(f"[{mark}] {subject}: {detail}")


def ask(message: str) -> str:
    req = urllib.request.Request(
        f"{RUNNER}/agent/{AGENT}/message",
        data=json.dumps({"message": message, "conversation": CONV}).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode()).get("text") or ""
    except urllib.error.HTTPError as e:
        return f"<<HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}>>"


def question_count(text: str) -> int:
    """Roughly: how many things is this turn asking for at once?"""
    return text.count("?")


def main() -> int:
    transcript: list[tuple[str, str]] = []
    doc = ""

    print(f"conversation {CONV}, agent {AGENT}\n")
    for i, answer in enumerate(ANSWERS):
        if i == 0:
            reply = ask("/briefing")  # bare invocation: the opening move is its own
        else:
            reply = ask(answer)
        transcript.append((answer if i else "(start)", reply))
        if SHOW:
            print(f"--- turn {i}\n  me:    {answer if i else '(start)'}\n"
                  f"  agent: {reply[:600]}\n")
        if reply.startswith("<<HTTP"):
            record("FAIL", "turn", reply[:180])
            return report()
        # The document is recognisable and ends the conversation early if the
        # agent gets there before the script runs out.
        if "Recherche-Briefing" in reply and "## Die Frage" in reply:
            doc = reply
            break
    else:
        doc = transcript[-1][1]

    # --- 1. the opening move -----------------------------------------------
    first = transcript[0][1].lower()
    if ("research" in first and "creative" in first) or "kind of brief" in first:
        record("PASS", "opening", "asked which kind of briefing")
    else:
        record("FAIL", "opening",
               f"did not offer the choice: {transcript[0][1][:140]}")

    # --- 2. one thing at a time --------------------------------------------
    walls = [t for _, t in transcript[:-1] if question_count(t) > 3]
    if walls:
        record("FAIL", "one at a time",
               f"{len(walls)} turn(s) asked more than three things at once")
    else:
        record("PASS", "one at a time", "no turn pasted a questionnaire")

    # --- 3. did the thread hold? -------------------------------------------
    if not doc:
        record("FAIL", "document", "no briefing was produced within the turn budget")
        return report()
    record("PASS", "document", f"produced, {len(doc)} chars")

    for label, needle in (("angles", "TQ"), ("source rule", "Herstellerangaben"),
                          ("region", REGION)):
        if needle.lower() in doc.lower():
            record("PASS", f"kept {label}", f"{needle!r} survived into the document")
        else:
            record("FAIL", f"kept {label}",
                   f"{needle!r} was given but is not in the document")

    # --- 4. THE one that matters: is the gap still a gap? ------------------
    stop = re.search(r"##\s*Stopping rule\s*\n(.{0,220})", doc, re.S)
    if not stop:
        record("FAIL", "gap kept open", "no 'Stopping rule' section in the document")
    else:
        body = stop.group(1).strip().lower()
        if "open" in body or DONT_KNOW.lower() in body:
            record("PASS", "gap kept open",
                   "the unanswered stopping rule is marked open, not invented")
        else:
            # An invented criterion reads exactly like a real one, and whoever
            # runs the brief would act on it.
            record("FAIL", "gap kept open",
                   f"INVENTED a stopping criterion: {stop.group(1).strip()[:120]}")

    if "## Open" in doc:
        record("PASS", "gap list", "the document carries its own list of gaps")
    else:
        record("WARN", "gap list", "no 'Offen' section — the template asks for one")

    if SHOW:
        print("\n" + "=" * 60 + "\n" + doc + "\n" + "=" * 60)
    return report()


def report() -> int:
    print()
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"{len(results) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warned, {len(fails)} failed")
    for _, subject, detail in fails:
        print(f"  FAILED  {subject}: {detail}")
    print("\nRun with --show to read the whole conversation.")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as e:
        print(f"cannot reach script-runner at {RUNNER}: {e}", file=sys.stderr)
        sys.exit(2)
