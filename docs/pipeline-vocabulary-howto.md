# How to: query and extend the pipeline vocabulary

The pipeline **vocabulary** is the set of step *ops* a pipeline is built from. It
has one source of truth — the registry in
`lib/mora02_core/src/mora02_core/pipeline/vocab.py` — and several views derived
from it. Extending it is **100% local** (no cloud, no Claude): the deterministic
`scripts/add-vocab.py` is the primitive; any future authoring front-end (a local
OpenClaw agent, a local-qwen dialog, a visual builder) sits *on top* of it.

## Query — three views, one source

| View | For | Command / location |
|------|-----|--------------------|
| Terminal CLI | rapid lookup | `scripts/vocab.py` |
| Markdown reference | reading | `docs/pipeline-vocabulary.md` (generated) |
| JSON over HTTP | front-ends / machines | `GET http://mora02.local:8096/pipeline/ops` |

```bash
scripts/vocab.py list                 # every op, one line each
scripts/vocab.py list --planned       # only not-yet-built ops
scripts/vocab.py list --bucket audio  # filter by service bucket
scripts/vocab.py show tts.speak       # full detail: summary, params, types
scripts/vocab.py search baserow       # full-text over name/summary/bucket
scripts/vocab.py <cmd> --json         # machine-readable
```

## Op status

- 🟢 **wired** — a handler exists in `apps/script-runner/app/main.py`
  (`_PIPELINE_STEPS`); runnable today.
- 🟡 **planned** — the capability exists as a lib/endpoint, but no pipeline
  handler yet. It is in the vocabulary as a contract/menu; the compiler refuses
  to build a pipeline that uses it until it is wired.

## Add a new vocab op — the structure

A vocab op has **two halves**. Only the first is auto-scaffolded; the second is
real code (it calls your service), so the tool prints a ready stub for it.

1. **Declaration** (metadata) — the `Op(...)` entry in `vocab.py`. Fully
   scriptable.
2. **Handler** (the code that does the work) — a function in script-runner.

### Step 1: scaffold the declaration (local, deterministic)

```bash
scripts/add-vocab.py                        # interactive interview
scripts/add-vocab.py --json-file spec.json  # non-interactive (automation/agent)
scripts/add-vocab.py --json '{...}'         # inline spec
scripts/add-vocab.py ... --dry-run          # render + validate, write nothing
```

It appends the `Op(...)` entry to `vocab.py` (at the `add-vocab` marker) as
`status="planned"`, regenerates `docs/pipeline-vocabulary.md`, and prints the
handler stub plus the promotion steps. The op is now in the dictionary,
documented, and visible to front-ends — but not yet runnable.

JSON spec shape (for the non-interactive / automation path):

```json
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
```

### Step 2: promote planned → wired (the manual half)

1. Paste the printed stub `_step_<name>(inputs, params)` into
   `apps/script-runner/app/main.py` and implement it — call your service/lib,
   return `{"ok": True, "op": "<name>", "out": <ref-or-text>, "type": "<wire-type>"}`.
   The step contract (stdin = newline-separated input refs/values, params = query
   string, `out` = the single stdout string) is in the "PIPELINE STEP VOCABULARY"
   section header of `main.py`.
2. Register it in the `_PIPELINE_STEPS` dict.
3. Set `status="wired"` on the `Op` in `vocab.py`, run
   `python3 scripts/gen-pipeline-vocab-doc.py`, and rebuild script-runner.

The startup **drift guard** asserts wired ops == registered handlers, so a
mismatch is logged loudly on the next deploy.

## Future: agent-driven authoring (local)

`scripts/add-vocab.py` takes a JSON spec, so a **local** OpenClaw agent (or a
local-qwen dialog) can drive it — "describe the new feature" → JSON → script. The
same primitive is the intended target for agent-driven *pipeline* creation
(emitting the pipeline JSON the compiler consumes). The deterministic script
stays the floor; the LLM layer over it is always optional and always local.
