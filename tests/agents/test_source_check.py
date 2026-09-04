#!/usr/bin/env python3
"""Step 4 of the research method, as machinery rather than as a paragraph.

WHY THIS EXISTS. Of the five moves in the research skill, four had a tool and
one had only prose. Notes had `note`, re-reading had `notes_review`, sources had
`web_read` -- and each leaves a trace beside the answer. "Check the load-bearing
facts at their source" had none, so nothing about it was checkable, it never
appeared in a report, and nobody noticed for weeks.

What made it visible was a hand check, not a model. On 2026-09-02 the question
the agent had been measured on all the previous day was answered by hand at the
sources: the recommended machine was 24,6 cm wide, and a machine meeting every
one of the same conditions -- automatic milk, under 500 EUR -- was 24,0 cm. Both
agent runs had already NAMED that gap in their own notes ("genaue Tiefe/Breite
fuer die DeLonghi-Modelle nicht aus den Quellen bestaetigt") and walked past it.
Neither searching nor judging failed. The closing step did, silently.

So the leading question of the canon -- not "does it work" but "and if it goes
wrong, will I see it?" -- has three answers here, one per check below:

  * a check that was only asserted        -> refused against the fetch record
  * a page that never loaded confirming   -> refused; only "not findable" stands
  * a gap carried into an answer          -> counted in the envelope regardless
                                             of what the agent wrote

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\
        python3 tests/agents/test_source_check.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "lib" / "mora02_core" / "src", ROOT / "apps" / "script-runner" / "app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import mcp_tools as m  # noqa: E402

FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        FAILED.append(label)


def call(name: str, args: dict) -> dict:
    return asyncio.run(m._call(name, args))


def test_detection() -> None:
    """The open points are computed from what the agent wrote, not asked for.

    Deliberately crude: its job is to raise candidates. The cases below are the
    ones that matter, and the second of them is why the pattern is not a simple
    adjacency -- German puts the negation four words away from the participle,
    and the first real note this was tried on slipped straight through.
    """
    print("\ndetection")
    # These stay in German on purpose, and are the one place in the tree that
    # does. The pattern reads both languages because a German page states its
    # restriction in German, and a case list with only English phrases would
    # leave that half of it untested. Everything a person or an agent READS is
    # English; this is neither, it is input.
    cases = [
        ("Preis Stand Juni 2026", False),
        ("nicht aus den Quellen bestaetigt", True),
        ("nicht aus den Quellen bestätigt", True),
        ("Preis nicht explizit genannt für Platz 1", True),
        ("keine Angabe zur Breite", True),
        ("dimensions not confirmed by the maker", True),
        ("unclear which variant", True),
        ("widersprüchlich zwischen Händlern", True),
        ("gilt nur für die EU-Version", False),
        ("Stand Dezember 2025, kann variieren", False),
    ]
    wrong = [(t, w) for t, w in cases if (m._OPEN_RX.search(t) is not None) != w]
    check("restrictions classified", not wrong,
          f"{len(cases) - len(wrong)}/{len(cases)}")
    for t, w in wrong:
        print(f"        missed {t!r} (expected open={w})")

    notes = [
        {"claim": "a", "source": "https://otto.de/x", "restriction": "Stand Juni 2026"},
        {"claim": "b", "source": "https://chip.de/y",
         "restriction": "nicht aus den Quellen bestaetigt"},
        {"claim": "c", "source": "https://coffeeness.de/z",
         "restriction": "unclear which variant"},
    ]
    check("open_notes picks only the open ones", len(m.open_notes(notes)) == 2)
    many = [{"claim": str(i), "source": "u", "restriction": "unklar"} for i in range(9)]
    check("open_notes is capped", len(m.open_notes(many)) == 3,
          "long chains were measured ending with no answer at all")


def test_provenance() -> None:
    """A check is performed, not asserted."""
    print("\nprovenance")
    m.end_turn()
    m.begin_turn({})
    url = "https://geizhals.de/evo"

    r = call("verify", {"checks": [{"claim": "Breite 24,0 cm", "source": url,
                                    "result": "confirmed", "detail": "240mm"}]})
    check("unfetched source refused", r.get("checked") == 0 and bool(r.get("rejected")))

    m._remember("read", url, ok=True)
    r = call("verify", {"checks": [{"claim": "Breite 24,0 cm",
                                    "source": "https://www.geizhals.de/evo/",
                                    "result": "confirmed",
                                    "detail": "240x360x440mm (BxHxT)"}]})
    check("accepted after a real fetch", r.get("checked") == 1,
          "www and trailing slash tolerated -- a check must not fail on cosmetics")

    r = call("verify", {"checks": [{"claim": "x", "source": url,
                                    "result": "vielleicht"}]})
    check("invented result refused", r.get("checked") == 0)


def test_dead_page() -> None:
    """A page that would not load is still a real outcome -- but only one of them.

    Measured by hand on 2026-09-02: four of ten fetches were refused outright
    (403), and the maker's own page -- the canonical place to verify a
    specification -- served nothing but ``VersuniB2CApp``, assembling itself in
    a browser. If "not findable at the source" were blocked for such a page, the
    honest outcome would be the one the machinery forbids.
    """
    print("\ndead pages")
    m.end_turn()
    m.begin_turn({})
    dead = "https://www.home-appliances.philips/de/de/p/EP2333_40"
    m._remember("read", dead, ok=False)

    r = call("verify", {"checks": [{"claim": "Breite laut Hersteller", "source": dead,
                                    "result": "not_found",
                                    "detail": "liefert nur VersuniB2CApp"}]})
    check("'not_found' stands for a page that failed", r.get("checked") == 1)

    r = call("verify", {"checks": [{"claim": "Breite laut Hersteller", "source": dead,
                                    "result": "confirmed", "detail": "24,6 cm"}]})
    check("the same page may NOT confirm anything", r.get("checked") == 0)


def test_review_reports_open() -> None:
    """notes_review states the open points; it does not wait to be asked."""
    print("\nreview")
    m.end_turn()
    t0 = m.begin_turn({})
    # Through the tool, not into the deque: a test that pokes the storage shape
    # breaks on the next change to it and proves nothing about the tool.
    call("note", {"notes": [
        {"claim": "a", "source": "u", "restriction": "Stand Juni 2026"},
        {"claim": "b", "source": "u", "restriction": "nicht bestaetigt"},
        {"claim": "c", "source": "u", "restriction": "keine Angabe zur Breite"}]})

    r = call("notes_review", {})
    check("open points returned", len(r.get("open") or []) == 2)
    check("both endings named in the hint",
          "verify" in r.get("hint", "") and "open" in r.get("hint", "").lower(),
          "checking and declaring are both complete outcomes")
    check("review is recorded", m.reviewed_this_turn())

    unchecked = [o for o in m.open_notes(m.notes_since(t0))
                 if o["claim"][:60] not in {c["claim"][:60] for c in m.checks_since(t0)}]
    check("a carried gap is countable without the agent's help", len(unchecked) == 2,
          "this is what the answer envelope reports")


def test_single_source() -> None:
    """Figures resting on one host -- and the negative result that shaped this.

    The detector was proposed to catch the Blender turn's one real error. Run
    against that turn's six actual notes it flagged all six, because a turn that
    reads the vendor's own pages -- what step 4 asks for -- is single-sourced by
    construction. And the error was a MISREADING, not a shortage of sources.
    Both cases below are kept so that neither conclusion has to be rediscovered.
    """
    print("\nsingle source")
    REQ = "https://www.blender.org/download/requirements/"
    blender = [
        ("https://www.blender.org/download/",
         "Blender 5.2.1 LTS erschien am 25. August 2026", "Stand 25.08.2026"),
        ("https://developer.blender.org/docs/release_notes/",
         "Blender 5.2 LTS bietet node-basierende Physik", "Versionsbeschreibung"),
        (REQ, "Windows-Mindestanforderung GPU: 2 GB VRAM, OpenGL 4.3, Vulkan 1.3",
         "Gilt für Blender 5.x"),
        (REQ, "Linux-Mindestanforderung GPU: 2 GB VRAM, OpenGL 4.3, Vulkan 1.3",
         "glibc 2.28 nötig"),
        (REQ, "macOS erfordert Apple Silicon und macOS 13 (Ventura)",
         "Blender 5.0+; Intel-Macs seit 4.5 LTS nicht mehr unterstützt"),
        (REQ, "Empfohlene GPU: 8 GB VRAM", "Empfehlung, nicht Minimum"),
    ]
    r = m.single_source_notes([{"source": s, "claim": c, "restriction": x}
                               for s, c, x in blender])
    check("a one-source turn is named, not listed",
          r["one_family"] and not r["candidates"],
          f"{r['total']} figures, 0 candidates -- a list flagging everything flags nothing")

    mixed = [
        ("https://github.com/a", "ComfyUI v0.34.0 ist aktuell", ""),
        ("https://docs.comfy.org/b", "Die ComfyUI-Version v0.34.0 ist die neueste", ""),
        ("https://heise.de/c", "ComfyUI v0.34.0 wurde veroeffentlicht", ""),
        ("https://blog.example/d", "Ein Blog nennt PyTorch 2.10.0+cu130 als passend",
         "Sekundärquelle"),
    ]
    r2 = m.single_source_notes([{"source": s, "claim": c, "restriction": x}
                                for s, c, x in mixed])
    check("with several hosts the outlier is isolated",
          not r2["one_family"] and len(r2["candidates"]) == 1
          and "Blog" in r2["candidates"][0]["claim"],
          "the corroborated version is not flagged; the lone blog figure is")

    check("restrictions are read too, not only claims",
          m._FIG_RX.search("kein Wert im Text " + "Blender 5.0+ seit 4.5 LTS") is not None,
          "the figure that was wrong sat in the restriction field")


def test_notes_survive_a_follow_up() -> None:
    """A second question in the same conversation keeps the first one's notes.

    The failure this closes: notes were read through a TIME WINDOW that
    `begin_turn` restamped on every question. The gateway thread held fine, so
    the agent carried the conversation and answered the follow-up from memory of
    its own reading -- with the qualifiers gone, which is precisely the distance
    the notes exist to close. The window could not answer "what did we establish
    two questions ago" because it never knew the questions belonged together.

    Sessions must also stay apart: two conversations blurring is worse than a
    lost note, so an unknown session carries nothing rather than guessing.
    """
    print("\nfollow-up")
    from mora02_core.agents import session_key
    sess, other = session_key("recherche", "conv-42"), session_key("recherche", "conv-99")

    m.end_turn()

    m.begin_turn({}, session=sess)
    m._remember("read", "https://docs.comfy.org/req", ok=True)
    call("note", {"notes": [
        {"claim": "Python 3.13 wird empfohlen", "source": "https://docs.comfy.org/req",
         "restriction": "3.14 läuft, aber manche Custom Nodes brechen"},
        {"claim": "torch 2.7 ist die Untergrenze", "source": "https://docs.comfy.org/req",
         "restriction": "neuere ausdrücklich empfohlen"}]})
    call("verify", {"checks": [
        {"claim": "Python 3.13 empfohlen", "source": "https://docs.comfy.org/req",
         "result": "confirmed", "detail": "'Python 3.13 is very well supported'"}]})

    time.sleep(0.01)
    m.end_turn()
    m.begin_turn({}, session=sess)                      # the follow-up question
    r = call("notes_review", {})
    check("earlier notes are carried", len(r.get("earlier") or []) == 2,
          "before this, a follow-up opened an empty notebook")
    check("their restrictions come with them",
          all(n.get("restriction") for n in r.get("earlier") or []))
    check("earlier verifications are carried too",
          len(r.get("already_checked") or []) == 1,
          "a figure confirmed two questions ago is still confirmed")
    check("this turn's own notes stay separate", r["notes"] == [])

    m.end_turn()

    m.begin_turn({}, session=other)
    check("a different conversation sees nothing",
          not call("notes_review", {}).get("earlier"))

    m.end_turn()

    m.begin_turn({}, session="")
    check("no session carries nothing rather than guessing",
          not call("notes_review", {}).get("earlier"))


def test_progress_is_visible_while_running() -> None:
    """A turn says what it is doing while it is still doing it.

    Measured 2026-09-02: 53 s for a light question, 194 s for one with five
    source checks -- and in both the person watching saw a bouncing dot and
    nothing else, while the service knew second by second where it was. Every
    field here is read out of registers that already existed for the answer
    envelope; nothing new is measured.

    The phase is derived from which record moved LAST, never from anything the
    model says about itself. And `running` has to go false when the route stops
    waiting, or the endpoint reports a finished turn as live forever -- a stale
    yes being worse than no answer.
    """
    print("\nprogress")
    # The tests above leave a turn open; the registers are module-level and one
    # suite runs in one process. Stated rather than worked around, because the
    # same single set of registers is why two concurrent turns would blur.
    m.end_turn()
    check("nothing running between turns", m.turn_progress() == {"running": False})

    m.end_turn()

    m.begin_turn({}, session="s-progress")
    check("a fresh turn is thinking", m.turn_progress()["phase"] == "thinking")

    m._remember("search", "https://a/1", ok=True)
    check("searching is visible", m.turn_progress()["phase"] == "searching")

    m._remember("read", "https://docs.comfy.org/req", ok=True)
    prog = m.turn_progress()
    check("reading is visible, with the page",
          prog["phase"] == "reading pages" and prog["last_read"].endswith("/req"))

    call("note", {"notes": [{"claim": "x", "source": "https://docs.comfy.org/req",
                             "restriction": "gilt 2026"}]})
    check("noting is visible", m.turn_progress()["phase"] == "taking notes")

    call("verify", {"checks": [{"claim": "x", "source": "https://docs.comfy.org/req",
                                "result": "confirmed"}]})
    check("verifying is visible", m.turn_progress()["phase"] == "checking at the source")

    call("notes_review", {})
    prog = m.turn_progress()
    check("composing is visible", prog["phase"] == "writing the answer")
    check("budget is counted, not guessed",
          prog["notes"] == 1 and prog["checks"] == 1 and prog["pages_max"] > 0)

    time.sleep(0.25)   # idle_s is rounded to a tenth; sleep past the rounding
    check("idle time is reported", m.turn_progress()["idle_s"] > 0,
          "the gap between tool calls separates thinking from hanging")

    m.end_turn()
    check("a finished turn stops reporting itself as running",
          m.turn_progress() == {"running": False})


def test_reported_weights() -> None:
    """The answer says which weights answered, not which name was written down.

    A local agent's manifest can only carry "llama-local/current": that is the
    id configured in the gateway's provider block, and an unconfigured one makes
    the agent fail to resolve. llama-server meanwhile serves whatever GGUF is
    loaded and ignores the id. Measured 2026-09-02: manifest said qwen3-14b,
    llm-switch said qwen36-27b, the server had Qwen3.6-27B.

    The guard is the part worth testing. Looking this up must never delay or
    fail a turn, so an unreachable server yields an empty string -- which reads
    as "unknown" in the envelope rather than as a wrong name.
    """
    print("\nreported weights")
    import agents as route
    import os
    prev = os.environ.get("QWEN_URL")
    try:
        os.environ["QWEN_URL"] = "http://127.0.0.1:9"     # nothing listens there
        import importlib
        importlib.reload(route)
        check("an unreachable server yields '', not an exception",
              asyncio.run(route._loaded_weights()) == "")
    finally:
        if prev is None:
            os.environ.pop("QWEN_URL", None)
        else:
            os.environ["QWEN_URL"] = prev


def test_check_rides_on_the_note() -> None:
    """A note carrying `result` is also a source check.

    Why the tools were merged. Three local turns used the SAME four tools every
    time -- web_search, web_read, note, notes_review -- and never a fifth, with
    `verify` allowed, described, and then re-described with a concrete trigger
    ("right after a web_read...") in between. The served description was checked
    over the live MCP endpoint, so it was not a rollout that failed. It was not
    the wording either: the same prompt reached for `note` in every single turn.

    So the record was attached to the act that reliably happens rather than
    asked for as an act of its own. `verify` stays for a model that does reach
    for it -- both doors book into the same ledger, through the same provenance
    rule, which is why that rule lives in one function.
    """
    print("\nmerged check")
    m.end_turn()
    m.begin_turn({}, session="merge")
    m._remember("read", "https://github.com/penpot/penpot/releases", ok=True)
    m._remember("read", "https://github.com/penpot/penpot/security/advisories/X", ok=False)

    r = call("note", {"notes": [
        {"claim": "Penpot 2.17.2 ist aktuell, 27. August",
         "source": "https://github.com/penpot/penpot/releases",
         "restriction": "Stand 2. September", "result": "confirmed",
         "detail": "'2.17.2 Latest', '27 Aug 08:31'"},
        {"claim": "Ein Blog nennt ein anderes Datum",
         "source": "https://blog.example/x", "restriction": "Sekundärquelle",
         "result": "confirmed"},
        {"claim": "Schweregrad von GHSA-4f36",
         "source": "https://github.com/penpot/penpot/security/advisories/X",
         "restriction": "404", "result": "not_found"},
        {"claim": "Eine gewöhnliche Notiz ohne Prüfung",
         "source": "https://github.com/penpot/penpot/releases", "restriction": "keine"},
    ]})
    check("all four notes are kept", r.get("noted") == 4)
    check("two of them became checks", r.get("checked") == 2)
    check("a check on an unfetched page is refused",
          len(r.get("check_rejected") or []) == 1,
          "the NOTE still stands -- only the check is refused")
    check("a page that would not load may still say 'not findable'",
          any(c["result"] == "not_found" for c in m.checks_since(m._TURN_T0)))

    rv = call("notes_review", {})
    check("review sees them as checks", rv.get("checked") == 2)

    r2 = call("verify", {"checks": [
        {"claim": "nachtraeglich", "source": "https://github.com/penpot/penpot/releases",
         "result": "contradicted", "detail": "x"}]})
    check("verify still works on its own and books to the same ledger",
          r2.get("checked") == 1 and r2.get("total_this_turn") == 3)


if __name__ == "__main__":
    print(__doc__.split("Usage:")[0].strip().splitlines()[0])
    test_detection()
    test_provenance()
    test_dead_page()
    test_review_reports_open()
    test_single_source()
    test_notes_survive_a_follow_up()
    test_progress_is_visible_while_running()
    test_reported_weights()
    test_check_rides_on_the_note()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
    sys.exit(1 if FAILED else 0)
