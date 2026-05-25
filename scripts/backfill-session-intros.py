#!/usr/bin/env python3
"""
Backfill "Für Dummies"-intro + metaphor paragraph to existing session summaries.

Reads each markdown file, sends it to the locally running llama-server
(whatever profile is currently loaded), asks for a short explanation +
metaphor in the user's house style, and prepends the result below the H1
title of the doc.

Idempotent: skips files that already contain the marker or the manual
H2 heading "## Worum es ging".

Usage:
    # Dry-run all files (safe default, writes nothing)
    ./backfill-session-intros.py

    # Actually write
    ./backfill-session-intros.py --apply

    # Single file, preview only
    ./backfill-session-intros.py --file /path/to/doc.md

    # Reprocess even already-tagged files
    ./backfill-session-intros.py --apply --force

    # Different source directory
    ./backfill-session-intros.py --dir /opt/mora02/knowledge/sessions --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SUMMARIES_DIR = Path("/opt/mora02/knowledge/sessions/claude/summaries")
LLAMA_URL = "http://mora02.local:8080/v1/chat/completions"
SCRIPT_RUNNER_CURRENT_URL = "http://mora02.local:8096/llm/current"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ENV_FILE = Path("/opt/mora02/docker/.env")
MARKER = "<!-- auto-dummies-intro:v1 -->"
REQUEST_TIMEOUT = 600  # seconds — Magistral can be slow

# Cloud model identifiers (must match Anthropic API exactly)
CLAUDE_MODEL_IDS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}

SYSTEM_PROMPT = """You are a technical editor writing short intros for session summaries in a solo developer's knowledge base. Each intro sits at the top of an existing session doc and gives the reader a plain-English overview plus a memorable metaphor.

## How you must reason

This is a reasoning task with multiple hard constraints. You MUST think step by step before producing your final output. Enclose ALL of your reasoning inside `[THINK]` and `[/THINK]` tags. Everything after `[/THINK]` is the clean final output and must match the strict format specified at the bottom.

Inside your `[THINK]` block, walk through these steps in order:

1. **Identify the session topic** — read the session doc carefully. Is it a technical session (code, infrastructure, debugging) or non-technical (creative writing, research, strategy)?
2. **Extract the arc**:
   (a) the MAIN ACTOR — who or what was doing the work
   (b) the CONFLICT — what was broken, stuck, or confusing
   (c) the RESOLUTION — what actually worked in the end
3. **Pick a metaphor scene** that is NOT in the avoid list (check the user message) and is NOT literally mentioned in the session doc (no transplantation). Brainstorm 2-3 candidate scenes and pick the one whose abstract actor/conflict/resolution shape best matches the session's arc.
4. **Draft the TL;DR paragraph** — 60-90 words in plain English, no file paths, no tool names, no code names. Voice: smart senior dev's Notion page.
5. **Check the TL;DR for banned terms**: if you find any specific tool name, file path, function name, or technology acronym, rewrite the sentence in plain English. Tech acronyms like "SSE", "AJAX", "CORS", "ORM", "UI" are banned even when they feel natural.
6. **Draft the metaphor title** — 4-10 words, anchored in the chosen scene, no trailing punctuation, no clichés from the banned list.
7. **Draft the metaphor paragraph** — 70-100 words, second-person voice, concrete sensory detail, small pointe at the end, structurally parallel to the session arc.
8. **Final verification pass**: explicitly check and state that (a) the title contains no trailing period/exclam, (b) the title and scene label refer to the same image, (c) the metaphor contains no noun from the source session doc, (d) the dummies paragraph contains no tech terms, (e) no banned cliché is present anywhere.
9. **Close the `[/THINK]` block and emit the final output in the strict format.**

The reasoning inside `[THINK]` tags will be automatically stripped before the intro is saved to disk. Be thorough — take as much reasoning space as you need. The final output must follow the format specification below exactly.

Every intro has four parts in a strict order.

## Part 1: TL;DR paragraph (60-90 words, 3-5 sentences)

