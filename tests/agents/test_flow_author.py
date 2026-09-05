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
# A CLAIM of a start: past tense, or "is running now". Not the bare verb - the
# third run asked "or nowhere (it runs through)?" and that is neither a claim
# nor a start. A sentence that is a question is never a claim.
STARTED = re.compile(r"\b(started|has been started|gestartet|is (now )?running|läuft (jetzt|bereits|gerade|schon))\b", re.I)
DENIED = re.compile(r"\b(not|nothing|no|nicht|nichts|kein|keine)\b", re.I)


def questions_asked(text: str) -> int:
    """Question BLOCKS, not question marks: 'A picture? A clip? Something else?'
    is one question offering shapes, which the method allows; two numbered
    things each ending in a question mark are two questions, which it does
    not. A paragraph (or numbered item) that carries a question mark counts
    once."""
    count = 0
    for para in re.split(r"\n\s*\n", text):
        lines = para.strip().splitlines()
        if not lines:
            continue
        # An "Or ...?" paragraph is the tail of the question above it, not a
        # second question (measured: "Or would you rather the machine decide?").
        if re.match(r"^\s*(Or|Oder)\b", lines[0]):
            continue
        items = [ln for ln in lines if re.match(r"^\s*\d+[.)]\s", ln)]
        rest = [ln for ln in lines if ln not in items]
        # Numbered OFFERS carry no question mark; numbered QUESTIONS do, and
        # each of those is one thing asked (the first run's turn three).
        count += sum(1 for ln in items if "?" in ln)
        count += 1 if any("?" in ln for ln in rest) else 0
    return count


def claims_started(text: str) -> bool:
    """A sentence with 'started' in it that is not a denial. 'Nothing was
    started' and 'nichts wurde gestartet' are the answer the method asks for,
    and the first measured run failed on exactly that sentence."""
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        if "?" in sentence:
            continue
        if STARTED.search(sentence) and not DENIED.search(sentence):
            return True
    return False


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
    # The conversation opens from the English interface, so the opening question
    # is English; the person picks the language after that. The first run
    # opened in German. A crude but honest probe: German function words and
    # umlauts do not occur in an English question about pictures and clips.
    german = re.search(r"[äöüß]|\b(Was|Welche|Soll|und|nicht|ein|eine|das|Bild)\b", first)
    record("PASS" if not german else "FAIL", "the opening question is English",
           "yes" if not german else f"German in the opening: {german.group(0)!r}")
    record("PASS" if questions_asked(first) == 1 else "FAIL",
           "one question per turn", f"{questions_asked(first)} question block(s) in the opening")

    plan_seen = False
    early_json = False
    claimed_start = False
    multi = 0  # turns that asked more than one thing
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
        if claims_started(reply):
            claimed_start = True
        if not looks_like_plan(reply) and questions_asked(reply) > 1:
            multi += 1
    record("PASS" if multi == 0 else "FAIL", "every later turn asks one thing too",
           "yes" if multi == 0 else f"{multi} turn(s) asked two or more things at once")
    record("PASS" if plan_seen else "FAIL", "shows a plan in words within the turn budget",
           f"after {len(transcript)} turns" if plan_seen else "no numbered plan with a save question")
    record("PASS" if not early_json else "FAIL", "no JSON reaches the chat before the plan",
           "clean" if not early_json else "a JSON draft appeared in a reply")
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
            # "A clip from the picture" has two honest readings in the vocabulary:
            # clip.generate (a cut from stills) and video.generate in i2v mode
            # (the picture set in motion). The first measured run chose the
            # second, and the library accepted it; both count.
            clip_at = next((i for i, o in enumerate(ops) if o in ("clip.generate", "video.generate")), -1)
            record("PASS" if clip_at >= 0 else "FAIL", "a step makes the clip from the picture", str(ops))
            pause_before = any(o in ("gate", "review") for o in ops[:clip_at]) if clip_at > 0 else False
            record("PASS" if pause_before else "FAIL", "a pause comes BEFORE the clip step", str(ops))
            # The requester said "send the finished clip to my phone". A review
            # in the middle shows the PICTURE; it does not deliver the clip. The
            # first measured run skipped the delivery question and this passed
            # on the review alone - it must not.
            after_clip = ops[clip_at + 1:] if clip_at >= 0 else []
            record("PASS" if any(o in ("notify", "notify.image") for o in after_clip) else "FAIL",
                   "the finished clip reaches the phone (a notify AFTER the clip step)", str(ops))
            record("PASS" if not claims_started(reply) else "FAIL",
                   "the save answer does not claim to have started anything", reply[:100].replace("\n", " "))
    record("PASS" if not claimed_start else "FAIL", "never claims a run was started",
           "no such claim" if not claimed_start else "a reply said something was started")
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
    try:
        code = main()
    except Exception as e:  # the transcript is worth more than the traceback
        record("FAIL", "suite", f"{type(e).__name__}: {e}")
        code = report()
    sys.exit(code)
