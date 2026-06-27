#!/usr/bin/env python3
"""add-vocab — scaffold a new pipeline vocabulary op. 100% local, no LLM, no cloud.

This is the deterministic primitive for extending the vocabulary. It does the
boilerplate half (the declaration) and prints the manual half (the handler stub).
Authoring front-ends (a local OpenClaw agent, a local-qwen dialog, a visual
builder) can sit ON TOP of this script later — but the script never needs any of
them, and never calls Claude/cloud.

What it does:
  - appends an Op(...) entry to mora02_core.pipeline.vocab as status="planned"
    (inserted at the add-vocab marker in vocab.py),
  - regenerates docs/pipeline-vocabulary.md,
  - prints a ready-to-paste handler stub + the 3 promotion steps.

What it does NOT do: write the handler into script-runner (that is real code —
the manual half). It prints the stub so you paste it where it belongs.

Usage:
  scripts/add-vocab.py                          # interactive interview
  scripts/add-vocab.py --json-file spec.json    # non-interactive (automation)
  scripts/add-vocab.py --json '{...}'           # inline spec
  scripts/add-vocab.py ... --dry-run            # render + validate, write nothing

JSON spec shape:
  {
    "name": "subtitle.burn",
    "summary": "Burn subtitles into a video.",
    "bucket": "media",
    "consumes": "one", "consumes_optional": false,
    "input_type": "video", "output_type": "video",
    "params": [
      {"name": "srt", "type": "string", "required": true, "desc": "subtitle file ref"},
      {"name": "style", "type": "enum", "default": "plain", "choices": ["plain", "box"]}
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VOCAB = REPO / "lib" / "mora02_core" / "src" / "mora02_core" / "pipeline" / "vocab.py"
GEN = REPO / "scripts" / "gen-pipeline-vocab-doc.py"
MARKER = "# <<< add-vocab: scripts/add-vocab.py inserts new Op() entries above this line >>>"

sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))
from mora02_core.pipeline import vocab as _vocab  # noqa: E402

_WIRE = ("image", "video", "audio", "text", "any")
_CONSUMES = ("none", "one", "many")


# --------------------------------------------------------------------------- #
# Spec gathering
# --------------------------------------------------------------------------- #

def _ask(prompt: str, default: str = "", choices: tuple[str, ...] | None = None) -> str:
    hint = f" [{default}]" if default else ""
    if choices:
        hint = f" ({'/'.join(choices)})" + hint
    while True:
        val = input(f"{prompt}{hint}: ").strip() or default
        if choices and val not in choices:
            print(f"  -> must be one of {choices}")
            continue
        return val


def interview() -> dict:
    print("New vocab op (Ctrl-C to abort). Name as service.action, e.g. subtitle.burn\n")
    spec: dict = {}
    spec["name"] = _ask("op name")
    spec["summary"] = _ask("one-line summary")
    spec["bucket"] = _ask("bucket (service family)", default=spec["name"].split(".")[0])
    spec["consumes"] = _ask("consumes (stdin cardinality)", default="none", choices=_CONSUMES)
    if spec["consumes"] != "none":
        spec["consumes_optional"] = _ask("stdin optional?", default="no", choices=("yes", "no")) == "yes"
        spec["input_type"] = _ask("input type", default="any", choices=_WIRE)
    spec["output_type"] = _ask("output type", default="text", choices=_WIRE)
    params = []
    print("\nParams (blank name to finish):")
    while True:
        pname = input("  param name: ").strip()
        if not pname:
            break
        p: dict = {"name": pname}
        ptype = _ask("    type", default="string", choices=("string", "int", "bool", "enum"))
        if ptype != "string":
            p["type"] = ptype
        if ptype == "enum":
            p["choices"] = [c.strip() for c in _ask("    choices (comma)").split(",") if c.strip()]
        if _ask("    required?", default="no", choices=("yes", "no")) == "yes":
            p["required"] = True
        default = input("    default (blank=none): ").strip()
        if default:
            p["default"] = default
        desc = input("    desc: ").strip()
        if desc:
            p["desc"] = desc
        params.append(p)
    spec["params"] = params
    return spec


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _s(value) -> str:
    """A Python string literal (double-quoted, properly escaped)."""
    return json.dumps(value, ensure_ascii=False)


def render_param(p: dict) -> str:
    args = [_s(p["name"])]
    if p.get("type", "string") != "string":
        args.append(f"type={_s(p['type'])}")
    if p.get("required"):
        args.append("required=True")
    if p.get("default") is not None:
        args.append(f"default={_s(str(p['default']))}")
    if p.get("choices"):
        inner = ", ".join(_s(c) for c in p["choices"])
        args.append(f"choices=({inner},)")
    if p.get("desc"):
        args.append(f"desc={_s(p['desc'])}")
    return f"            Param({', '.join(args)}),"


def render_op(spec: dict) -> str:
    lines = ["    Op("]
    lines.append(f"        name={_s(spec['name'])},")
    lines.append(f"        summary={_s(spec['summary'])},")
    lines.append(f"        bucket={_s(spec.get('bucket', ''))},")
    lines.append('        status="planned",')
    params = spec.get("params") or []
    if params:
        lines.append("        params=(")
        lines += [render_param(p) for p in params]
        lines.append("        ),")
    lines.append(f"        consumes={_s(spec.get('consumes', 'none'))},")
    if spec.get("consumes_optional"):
        lines.append("        consumes_optional=True,")
    if spec.get("consumes", "none") != "none":
        lines.append(f"        input_type={_s(spec.get('input_type', 'any'))},")
    lines.append(f"        output_type={_s(spec.get('output_type', 'text'))},")
    lines.append("    ),")
    return "\n".join(lines)


def render_handler_stub(spec: dict) -> str:
    name = spec["name"]
    fn = "_step_" + name.replace(".", "_")
    out_type = spec.get("output_type", "text")
    return f'''async def {fn}(inputs: List[str], params: dict) -> dict:
    """{name} — {spec['summary']}"""
    # TODO: implement. Read stdin values from `inputs` (newline-separated refs/
    # values), read step params from `params`, do the work, return one `out`
    # string (an asset ref for media, or a text value).
    raise NotImplementedError("{name} not implemented yet")
    return {{"ok": True, "op": "{name}", "out": ..., "type": "{out_type}"}}'''


# --------------------------------------------------------------------------- #
# Validation + write
# --------------------------------------------------------------------------- #

def validate(spec: dict) -> None:
    if not spec.get("name"):
        raise SystemExit("error: name is required")
    if _vocab.get_op(spec["name"]) is not None:
        raise SystemExit(f"error: op {spec['name']!r} already exists in the vocabulary")
    if not spec.get("summary"):
        raise SystemExit("error: summary is required")
    if spec.get("consumes", "none") not in _CONSUMES:
        raise SystemExit(f"error: consumes must be one of {_CONSUMES}")
    # Prove the rendered Op source is valid Python that builds an Op.
    ns: dict = {"Op": _vocab.Op, "Param": _vocab.Param}
    try:
        eval(render_op(spec).strip().rstrip(","), ns)  # noqa: S307 - trusted, self-rendered
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"error: rendered Op is invalid: {e}")


def insert_op(op_src: str) -> None:
    text = VOCAB.read_text(encoding="utf-8")
    if MARKER not in text:
        raise SystemExit(f"error: insert marker not found in {VOCAB}")
    marker_line = next(ln for ln in text.splitlines() if MARKER in ln)
    text = text.replace(marker_line, op_src + "\n" + marker_line, 1)
    VOCAB.write_text(text, encoding="utf-8")


def regenerate_doc() -> None:
    subprocess.run([sys.executable, str(GEN)], check=True)


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new pipeline vocab op (local-only).")
    ap.add_argument("--json", help="inline JSON spec")
    ap.add_argument("--json-file", help="path to a JSON spec file")
    ap.add_argument("--dry-run", action="store_true", help="render + validate, write nothing")
    args = ap.parse_args()

    if args.json:
        spec = json.loads(args.json)
    elif args.json_file:
        spec = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    else:
        spec = interview()

    validate(spec)
    op_src = render_op(spec)
    stub = render_handler_stub(spec)

    print("\n--- Op (planned) to be added to vocab.py ---\n")
    print(op_src)
    print("\n--- handler stub to paste into apps/script-runner/app/main.py ---\n")
    print(stub)

    if args.dry_run:
        print("\n[dry-run] valid; nothing written.")
        return 0

    insert_op(op_src)
    regenerate_doc()
    print(f"\n✓ added {spec['name']!r} to the vocabulary (status: planned) + regenerated docs.")
    print("\nTo make it runnable (promotion):")
    print("  1. paste the handler stub above into main.py and implement it")
    print(f"  2. register it in _PIPELINE_STEPS: {spec['name']!r}: {'_step_' + spec['name'].replace('.', '_')}")
    print(f"  3. set status=\"wired\" on the {spec['name']!r} Op in vocab.py, regenerate, rebuild script-runner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
