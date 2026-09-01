"""Search via the local SearXNG, and read a page as plain text.

Lifted out of script-runner's step handlers unchanged in behaviour; what is new
is ``search_many``, which the agent layer needs and a pipeline step does not.

WHY MANY QUERIES IN ONE CALL. The tool bench measured long tool chains and found
them shaky: eight hops one file at a time held 5/5 for one profile and 2/5 for
the same profile on another run, and the model with the best endurance was the
worst at admitting a broken trail. Research is a chain that breaks constantly —
a search returning nothing useful IS a broken hop, and it is the rule rather
than the exception.

The way around that is not a better model but fewer, bigger hops. Three angles
asked at once is one tool call returning two dozen results; asked one at a time
it is three calls, three chances to lose the thread, and three chances to invent
a result where none came back.
"""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from mora02_core._common import get_logger

log = get_logger("mora02_core.web")

_DEFAULT_SEARXNG = "http://searxng:8080"

_RE_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"\s+")

# A page is read to be understood, not archived. The ceiling is real -- a long
# page would blow past any context window -- but it is announced every time, so
# a summary of half a document can never look like a summary of the whole.
DEFAULT_MAX_CHARS = 20000


class WebError(RuntimeError):
    """The search or the page did not come back in a usable state."""


def _searxng_url() -> str:
    return os.environ.get("SEARXNG_URL", _DEFAULT_SEARXNG)


async def search(query: str, *, categories: str = "general", limit: int = 8) -> dict:
    """One query against the local metasearch engine.

    Returns ``{"query": ..., "results": [{title, url, content}, ...]}``. Every
    result carries its URL, which is what makes a claim traceable later without
    anyone having to remember to note where it came from.

    Raises rather than returning nothing when the engines themselves failed.
    SearXNG answers HTTP 200 with an empty list when every upstream engine is
    blocked, and names them in ``unresponsive_engines`` -- measured live:
    ``brave: Suspended: too many requests``, ``duckduckgo: CAPTCHA``,
    ``startpage: Suspended: CAPTCHA``. Passing that on as "no results" tells a
    caller that nothing exists when the truth is that nothing was looked at, and
    a model handed the first will report an empty field as a finding.
    """
    query = (query or "").strip()
    if not query:
        raise WebError("a search needs a query")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{_searxng_url()}/search",
                params={"q": query, "format": "json", "categories": categories},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        # Named rather than swallowed: "the search engine is unreachable" and
        # "nothing was found" are different facts, and a model told the second
        # when the first is true will report an empty field as a finding.
        raise WebError(f"SearXNG did not answer: {e}") from e

    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in (data.get("results") or [])[:limit]
    ]
    # [[name, reason], ...] -- SearXNG's own account of which engines declined.
    dead = [f"{e[0]}: {e[1]}" for e in (data.get("unresponsive_engines") or []) if e]

    if not results and dead:
        raise WebError(
            "no engine answered — " + "; ".join(dead)
            + ". This is not an empty result, it is a failed search."
        )

    out = {"query": query, "results": results}
    if dead:
        # Some answered, some did not. Not fatal, but the coverage is thinner
        # than the number of hits suggests, and that belongs in the record.
        out["engines_failed"] = dead
    return out


async def search_many(
    queries: list[str], *, categories: str = "general", limit: int = 8
) -> dict:
    """Several angles at once, run concurrently, reported per query.

    Kept per-query rather than merged into one ranked list: which angle found a
    result is itself information — a claim that only ever turns up under one
    phrasing is a different kind of claim than one that turns up under three.

    A query that fails does not sink the rest. It comes back with its error, so
    "this angle found nothing" and "this angle could not be tried" stay apart.
    """
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    if not queries:
        raise WebError("a search needs at least one query")

    async def one(q: str) -> dict:
        try:
            return await search(q, categories=categories, limit=limit)
        except WebError as e:
            return {"query": q, "results": [], "error": str(e)}

    per_query = await asyncio.gather(*(one(q) for q in queries))

    seen: set[str] = set()
    unique = 0
    for block in per_query:
        for r in block["results"]:
            if r["url"] and r["url"] not in seen:
                seen.add(r["url"])
                unique += 1

    log.info("searched %d angle(s), %d unique urls", len(queries), unique)
    return {
        "queries": queries,
        "per_query": per_query,
        "unique_urls": unique,
        "failed": [b["query"] for b in per_query if b.get("error")],
    }


async def fetch(url: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    """One page as readable text.

    Returns ``{"url", "text", "chars"}`` plus, when the page was longer than the
    ceiling, ``truncated``, ``source_chars`` and a ``hint`` naming how to raise
    it. The cut is always reported: a silent one turns half a document into
    something that reads like a whole one.
    """
    url = (url or "").strip()
    if not url:
        raise WebError("a fetch needs a url")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (mora02 pipeline)"})
            resp.raise_for_status()
            body = resp.text
    except httpx.HTTPError as e:
        raise WebError(f"could not read {url}: {e}") from e

    text = _RE_WS.sub(" ", _RE_TAG.sub(" ", _RE_SCRIPT.sub(" ", body))).strip()
    # chars is what you GOT, source_chars is what the page had. The two used to
    # be the same number even when the text was cut, which reads as though
    # nothing was left behind.
    out: dict = {"url": url}
    if len(text) > max_chars:
        out.update(
            truncated=True, source_chars=len(text), max_chars=max_chars,
            hint=f"Seite auf {max_chars} von {len(text)} Zeichen gekürzt "
                 f"— max_chars erhöhen, um mehr zu holen.",
        )
        text = text[:max_chars]
    out["chars"] = len(text)
    out["text"] = text
    return out
