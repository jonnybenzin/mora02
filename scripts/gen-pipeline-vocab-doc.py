#!/usr/bin/env python3
"""Generate docs/pipeline-vocabulary.md from the pipeline op registry.

The vocabulary is single-source-of-truth in mora02_core.pipeline.vocab; this
renders the human-readable reference from it. Re-run after changing an op:

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


def _param_row(p: dict) -> str:
    req = "yes" if p["required"] else "no"
    default = "" if p["default"] is None else f"`{p['default']}`"
    choices = f" (one of: {', '.join(p['choices'])})" if p.get("choices") else ""
    return f"| `{p['name']}` | {p['type']} | {req} | {default} | {p['desc']}{choices} |"


def render() -> str:
    lines: list[str] = []
    lines.append("# Pipeline Vocabulary")
    lines.append("")
    lines.append(
        "> Generated from `mora02_core.pipeline.vocab` by "
        "`scripts/gen-pipeline-vocab-doc.py`. Do not edit by hand — edit the "
        "registry and regenerate."
    )
    lines.append("")
    lines.append(
        "The step *ops* a mora02 pipeline is built from. A pipeline spec lists "
        "steps by op name; the compiler validates each against this vocabulary "
        "and emits a Lobster workflow. Step outputs are named refs — by default a "
        "step's id is the text before the first dot (`image.generate` → `image`), "
        "and a step reads the previous op step's output unless `in:` overrides it."
    )
    lines.append("")
    lines.append(
        "**Status:** 🟢 `wired` = runnable today · 🟡 `planned` = capability exists "
        "(lib/endpoint) but no pipeline handler yet; the compiler refuses to build a "
        "pipeline that uses it until it is wired."
    )
    lines.append("")
    lines.append("## Spec constructs (not ops)")
    lines.append("")
    lines.append(
        "- **`gate`** 🟢 — a pure human pause: `- gate: \"Approve?\"`. Resumes with a "
        "yes/no decision; nothing is sent.\n"
        "- **`review`** 🟢 — human-in-the-loop with delivery: `- review: \"Approve?\"` "
        "sends the previous step's output to a human *type-aware* (image/video/audio/text, "
        "inferred from the prior op's output) **and** pauses for approval. Compiles to a "
        "`notify` sub-step + an input gate; supersedes the manual `notify.image` + `gate` "
        "pattern."
    )
    lines.append("")
    lines.append("## Ops by bucket")
    lines.append("")
    lines.append("| Op | Status | Bucket | Default id | Consumes | Input | Output |")
    lines.append("|----|--------|--------|-----------|----------|-------|--------|")
    badge = {"wired": "🟢", "planned": "🟡"}
    for op in vocab.all_ops():
        d = op.to_dict()
        consumes = d["consumes"] + (" (opt)" if d["consumes_optional"] else "")
        st = f"{badge.get(d['status'], '')} {d['status']}"
        lines.append(
            f"| [`{d['name']}`](#{d['name'].replace('.', '')}) | {st} | {d['bucket']} "
            f"| `{d['default_id']}` | {consumes} | {d['input_type']} | {d['output_type']} |"
        )
    lines.append("")

    for op in vocab.all_ops():
        d = op.to_dict()
        lines.append(f"## {d['name']}")
        lines.append("")
        lines.append(f"{badge.get(d['status'], '')} **{d['status']}** · bucket: `{d['bucket']}`")
        lines.append("")
        lines.append(d["summary"])
        lines.append("")
        consumes = d["consumes"] + (" (optional)" if d["consumes_optional"] else "")
        lines.append(
            f"- **Default step id:** `{d['default_id']}`  "
            f"\n- **Consumes (stdin):** {consumes} ({d['input_type']})  "
            f"\n- **Emits (stdout):** {d['output_type']}"
        )
        lines.append("")
        if d["params"]:
            lines.append("| Param | Type | Required | Default | Description |")
            lines.append("|-------|------|----------|---------|-------------|")
            for p in d["params"]:
                lines.append(_param_row(p))
        else:
            lines.append("_No parameters._")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(vocab.all_ops())} ops)")


if __name__ == "__main__":
    main()