A plain-English summary of what the session was about, what the problem was, and what the solution was. No file paths. No code names. No tool names unless absolutely unavoidable. If the session was non-technical (creative writing, research, strategy), adapt accordingly: what was being worked on, and what came out of it.

Voice: a senior developer writing for their future self. Smart, casual, zero corporate fluff. Think Stripe Atlas or 37signals — not LinkedIn, not academic.

## Part 2: Metaphor title (4-10 words)

A punchy hook that sits above the metaphor paragraph. Will double as a text overlay on short social-media videos we'll generate later. Must stop a thumb in a feed.

A good title is ANCHORED IN THE SCENE you're about to tell (it points at a specific object, character, or moment from the metaphor — not at the underlying technology), it is SPECIFIC rather than abstract, and it creates curiosity without being clever for clever's sake. Think of it like the title of a tiny fable. Do not generate a title before you have chosen your metaphor — the title must come FROM the metaphor, not the other way around.

BAD titles (descriptive, clichéd, or directly naming the technology — NEVER produce anything that looks like these):
- "AJAX Polling for Progress Updates"
- "A Simple Solution to a Complex Problem"
- "Game-Changing Insights on Architecture"
- "The Power of Simplicity"
- "Lessons Learned from the Refactor"
- "Unlocking the Potential of X"

Title rules:
- NO trailing period or exclamation mark. Question mark only if the title is literally a question.
- NO clichés: banned phrases include "game-changer", "it just works", "brutally simple", "the power of X", "in today's world", "lessons learned", "a deep dive", "under the hood", "next-level", "behind the scenes".
- Anchor it in the scene or the insight. Never in the technology.
- DO NOT reuse a title from anywhere in this prompt or from a prior batch output. Invent a fresh one for each session.

## Part 3: Scene label (1-3 words)

The noun of the chosen metaphor scene, short. Used internally to track which scenes have been used already in this batch so we can vary them. Examples: "Lighthouse", "Bakery night shift", "Chess club", "Weather station", "Pharmacy", "Post sorting room".

## Part 4: Metaphor paragraph (70-100 words, 3-5 sentences)

A fleshed-out everyday scene that structurally mirrors the session. Use second-person ("You're standing in a…"), concrete sensory detail, and end on a small turn or pointe. Slightly absurd or unexpected is welcome and encouraged.

### The Coherence Rule (critical)

Before writing the metaphor, extract these three things from the TL;DR and write them down in your reasoning (do not output them):
(a) the MAIN ACTOR — who or what was doing the work
(b) the CONFLICT — what was broken, stuck, or confusing
(c) the RESOLUTION — what actually worked in the end

Then pick a scene where a PARALLEL actor faces a PARALLEL conflict and finds a PARALLEL resolution. Not a scene that just has a similar vibe. Not a scene that's vaguely related. The actor-conflict-resolution arc must be isomorphic — the abstract shape of the arc must be preserved exactly, even while every concrete element changes.

### The No-Literal-Transplant Rule (equally critical)

The metaphor must be STRUCTURALLY parallel but CONCRETELY DIFFERENT from the source. Transform the scene — never transplant it. If the source mentions a bakery, the metaphor must not contain a bakery. If the source involves an elderly woman, the metaphor must not feature an elderly woman. If the source is about a lighthouse, the metaphor must not be about a lighthouse. If the source says "cat", the metaphor does not contain any animal that would read as cat-adjacent (dogs, ferrets, parrots, etc. are fine if the arc fits — but check).

Swap the setting, the characters, the props — keep only the abstract actor-conflict-resolution shape.

BAD transplantation (noun substitution of the source scene — NEVER do this):
Source content: anything about a bakery with an elderly woman
BAD metaphor: a bakery scene with an elderly woman where only one noun was swapped

That is NOT a metaphor. That is the original story with new props glued on. A real metaphor takes place in a scene the source never mentioned.

#### Coherence example (GOOD):
TL;DR: "A stubborn stray cat refused every rescue attempt and finally found a home with an elderly woman who wasn't trying to save her."
GOOD metaphor: an old weather vane on a village church that refused to turn for decades, considered broken by everyone — until one stormy afternoon it snapped west and turned out to have been pointing the right way all along.
(Actor: stubborn thing. Conflict: considered useless. Resolution: found purpose without trying.)

