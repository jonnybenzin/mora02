#!/usr/bin/env python3
"""Phase 6b of the test plan: does the flow builder behave in a browser?

Everything else in this suite talks to endpoints. The builder is the one part
whose defects only exist on screen - a message written into an element that the
next render replaced, a palette missing the blocks a flow cannot be built
without, an insertion mark that always appends. Four of the nine defects of
26 August lived here, and none of them could have been caught from the API side.

Playwright drives a headless Chromium against the served UI. Console errors are
collected throughout: a red line in the console is a finding even when the page
still looks right.

Usage:
    python3 tests/pipeline/test_builder_ui.py
    python3 tests/pipeline/test_builder_ui.py --headed   # watch it happen

Environment: PILOT_UI_URL (default http://127.0.0.1:8092/pilot/index.html).
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

import os

UI = os.environ.get("PILOT_UI_URL", "http://127.0.0.1:8092/pilot/index.html")

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str) -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))


def open_groups(page) -> int:
    """Open every palette group. A re-render collapses them again, so this runs
    before each palette click rather than once."""
    headers = page.query_selector_all(".flw-grp-h")
    for h in headers:
        try:
            if not h.evaluate("e => { const b = e.nextElementSibling;"
                              " return b && getComputedStyle(b).display !== 'none'; }"):
                h.click()
        except Exception:
            pass
    page.wait_for_timeout(200)
    return len(headers)


def run(page) -> None:
    page.goto(UI, wait_until="networkidle")
    page.evaluate("navigate('flows')")
    page.wait_for_selector("[data-fl-act]", timeout=15000)

    # The library view comes first; open the empty builder.
    if page.query_selector('[data-fl-act="new"]'):
        page.click('[data-fl-act="new"]')
    page.wait_for_selector("[data-fl-op]", state="attached", timeout=15000)

    # The palette groups its ops by family and starts collapsed. Opening every
    # group is part of the check: an op inside a group that never opens is an op
    # nobody can reach.
    groups = open_groups(page)
    visible = page.eval_on_selector_all(
        "[data-fl-op]", "els => els.filter(e => e.offsetParent !== null).length")
    record(groups > 0 and visible > 0, "palette groups open",
           f"{groups} groups, {visible} ops reachable after opening them")

    # --- the palette holds what a flow cannot be built without ---------------
    ops = page.eval_on_selector_all("[data-fl-op]", "els => els.map(e => e.dataset.flOp)")
    gates = page.eval_on_selector_all("[data-fl-gate]", "els => els.map(e => e.dataset.flGate)")
    record(len(ops) >= 30, "palette lists the vocabulary", f"{len(ops)} ops offered")
    record("gate" in gates and "review" in gates, "gates are in the palette",
           f"gate blocks: {gates}")

    # --- adding steps -------------------------------------------------------
    open_groups(page)
    page.click('[data-fl-op="web.fetch"]')
    open_groups(page)
    page.click('[data-fl-op="llm.classify"]')
    page.wait_for_selector("[data-fl-step]")
    n = len(page.query_selector_all("[data-fl-step]"))
    record(n == 2, "clicking a palette op adds a step", f"{n} steps in the stack")

    # --- inserting in the MIDDLE, not at the end ----------------------------
    # The mark before index 1 sits between the two steps that exist.
    mark = page.query_selector('[data-fl-ins="1"]')
    if mark is None:
        record(False, "insertion mark places a step", "no insertion mark rendered")
    else:
        mark.click()
        open_groups(page)
        page.click('[data-fl-gate="gate"]')
        page.wait_for_timeout(300)
        kinds = page.eval_on_selector_all(
            "[data-fl-step]",
            "els => els.map(e => e.closest('.flw-step') ? "
            "(e.querySelector('[data-fl-gsum]') ? 'gate' : 'op') : 'op')")
        record(len(kinds) == 3 and kinds[1] == "gate",
               "insertion mark places a step", f"stack after inserting: {kinds}")

    # --- the approval text is editable --------------------------------------
    gsum = page.query_selector("[data-fl-gsum]")
    editable = False
    if gsum:
        gsum.click()
        page.wait_for_timeout(200)
        editable = page.query_selector("[data-fl-gtext], textarea, input.fl-input") is not None
    record(editable, "approval text can be edited",
           "an input appears for the gate prompt" if editable
           else "the gate prompt offers no editable field")

    # --- a source picker must only offer EARLIER steps ----------------------
    # A picker that offers a later step lets someone wire a flow that cannot run;
    # the compiler would refuse it, but only once the work is under way.
    heads = page.query_selector_all("[data-fl-step]")
    if heads:
        heads[-1].click()
        page.wait_for_timeout(400)
    pickers = page.eval_on_selector_all(
        "[data-fl-in]",
        "els => els.map(e => ({at: +e.dataset.flIn,"
        " options: Array.from(e.options).map(o => o.value)}))")
    ids = page.eval_on_selector_all("[data-fl-id]", "els => els.map(e => e.value)")
    if not pickers:
        record(False, "source picker offers only earlier steps",
               "no wire picker rendered for an opened step")
    else:
        bad = []
        for pk in pickers:
            later = [o for o in pk["options"]
                     if o in ids and ids.index(o) >= pk["at"]]
            if later:
                bad.append((pk["at"], later))
        record(not bad, "source picker offers only earlier steps",
               f"{len(pickers)} picker(s), none offering a later step" if not bad
               else f"offers steps that come later: {bad}")

    # --- the save message must survive the re-render it triggers ------------
    name = "ui-probe-7q4x"
    page.fill("#fl-f-name", name)
    page.click("[data-fl-save]")
    page.wait_for_timeout(1500)
    hint = page.query_selector("#fl-savehint")
    text = (hint.inner_text().strip() if hint else "")
    record(bool(text), "the save message survives the re-render",
           f"hint says {text!r}" if text
           else "the hint element is empty - the message was written into an "
                "element the re-render had already replaced")

    # Take the probe flow back out of the library.
    page.evaluate(
        "fetch('http://127.0.0.1:8096/pipeline/flow/%s', {method:'DELETE'})" % name)
    page.wait_for_timeout(500)


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            run(page)
        except Exception as e:
            record(False, "the builder survives the walkthrough",
                   f"{type(e).__name__}: {str(e)[:140]}")
        browser.close()

    record(not errors, "no errors in the browser console",
           "clean" if not errors else f"{len(errors)}: {errors[:2]}")

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    for verdict, subject, detail in results:
        print(f"{verdict}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
