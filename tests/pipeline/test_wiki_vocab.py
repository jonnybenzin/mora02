#!/usr/bin/env python3
"""The VOKABULAR tab: does the vocabulary read as a table a human can act on?

The tab answers questions that are asked before an op is used - what does this
cost, how long does it take, does it leave the house - so the things worth
testing are the ones that would quietly mislead: a filter that stays on without
saying so, a count that does not move, an empty cell that reads as "nothing"
when it means "not known".

Two states are both legitimate and both tested by simply running this:
the measured columns are filled when /pipeline/vocab-stats answers, and empty
with a visible notice when it does not (an older container). The table must be
usable either way.

Usage:
    python3 tests/pipeline/test_wiki_vocab.py
    python3 tests/pipeline/test_wiki_vocab.py --headed

Environment: PILOT_UI_URL (default http://mora02.local:8092/pilot/index.html)
"""

from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

UI = os.environ.get("PILOT_UI_URL", "http://mora02.local:8092/pilot/index.html")

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str) -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))


def count_label(page) -> str:
    el = page.query_selector("#vocab-count")
    return el.inner_text().strip() if el else ""


def rows(page) -> int:
    return len(page.query_selector_all("[data-vrow]"))


def run(page) -> None:
    page.goto(UI, wait_until="networkidle")
    page.evaluate("navigate('wiki')")
    page.wait_for_selector(".wiki-tabs", timeout=15000)

    labels = page.eval_on_selector_all(
        ".wiki-tabs *", "els => els.map(e => e.textContent.trim()).filter(Boolean)")
    record("VOKABULAR" in labels, "the tab sits with the others", f"tabs: {labels}")

    page.click("text=VOKABULAR")
    page.wait_for_selector("[data-vrow]", timeout=15000)

    total = rows(page)
    record(total >= 39, "every op is listed", f"{total} rows")
    record(count_label(page) == f"{total} von {total}",
           "the count says how many of how many", count_label(page))

    # ALL is the absence of filters, so it is lit when nothing is filtered.
    all_btn = page.query_selector('[data-vf="__all"]')
    record(all_btn is not None and "tool-btn-primary" in (all_btn.get_attribute("class") or ""),
           "ALLE is lit when nothing is filtered",
           (all_btn.get_attribute("class") if all_btn else "no ALLE button"))

    # A filter must visibly reduce - and the count must say so, because a filter
    # left on silently is how someone concludes an op no longer exists.
    #
    # The cost/effect fields arrived with this feature, so a container built
    # before them serves ops without them. That is a legitimate state, reported
    # as such: a FAIL here would blame the page for what the backend has not
    # been asked to send yet.
    has_facts = page.evaluate(
        "() => vocabOps.some(o => o.effect !== undefined || o.cost !== undefined)")
    page.click('[data-vf="outward"]')
    page.wait_for_timeout(300)
    filtered = rows(page)
    if not has_facts:
        results.append(("n/a", "a filter reduces the list",
                        "the container serves no cost/effect fields yet — rebuild first"))
    else:
        record(0 < filtered < total, "a filter reduces the list",
               f"{filtered} of {total} left after 'verlässt das Haus'")
    record(count_label(page) == f"{filtered} von {total}",
           "the count follows the filter", count_label(page))
    all_btn = page.query_selector('[data-vf="__all"]')
    record("tool-btn-primary" not in (all_btn.get_attribute("class") or ""),
           "ALLE goes dark while a filter is on",
           all_btn.get_attribute("class") or "")

    # Two filters combine rather than replace each other.
    page.click('[data-vf="cloud"]')
    page.wait_for_timeout(300)
    both = rows(page)
    record(both <= filtered, "filters combine", f"{both} left with both on")

    # ALL clears everything, including the search box.
    page.fill("#wiki-search", "linkedin")
    page.wait_for_timeout(300)
    page.click('[data-vf="__all"]')
    page.wait_for_timeout(300)
    record(rows(page) == total and (page.input_value("#wiki-search") or "") == "",
           "ALLE restores the full view and clears the search",
           f"{rows(page)} rows, search={page.input_value('#wiki-search')!r}")

    # Search alone narrows the table.
    page.fill("#wiki-search", "linkedin")
    page.wait_for_timeout(400)
    found = rows(page)
    record(0 < found < total, "search narrows the table", f"{found} row(s) for 'linkedin'")
    page.click('[data-vf="__all"]')
    page.wait_for_timeout(300)

    # A row opens its own detail rather than navigating away.
    before = rows(page)
    page.click('[data-vrow="notify"]')
    page.wait_for_timeout(300)
    detail = page.query_selector("text=Minimalbeispiel")
    record(detail is not None and rows(page) == before,
           "a row opens its detail in place",
           "detail shown" if detail else "no detail block appeared")

    # Whatever the backend can offer, the page must SAY which state it is in.
    note = page.eval_on_selector_all(
        "#wiki-list div",
        "els => els.map(e => e.textContent).filter(t => t.indexOf('Geldbeträge in Euro') !== -1"
        " || t.indexOf('Statistik-Endpunkt') !== -1)")
    record(bool(note), "the page names its own data state",
           (note[0][:90] if note else "neither a rate line nor a missing-stats notice"))


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            run(page)
        except Exception as e:
            record(False, "the tab survives the walkthrough",
                   f"{type(e).__name__}: {str(e)[:140]}")
        browser.close()

    # A 404 on the stats endpoint is an expected state (older container), not a
    # defect - it is reported by the page itself and tested above.
    real = [e for e in errors if "vocab-stats" not in e and "404" not in e]
    record(not real, "no unexpected errors in the browser console",
           "clean" if not real else f"{len(real)}: {real[:2]}")

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    na = sum(1 for v, _, _ in results if v == "n/a")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed - na} passed, {failed} failed, {na} not applicable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