#### Coherence example (BAD):
TL;DR: same cat story.
BAD metaphor: an airport check-in agent trying to help a frustrated passenger through a broken system.
(Wrong actor, wrong conflict, wrong resolution. The metaphor has nothing structural to do with the cat.)

### Scene variation

Never reuse a scene already used earlier in this batch (the user message will tell you which scenes are off-limits). Pull from any corner of ordinary life: workshops, kitchens, libraries, harbors, mountain stations, classrooms, offices, factories, theaters, beehives, hospitals, construction sites, hotels, radio stations, train yards, farm stands, laundromats, dive schools, museums. Avoid pizzerias and restaurants unless the session genuinely demands it.

## Voice for all four parts

Write like a senior developer's Notion page. Smart, casual, specific, zero corporate fluff. One gentle wink allowed per paragraph. No "in our ever-changing world". No "it just works". No "game-changer". No "it turns out that…" as filler.

## Output format (strict)

Reply with EXACTLY this format, nothing before or after. No markdown headers. No preamble. Start with `===DUMMIES===` on its own line. End with `===END===` on its own line.

The format skeleton:

===DUMMIES===
{60-90 word TL;DR paragraph written in plain English, no tool names, no file paths, voice: smart senior dev's Notion page}

===TITLE===
{4-10 word scene-anchored hook, no trailing punctuation, never reused from the prompt}

===SCENE===
{1-3 word noun phrase naming the metaphor's setting}

===METAPHOR===
{70-100 word second-person scene that is STRUCTURALLY PARALLEL (same actor-conflict-resolution shape) but CONCRETELY DIFFERENT (different setting, different props, different characters) from whatever the session doc describes. End on a small pointe.}
===END===

Write every part yourself from scratch. Do not reuse any title, scene, or metaphor content from this prompt's instructions — those are rules, not templates. Invent fresh material every time, tailored to the specific session document you receive."""

USER_TEMPLATE = (
    "Here is the session document. Write the four-part intro in the specified "
    "format. Output English only. Work through the coherence checklist (actor, "
    "conflict, resolution) before writing the metaphor. Take your time and "
    "think carefully — this is a reasoning task.\n\n"
    "---\n"
    "{content}\n"
    "---{avoid_block}"
)

# ---------------------------------------------------------------------------
# Critique pass: a second LLM call that reads the draft and produces a
# revised version. Reasoning models respond well to explicit self-critique
# when the draft is presented as a concrete object to react to.
# ---------------------------------------------------------------------------

CRITIQUE_SYSTEM_PROMPT = """You are a strict editor reviewing a draft intro that was written for a session document. Your job is to check the draft against a list of hard rules, identify every violation, and rewrite the intro so it passes all rules.

## How you must reason

Enclose ALL your reasoning inside `[THINK]` and `[/THINK]` tags. Everything after `[/THINK]` is the final revised output and must match the strict format at the bottom.

Inside `[THINK]`, work through these checks explicitly, one by one, stating PASS or FAIL for each:

**Mechanical checks (easy to verify):**
1. Dummies word count — count the words in the dummies paragraph. Must be 60-90 words. PASS or FAIL with count.
2. Dummies voice — is it in the "smart senior dev's Notion page" register (casual, specific, concrete), or is it clinical/passive/corporate? A clinical dummies is a FAIL.
3. Dummies tech terms — scan for any specific tool name, file path, function name, code symbol, programming language, library name, acronym (SSE, AJAX, CORS, API, UI, ORM, REST), technology name (PostgreSQL, WebSocket, Redis, Docker, etc.). Any such term is a FAIL, list each one.
4. Title word count — 4-10 words. Count.
5. Title trailing punctuation — no period, no exclamation mark. Question mark only if genuine question. Check.
6. Title clichés — scan for these banned phrases: "just works", "it just works", "game-changer", "brutally simple", "the power of X", "in today's world", "lessons learned", "a deep dive", "under the hood", "next-level", "behind the scenes", "at the end of the day". Any match is a FAIL.
7. Title-scene match — does the title point at something in the metaphor scene (an object, character, or moment from within the metaphor)? If the title references the source session's topic instead of the metaphor scene, FAIL.
8. Metaphor word count — 70-100 words.

**Semantic checks (harder, require actual reading):**
9. **Transplantation check** — list every concrete noun/character/object from the source session document. Then scan the metaphor. Does the metaphor contain any of those source nouns? If yes, FAIL — the metaphor is transplantation, not transformation.
10. **Coherence arc check** — this is the most important. Extract the session arc:
    - Session MAIN ACTOR: who or what was doing the work in the session?
    - Session CONFLICT: what was broken, stuck, or confusing?
    - Session RESOLUTION: what actually worked in the end?
    Now extract the metaphor arc:
    - Metaphor MAIN ACTOR: who or what is the protagonist of the scene?
    - Metaphor CONFLICT: what is the problem in the scene?
    - Metaphor RESOLUTION: how does the scene end?
    Compare them. The arcs must be STRUCTURALLY ISOMORPHIC. That means: the metaphor actor plays the same functional role as the session actor, the metaphor conflict mirrors the session conflict, and the metaphor resolution mirrors the session resolution. If the metaphor tells a different kind of story with a different pointe, FAIL with explanation.
11. **Session-insight check** — what is the core insight or lesson of the session? (e.g. "simple solution beat fancy one", "letting go solved the problem", "shared system reduced duplication".) Does the metaphor deliver the SAME insight? If the metaphor delivers a different lesson (e.g. "trial and error works" when the session is about "simple wins over complex"), FAIL.

After walking through all 11 checks, count the FAILs. If there are zero FAILs, output the original draft unchanged. If there is one or more FAIL, rewrite the intro so it passes every rule. When rewriting, fix the specific issues identified — do not rewrite parts that were already passing.

## Output format (strict)

After the `[/THINK]` block, output EXACTLY this format, nothing before or after:

===DUMMIES===
{dummies paragraph, 60-90 words, plain English voice}

===TITLE===
{title, 4-10 words, no trailing punctuation, anchored in the metaphor scene}

===SCENE===
{1-3 word noun phrase}

===METAPHOR===
{70-100 word second-person scene, structurally parallel to the session arc, no source transplantation}
===END==="""

CRITIQUE_USER_TEMPLATE = (
    "Here is the original session document:\n\n"
    "---\n"
    "{content}\n"
    "---\n\n"
    "Here is the draft intro to review and revise:\n\n"
    "===DUMMIES===\n"
    "{dummies}\n\n"
    "===TITLE===\n"
    "{title}\n\n"
    "===SCENE===\n"
    "{scene}\n\n"
    "===METAPHOR===\n"
    "{metaphor}\n"
    "===END===\n\n"
    "Run through all 11 checks explicitly, then produce the revised intro."
    "{avoid_block}"
)

AVOID_BLOCK_TEMPLATE = (
    "\n\n**IMPORTANT — scenes already used in this batch, DO NOT reuse any of "
    "these:** {scenes}. Pick a scene from a completely different corner of "
    "ordinary life."
)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------


def http_post_json(url: str, payload: dict, timeout: int, extra_headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_claude_api_key() -> str:
    """
    Read the Anthropic API key from /opt/mora02/docker/.env.

    Accepts three formats:
      1. Raw key as entire file content (starts with "sk-")
      2. VAR=value format with CLAUDE_API_KEY or ANTHROPIC_API_KEY
      3. `export VAR=value` shell-style variant of (2)
    """
    if not ENV_FILE.exists():
        raise RuntimeError(f"{ENV_FILE} not found — cannot call Anthropic API")
    content = ENV_FILE.read_text().strip()

    # Format 1: the entire file is just the key (no variable wrapper).
    if content.startswith("sk-"):
        # Take only the first line in case there are trailing newlines
        first_line = content.splitlines()[0].strip()
        if first_line.startswith("sk-") and len(first_line) > 10:
            return first_line

    # Format 2/3: parse line-by-line looking for known key names.
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        for key_name in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"):
            prefix = key_name + "="
            if line.startswith(prefix):
                val = line[len(prefix):].strip().strip('"').strip("'")
                if val:
                    return val

    raise RuntimeError(
        f"No usable API key found in {ENV_FILE}. Expected either a raw "
        f"key starting with 'sk-' as the file content, or a line "
        f"'CLAUDE_API_KEY=...' / 'ANTHROPIC_API_KEY=...'."
    )


def http_get_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_current_profile_label() -> str:
    """Ask script-runner which local profile is currently active."""
    try:
        data = http_get_json(SCRIPT_RUNNER_CURRENT_URL)
        cur = data.get("current") or {}
        return cur.get("label") or cur.get("name") or "unknown"
    except Exception:
        return "unknown"


def _build_user_content(content: str, seen_scenes: list[str] | None) -> str:
    avoid_block = ""
    if seen_scenes:
        avoid_block = AVOID_BLOCK_TEMPLATE.format(scenes=", ".join(seen_scenes))
    return USER_TEMPLATE.format(content=content, avoid_block=avoid_block)


def _build_critique_user_content(
    content: str, dummies: str, title: str, scene: str, metaphor: str,
    seen_scenes: list[str] | None,
) -> str:
    avoid_block = ""
    if seen_scenes:
        avoid_block = AVOID_BLOCK_TEMPLATE.format(scenes=", ".join(seen_scenes))
    return CRITIQUE_USER_TEMPLATE.format(
        content=content,
        dummies=dummies,
        title=title,
        scene=scene,
        metaphor=metaphor,
        avoid_block=avoid_block,
    )


def _call_local(system_prompt: str, user_content: str, temperature: float) -> str:
    payload = {
        "model": "local",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": 6144,
        "stream": False,
    }
    data = http_post_json(LLAMA_URL, payload, timeout=REQUEST_TIMEOUT)
    return data["choices"][0]["message"]["content"]


def _call_anthropic(
    model_key: str, system_prompt: str, user_content: str, temperature: float,
) -> str:
    """Send a single non-streaming Messages request to the Anthropic API."""
    api_key = load_claude_api_key()
    model_id = CLAUDE_MODEL_IDS[model_key]
    payload = {
        "model": model_id,
        "max_tokens": 6144,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    data = http_post_json(ANTHROPIC_URL, payload, timeout=REQUEST_TIMEOUT, extra_headers=headers)
    blocks = data.get("content", [])
    if not blocks:
        raise RuntimeError("Anthropic returned empty content array")
    # Response is a list of blocks; take the text of the first text block.
    for block in blocks:
        if block.get("type") == "text":
            return block.get("text", "")
    raise RuntimeError("Anthropic response had no text block")


def call_llm(
    content: str, seen_scenes: list[str] | None = None, model: str = "local",
) -> str:
    user_content = _build_user_content(content, seen_scenes)
    if model == "local":
        return _call_local(SYSTEM_PROMPT, user_content, temperature=0.75)
    return _call_anthropic(model, SYSTEM_PROMPT, user_content, temperature=0.7)


def call_critique(
    content: str,
    dummies: str,
    title: str,
    scene: str,
    metaphor: str,
    seen_scenes: list[str] | None = None,
    model: str = "local",
) -> str:
    """
    Second-pass critique call. Takes the draft intro produced by call_llm(),
    feeds it back to the model, asks it to check the draft against the rule
    set explicitly, and output a revised version.
    """
    user_content = _build_critique_user_content(
        content, dummies, title, scene, metaphor, seen_scenes
    )
    if model == "local":
        return _call_local(CRITIQUE_SYSTEM_PROMPT, user_content, temperature=0.65)
    return _call_anthropic(model, CRITIQUE_SYSTEM_PROMPT, user_content, temperature=0.5)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def strip_think_tags(text: str) -> str:
    """
    Remove reasoning-model think blocks from model output. Handles all the
    format variants we've observed in the wild:
      - <think>...</think>     (Qwen3 convention)
      - [THINK]...[/THINK]     (Mistral convention, documented)
      - [THINK]...</THINK>     (Magistral hybrid, actually emitted — yes really)
      - <think>...[/THINK]     (the other hybrid, just in case)
    Matching is case-insensitive via re.IGNORECASE.

    If the strip would erase everything (model output was ALL reasoning
    with no actual answer), fall back to the original text so the caller
    sees what happened instead of getting a silent empty-string crash.
    """
    # Match any opening think tag, any content, any closing think tag.
    unified = re.compile(
        r"(?:<think>|\[THINK\])[\s\S]*?(?:</think>|\[/THINK\])\s*",
        re.IGNORECASE,
    )
    stripped = unified.sub("", text)

    if not stripped.strip() and text.strip():
        # Unclosed opening tag (truncated by max_tokens).
        unclosed = re.compile(r"(?:<think>|\[THINK\])[\s\S]*$", re.IGNORECASE)
        stripped = unclosed.sub("", text)
        if not stripped.strip():
            return text  # give the parser the raw content so it can error loudly
    return stripped


def parse_response(raw: str) -> tuple[str, str, str, str]:
    clean = strip_think_tags(raw).strip()
    # ===END=== is optional — some models omit it. Match until END marker
    # OR end of string, whichever comes first.
    pattern = re.compile(
        r"===DUMMIES===\s*(.*?)\s*"
        r"===TITLE===\s*(.*?)\s*"
        r"===SCENE===\s*(.*?)\s*"
        r"===METAPHOR===\s*(.*?)(?:\s*===END===|\s*$)",
        re.DOTALL,
    )
    m = pattern.search(clean)
    if not m:
        raise ValueError(
            "LLM response did not match expected format.\n"
            f"Full cleaned output ({len(clean)} chars):\n{clean}"
        )
    dummies = m.group(1).strip()
    title = m.group(2).strip()
    scene = m.group(3).strip()
    metaphor = m.group(4).strip()
    # Collapse any accidental newlines in title/scene to single line
    title = " ".join(title.split())
    scene = " ".join(scene.split())
    # Strip trailing punctuation from title (no period, no exclam). Keep ?.
    title = re.sub(r"[.!]+$", "", title).rstrip()
    if not dummies or not title or not scene or not metaphor:
        raise ValueError(
            f"LLM response parsed but sections empty.\n"
            f"dummies={len(dummies)}, title={len(title)}, "
            f"scene={len(scene)}, metaphor={len(metaphor)}\n"
            f"Full cleaned output:\n{clean}"
        )
    return dummies, title, scene, metaphor


# ---------------------------------------------------------------------------
# Markdown injection
# ---------------------------------------------------------------------------


def already_processed(content: str) -> bool:
    if MARKER in content:
        return True
    # Fallback: heuristic — docs written manually already have the heading
    if "## Worum es ging (Für-Dummies-Version)" in content:
        return True
    if "## Worum es ging" in content and "(Für-Dummies" in content:
        return True
    return False


def strip_existing_intro(content: str) -> str:
    """
    Remove a previously auto-generated intro block (marker + Für-Dummies
    section + trailing '---' separator) so we can re-inject cleanly when
    --force is used.

    Only strips blocks that were written by THIS script (marker-bracketed).
    Manually written intros are left alone.
    """
    if MARKER not in content:
        return content
    # Match from the marker line through the first "---\n" that follows
    # the metaphor (our injection always ends with '---\n\n').
    pattern = re.compile(
        r"^" + re.escape(MARKER) + r"\s*\n.*?\n---\s*\n\s*",
        re.DOTALL | re.MULTILINE,
    )
    return pattern.sub("", content, count=1)


def inject_intro(original: str, dummies: str, title: str, metaphor: str) -> str:
    block = (
        f"{MARKER}\n\n"
        f"## In Plain English\n\n"
        f"{dummies}\n\n"
        f"### {title}\n\n"
        f"{metaphor}\n\n"
        f"---\n\n"
    )

    # If the doc starts with an H1, insert below it + preserve any metadata
    lines = original.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("# "):
        # Find the end of the title block (the first blank line after H1
        # or until we hit the next heading). Keep any metadata that sits
        # directly under the H1 (lines that don't start with ##).
        title_end = 1
        while title_end < len(lines):
            stripped = lines[title_end].strip()
            if stripped.startswith("## ") or stripped.startswith("---"):
                break
            title_end += 1
        head = "".join(lines[:title_end])
        tail = "".join(lines[title_end:])
        # Make sure there's a blank line between head and our block
        if not head.endswith("\n\n"):
            head = head.rstrip("\n") + "\n\n"
        return head + block + tail.lstrip("\n")

    # No H1: just prepend
    return block + original


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def classify_content(content: str) -> str:
    """
    Classify the current state of a file:
      - "marker": contains our auto-generated marker (safe to --force over)
      - "manual": contains a "plain English"/"Für-Dummies" heading but no
                  marker (user-written, protected even from --force)
      - "fresh":  no intro at all, safe to process
    """
    if MARKER in content:
        return "marker"
    # German manual intros (legacy)
    if "## Worum es ging (Für-Dummies-Version)" in content:
        return "manual"
    if "## Worum es ging" in content and "(Für-Dummies" in content:
        return "manual"
    # English manual intros (new convention) — only treat as manual when
    # paired with the marker absence (which is already checked above).
    if "## In Plain English" in content:
        return "manual"
    return "fresh"


def process_file(
    path: Path,
    apply: bool,
    force: bool,
    seen_scenes: list[str] | None = None,
    verbose: bool = True,
    critique: bool = False,
    model: str = "local",
) -> str:
    content = path.read_text(encoding="utf-8")
    state = classify_content(content)

    # Manual intros are ALWAYS protected, even with --force. This prevents
    # accidental clobbering of user-written content like today's session doc.
    if state == "manual":
        return "SKIP (manual intro, protected from --force)"

    if state == "marker" and not force:
        return "SKIP (already auto-processed, use --force to reprocess)"

    # On --force re-run of a marker block: strip the previous auto-generated
    # intro before feeding the LLM and before injecting the new one.
    clean_content = strip_existing_intro(content) if state == "marker" else content

    if verbose:
        print(f"  → calling LLM for {path.name}"
              + (f" (avoid: {', '.join(seen_scenes)})" if seen_scenes else "")
              + "...", flush=True)

    # Up to 2 attempts — retry once on parse fail or transient errors.
    last_error = None
    dummies = title = scene = metaphor = None
    for attempt in (1, 2):
        try:
            raw = call_llm(clean_content, seen_scenes=seen_scenes, model=model)
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if attempt == 1 and verbose:
                print(f"  ⚠ attempt 1 failed ({last_error}), retrying...", flush=True)
            continue
        except urllib.error.URLError as e:
            return f"CONNECT FAIL: {e.reason}"
        except Exception as e:
            last_error = f"LLM CALL FAIL: {e}"
            if attempt == 1 and verbose:
                print(f"  ⚠ attempt 1 failed ({last_error}), retrying...", flush=True)
            continue

        try:
            dummies, title, scene, metaphor = parse_response(raw)
            break  # success
        except ValueError as e:
            last_error = f"PARSE FAIL: {e}"
            if attempt == 1 and verbose:
                print(f"  ⚠ attempt 1 parse failed, retrying...", flush=True)
            continue

    if dummies is None:
        return last_error or "UNKNOWN FAILURE"

    # --- Optional critique pass ---
    # Feed the draft back to the reasoning model for explicit rule-checking
    # and revision. Keep the original draft as a fallback if the critique
    # step fails to produce a valid revised version.
    if critique:
        if verbose:
            print(f"  ↻ running critique pass...", flush=True)
        try:
            raw_crit = call_critique(
                clean_content, dummies, title, scene, metaphor,
                seen_scenes=seen_scenes, model=model,
            )
            d2, t2, s2, m2 = parse_response(raw_crit)
            if verbose:
                changed = (d2 != dummies or t2 != title or s2 != scene or m2 != metaphor)
                marker = "revised" if changed else "passed through unchanged"
                print(f"  ↻ critique {marker} (scene: '{s2}')", flush=True)
            dummies, title, scene, metaphor = d2, t2, s2, m2
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            if verbose:
                print(f"  ⚠ critique failed ({e}); keeping original draft", flush=True)
            # Fall through with the original draft

    new_content = inject_intro(clean_content, dummies, title, metaphor)

    # Track the scene for subsequent batch calls (happens even in dry-run,
    # so previews stay consistent with a hypothetical apply run).
    if seen_scenes is not None and scene and scene not in seen_scenes:
        seen_scenes.append(scene)

    if not apply:
        print("  --- PREVIEW (first 1200 chars of new content) ---")
        print("  " + new_content[:1200].replace("\n", "\n  "))
        print(f"  --- scene used: '{scene}' ---")
        return "DRY-RUN (nothing written)"

    # Backup with timestamp so re-runs don't overwrite prior backups
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(f"{path.suffix}.{ts}.bak")
    bak.write_text(content, encoding="utf-8")
    path.write_text(new_content, encoding="utf-8")
    return f"WRITTEN (scene: '{scene}', backup: {bak.name})"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=str, action="append", default=None,
                    help=f"Directory with session docs. Can be repeated to combine "
                         f"multiple dirs into one batch with shared scene tracking. "
                         f"Default: {DEFAULT_SUMMARIES_DIR}")
    ap.add_argument("--file", type=str, default=None,
                    help="Process only this single file (absolute or relative path)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write files. Without this flag, runs dry.")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess files that already have the intro marker")
    ap.add_argument("--avoid-scene", type=str, action="append", default=None,
                    help="Seed the scene-avoid list with this scene. Repeatable. "
                         "Useful for single-file retries after a failed batch.")
    ap.add_argument("--critique", action="store_true",
                    help="Enable second-pass self-critique: after the initial "
                         "draft is produced, feed it back to the reasoning "
                         "model for explicit rule-check and revision.")
    ap.add_argument("--model", choices=["local", "haiku", "sonnet", "opus"],
                    default="local",
                    help="Model backend: 'local' uses llama.cpp at port 8080 "
                         "(whatever profile is loaded), or 'haiku'/'sonnet'/"
                         "'opus' for Anthropic API. Default: local.")
    args = ap.parse_args()

    if args.model == "local":
        profile = get_current_profile_label()
        print(f"Model backend: LOCAL ({profile}) via {LLAMA_URL}")
    else:
        print(f"Model backend: ANTHROPIC API ({CLAUDE_MODEL_IDS[args.model]})")
    print(f"Mode: {'APPLY (writing files)' if args.apply else 'DRY-RUN (no writes)'}")
    print(f"Critique loop: {'ON' if args.critique else 'OFF'}")
    print()

    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1
        files = [p]
    else:
        dirs = [Path(d) for d in (args.dir or [str(DEFAULT_SUMMARIES_DIR)])]
        for d in dirs:
            if not d.is_dir():
                print(f"ERROR: {d} not a directory", file=sys.stderr)
                return 1
        files = []
        for d in dirs:
            files.extend(sorted(d.glob("*.md")))

    if not files:
        print("No .md files found.")
        return 0

    print(f"Found {len(files)} file(s) to consider")
    print()

    # Shared state: scenes already used within this batch. Each successful
    # LLM call appends its scene here, and subsequent calls get this list
    # as an "avoid" instruction in the user message.
    seen_scenes: list[str] = list(args.avoid_scene or [])
    if seen_scenes:
        print(f"Seeded avoid list: {', '.join(seen_scenes)}")
        print()

    written = 0
    skipped = 0
    failed = 0
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        result = process_file(
            f, apply=args.apply, force=args.force,
            seen_scenes=seen_scenes, critique=args.critique,
            model=args.model,
        )
        print(f"  → {result}")
        if result.startswith("WRITTEN"):
            written += 1
        elif result.startswith("SKIP"):
            skipped += 1
        elif "FAIL" in result or result.startswith("HTTP") or result.startswith("CONNECT"):
            failed += 1
        print()

    print("—" * 60)
    print(f"Summary: {written} written, {skipped} skipped, {failed} failed, "
          f"{len(files) - written - skipped - failed} dry-run")
    if seen_scenes:
        print(f"Scenes used in this batch: {', '.join(seen_scenes)}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
