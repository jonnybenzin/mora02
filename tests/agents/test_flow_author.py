#!/usr/bin/env python3
"""Can a local model turn a wish into a saved flow - and only when told to?

A scripted requester wants one thing made, answers the catalogue, and says yes
once the agent shows a plan. The suite watches for what decides whether the
agent is usable, and every check is a string comparison, not a judgement:

  * the first turn asks what should come out, and offers nothing
  * one question per turn, not a questionnaire
  * no JSON and no op names reach the chat before the plan is shown in words
  * the flow is NOT in the library before the requester says yes
  * after the yes it IS there, under the agreed name, and it holds: the
    planted subject as an argument, a picture step, a pause BEFORE the clip
    step, and a delivery to the phone - the four things that were asked for
  * the agent never claims to have started anything

This spends real turns on the local model (a dozen, a few minutes) and is
therefore behind --model in run-all.sh rather than in the default pass. The
scenario is deliberately NOT one of the skill's examples.

Usage:
    python3 tests/agents/test_flow_author.py [--show]
Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096),
MORA02_PIPELINE_SPECS_LOCAL_DIR (default /opt/mora02/pipelines/local/specs).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
AGENT = os.environ.get("MORA02_TEST_AGENT", "flow-author")
LOCAL = Path(os.environ.get("MORA02_PIPELINE_SPECS_LOCAL_DIR", "/opt/mora02/pipelines/local/specs"))
CONV = f"flowtest-{int(time.time())}"
NAME = f"probe-otter-clip-{int(time.time()) % 100000}"
SUBJECT = "an otter juggling three river stones"
MAX_TURNS = 18
SHOW = "--show" in sys.argv

# Answers in the order the catalogue asks; the agent may skip or merge, so they
# are fed in sequence rather than matched to a question.
ANSWERS = [
    "A short clip, a few seconds, with one picture in it.",
    f"Just a subject in words. For example: {SUBJECT}.",
    "First a picture from the subject, then the clip from that picture.",
    "I want to see the picture on my phone before the clip is made.",
    "Send the finished clip to my phone.",
    "The subject changes every time, everything else stays.",
    f"Call it {NAME}.",
]
YES = f"Yes, save it as {NAME}."

results: list[tuple[str, str, str]] = []
transcript: list[tuple[str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def ask(message: str) -> str:
    req = urllib.request.Request(
        f"{RUNNER}/agent/{AGENT}/message", method="POST",
        data=json.dumps({"message": message, "conversation": CONV}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode()).get("text") or ""
    except urllib.error.HTTPError as e:
        return f"<<HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}>>"


OP_NAME = re.compile(r"\b[a-z]+\.[a-z_]+\b")
CHAT_JSON = re.compile(r'"steps"\s*:|\{"[a-z.]+":\s*\{')


def looks_like_plan(text: str) -> bool:
    """A numbered list plus the question whether to save it."""
    numbered = len(re.findall(r"(?m)^\s*\d+[.)]\s", text)) >= 2
    return numbered and ("save" in text.lower() or "speicher" in text.lower())


def main() -> int:
    saved_file = LOCAL / f"{NAME}.json"
    reply = ask("Hello, I want a flow that makes something for me.")
    transcript.append(("(start)", reply))
    first = reply
    record("PASS" if "?" in first and not OP_NAME.search(first) else "FAIL",
           "opens with a question, and no op name in it", first[:120].replace("\n", " "))
    record("PASS" if first.count("?") <= 2 else "FAIL",
           "one question per turn", f"{first.count('?')} question marks")

    plan_seen = False
    early_json = False
    claimed_start = False
    answers = list(ANSWERS)
    for i in range(1, MAX_TURNS):
        if plan_seen:
            break
        if looks_like_plan(reply):
            plan_seen = True
            record("PASS" if not saved_file.exists() else "FAIL",
                   "nothing is in the library before the yes",
                   "not saved yet" if not saved_file.exists() else f"{saved_file.name} already exists")
            break
        if CHAT_JSON.search(reply):
            early_json = True
        if answers:
            msg = answers.pop(0)
        else:
            msg = "That is all I can say - please show me the plan."
        reply = ask(msg)
        transcript.append((msg, reply))
        if reply.startswith("<<HTTP"):
            record("FAIL", "turn", reply[:180])
            return report()
        if re.search(r"\b(started|running|has been started|läuft|gestartet)\b", reply, re.I):
            claimed_start = True
    record("PASS" if plan_seen else "FAIL", "shows a plan in words within the turn budget",
           f"after {len(transcript)} turns" if plan_seen else "no numbered plan with a save question")
    record("PASS" if not early_json else "FAIL", "no JSON reaches the chat before the plan")
    if plan_seen:
        reply = ask(YES)
        transcript.append((YES, reply))
        record("PASS" if saved_file.exists() else "FAIL", "after the yes the flow is in the library",
               str(saved_file) if saved_file.exists() else "not there")
        if saved_file.exists():
            spec = json.loads(saved_file.read_text(encoding="utf-8"))
            ops = [next(iter(s)) for s in spec.get("steps", []) if isinstance(s, dict)]
            record("PASS" if SUBJECT in json.dumps(spec) or '"arg"' in json.dumps(spec) else "FAIL",
                   "the subject travels as an argument (or its example as default)",
                   json.dumps(spec)[:100])
            record("PASS" if "image.generate" in ops else "FAIL", "a picture step is in", str(ops))
            clip_at = ops.index("clip.generate") if "clip.generate" in ops else -1
            pause_before = any(o in ("gate", "review") for o in ops[:clip_at]) if clip_at > 0 else False
            record("PASS" if pause_before else "FAIL", "a pause comes BEFORE the clip step", str(ops))
            record("PASS" if any(o in ("notify", "notify.image") for o in ops) or "review" in ops else "FAIL",
                   "the result reaches the phone", str(ops))
            record("PASS" if "start" not in reply.lower() or "not" in reply.lower() or "nothing" in reply.lower() else "FAIL",
                   "the save answer does not claim to have started anything", reply[:100].replace("\n", " "))
    record("PASS" if not claimed_start else "FAIL", "never claims a run was started")
    return report()


def report() -> int:
    saved_file = LOCAL / f"{NAME}.json"
    if saved_file.exists():
        try:
            saved_file.unlink()
        except OSError:
            record("FAIL", "cleanup", f"could not remove {saved_file}")
    if SHOW:
        for me, them in transcript:
            print(f"--- me:    {me}\n    agent: {them}\n")
    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed  (conversation {CONV})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
