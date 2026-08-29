#!/usr/bin/env python3
"""Generate docs/pipeline-vocabulary.md from the pipeline op registry.

The vocabulary is single-source-of-truth in mora02_core.pipeline.vocab; this
renders the human-readable reference from it, grouped by bucket (semantic unit).
Re-run after changing an op:

    python3 scripts/gen-pipeline-vocab-doc.py

Do not edit the generated markdown by hand — edit vocab.py and regenerate.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

from mora02_core.pipeline import vocab  # noqa: E402

OUT = REPO / "docs" / "pipeline-vocabulary.md"

# Bucket -> readable section title, in the order they should appear. Buckets not
# listed here are appended at the end under their raw name (so a new bucket never
# vanishes from the doc — it just lands last until this list is updated).
BUCKET_TITLES: list[tuple[str, str]] = [
    ("source", "Sources"),
    ("image", "Image generation"),
    ("video", "Video"),
    ("blender", "3D text (Blender / PixelText)"),
    ("media", "Media finishing"),
    ("audio", "Audio"),
    ("llm", "Local LLM"),
    ("cloud", "Cloud LLM"),
    ("db", "Data (tables)"),
    ("web", "Web & stock"),
    ("publish", "Publishing"),
    ("delivery", "Delivery / notify"),
]

BADGE = {"wired": "🟢", "planned": "🟡"}


def _anchor(name: str) -> str:
    return name.replace(".", "")


def _grouped_ops() -> list[tuple[str, str, list]]:
    """Return [(bucket, title, [ops...])] in display order (non-empty groups)."""
    ops = [op.to_dict() for op in vocab.all_ops()]
    by_bucket: dict[str, list] = {}
    for d in ops:
        by_bucket.setdefault(d["bucket"], []).append(d)
    seen = set()
    out: list[tuple[str, str, list]] = []
    for bucket, title in BUCKET_TITLES:
        if bucket in by_bucket:
            out.append((bucket, title, by_bucket[bucket]))
            seen.add(bucket)
    for bucket in by_bucket:  # any bucket not in BUCKET_TITLES, appended last
        if bucket not in seen:
            out.append((bucket, bucket.title(), by_bucket[bucket]))
    return out


def _param_row(p: dict) -> str:
    req = "yes" if p["required"] else "no"
    default = "" if p["default"] is None else f"`{p['default']}`"
    choices = f" (one of: {', '.join(p['choices'])})" if p.get("choices") else ""
    return f"| `{p['name']}` | {p['type']} | {req} | {default} | {p['desc']}{choices} |"


def render() -> str:
    L: list[str] = []
    L.append("# Pipeline Vocabulary")
    L.append("")
    L.append(
        "> Generated from `mora02_core.pipeline.vocab` by "
        "`scripts/gen-pipeline-vocab-doc.py`. Do not edit by hand — edit the "
        "registry and regenerate."
    )
    L.append("")
    L.append(
        "The step *ops* a mora02 pipeline is built from, grouped by kind. Each op "
        "has a plain-language line (what it does) and the technical contract "
        "(what it reads/emits, its parameters). A pipeline spec lists steps by op "
        "name; the compiler validates each against this vocabulary and emits a "
        "Lobster workflow. Step outputs are named refs — by default a step's id is "
        "the text before the first dot (`image.generate` → `image`), and a step "
        "reads the previous step's output unless `in:` overrides it."
    )
    L.append("")
    L.append(
        "**Status:** 🟢 `wired` = runnable today · 🟡 `planned` = capability exists "
        "(lib/endpoint) but no pipeline handler yet; the compiler refuses to build a "
        "pipeline that uses it until it is wired."
    )
    L.append("")
    L.append("## Spec constructs (not ops)")
    L.append("")
    L.append(
        "- **`gate`** 🟢 — a pure human pause: `- gate: \"Approve?\"`. Resumes with a "
        "yes/no decision; nothing is sent.\n"
        "- **`review`** 🟢 — human-in-the-loop with delivery: `- review: \"Approve?\"` "
        "sends the previous step's output to a human *type-aware* (image/video/audio/text, "
        "inferred from the prior op's output) **and** pauses for approval. Compiles to a "
        "`notify` sub-step + an input gate; supersedes the manual `notify.image` + `gate` "
        "pattern."
    )
    L.append("")

    groups = _grouped_ops()

    # ---- At a glance: one plain-language table per bucket --------------------
    L.append("## At a glance")
    L.append("")
    for _bucket, title, ops in groups:
        L.append(f"### {title}")
        L.append("")
        L.append("| Op | What it does | Status |")
        L.append("|----|--------------|--------|")
        for d in ops:
            plain = d.get("plain") or d["summary"]
            st = BADGE.get(d["status"], "")
            L.append(f"| [`{d['name']}`](#{_anchor(d['name'])}) | {plain} | {st} |")
        L.append("")

    # ---- Reference: full per-op detail, grouped ------------------------------
    L.append("## Reference")
    L.append("")
    for _bucket, title, ops in groups:
        L.append(f"### {title}")
        L.append("")
        for d in ops:
            L.append(f"#### `{d['name']}` {BADGE.get(d['status'], '')}")
            L.append("")
            if d.get("plain"):
                L.append(d["plain"])
                L.append("")
            L.append(f"*Technical:* {d['summary']}")
            L.append("")
            consumes = d["consumes"] + (" (optional)" if d["consumes_optional"] else "")
            L.append(
                f"- **Default step id:** `{d['default_id']}`  "
                f"\n- **Consumes (stdin):** {consumes} ({d['input_type']})  "
                f"\n- **Emits (stdout):** {d['output_type']}"
            )
            L.append("")
            if d["params"]:
                L.append("| Param | Type | Required | Default | Description |")
                L.append("|-------|------|----------|---------|-------------|")
                for p in d["params"]:
                    L.append(_param_row(p))
            else:
                L.append("_No parameters._")
            L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(vocab.all_ops())} ops)")


if __name__ == "__main__":
    main()
