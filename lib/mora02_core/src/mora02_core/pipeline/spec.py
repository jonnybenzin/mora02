"""mora02_core.pipeline.spec — the native mora02 pipeline format + compiler.

A pipeline SPEC is the author-facing layer of the Nordstern (ADR pending): a
small declarative document that compiles to a Lobster workflow (``.lobster``,
itself JSON) which then runs via the existing :mod:`mora02_core.pipeline` runner.

Why a spec on top of ``.lobster``: hand-writing Lobster means repeating a curl
string, URL-encoding params, threading ``stdin: $step.stdout``, and copying a
``condition:`` onto every step after a gate. The spec removes all of that. Step
outputs are NAMED refs ("refs first-class"); a step declares what it consumes.

The spec JSON is deliberately the COMMON COMPILE TARGET for the rapid-authoring
front-ends (recording / visual builder / LLM dialog) — nobody hand-writes these
by hand; the front-ends all emit this dict, so the compiler + runner are written
once. See the project note ``project_pipeline_authoring_frontends``.

Three inputs, one model:
    load_spec(path)            # a .json or .yaml/.yml file on disk
    load_spec({...})           # an in-memory dict (e.g. emitted by an agent)
    compile_to_lobster(spec)   # PURE: spec -> lobster dict, no IO (tests/inspection)
                               # run_pipeline_spec() (in __init__) writes + runs.

Spec shape (JSON is the documented default; YAML is accepted, being a superset)::

    {
      "name": "image-review",
      "steps": [
        {"llm.image_prompt": {"subject": "a red fox in deep snow at dawn"}},
        {"gate": "Approve this image prompt before generating?"},
        {"image.generate": {"flow": "photo"}},
        {"notify.image": {"target": "+49...", "message": "approve?"}},
        {"gate": "Approve the generated image (check your phone)?"},
        {"clip.generate": {"in": "image", "resolution": "720p", "durations": "3"}}
      ]
    }

Each step is a single-key dict. Key ``"gate"`` is a human-in-the-loop pause;
any other key is a step OP (executed by the script-runner step endpoint). An op
step's value holds its query params, plus two reserved control keys:
  - ``id``: override the step's name (default = the op text before the first dot,
    so ``image.generate`` -> ``image``). Needed only to disambiguate duplicates.
  - ``in``: wire the input ref explicitly to another step's id (default = the
    previous op step). ``"none"`` suppresses stdin for a pure producer that
    happens to not be first. A list (fan-in) is not yet supported by the target.

A param value may also be a step-output REFERENCE ``{"from": "<step id>"}`` instead
of a literal: it pulls that earlier step's output into this specific field at run
time (non-linear fan-in — e.g. ``music.generate`` taking its ``prompt`` from one
LLM step and its ``lyrics`` from another). The ref must point at an earlier step;
it compiles to ``__ref_<param>=<id>`` and is resolved from the run bucket in the
executor (see mora02_core.pipeline.runbucket).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union
from urllib.parse import quote

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.vocab import is_wired, validate_op

# Where a compiled step's curl call is sent. The step endpoint lives in
# script-runner (the executor, ADR-020); override for tests / a moved service.
STEP_BASE_URL = os.environ.get(
    "MORA02_PIPELINE_STEP_BASE", "http://script-runner:8096"
)

# Reserved keys inside an op step's value dict — everything else is a query param.
_CONTROL_KEYS = ("id", "in")


def _is_ref(value: Any) -> bool:
    """A param value that references another step's output: ``{"from": "<id>"}``.

    Non-linear data flow: instead of a literal, a param can pull an earlier step's
    output into a specific field. Kept as a structured object (not a string
    placeholder) so it never collides with literal text and is trivial for the
    authoring front-ends to emit. Compiled to ``__ref_<param>=<id>`` and resolved
    from the run bucket in the executor (see mora02_core.pipeline.runbucket)."""
    return isinstance(value, dict) and "from" in value


def _is_arg(value: Any) -> bool:
    """A param value that references a variable run INPUT: ``{"arg": "<name>"}``.

    The run's ``args`` are seeded into the bucket under ``args.<name>`` at run start,
    so an arg reference resolves on the same ``__ref_`` transport as :func:`_is_ref`
    — one mechanism, two sources (earlier steps + run inputs). May carry a ``default``
    key for the authoring UI; the compiler ignores it."""
    return isinstance(value, dict) and "arg" in value

# Default response schema for a bare ``gate`` (a yes/no approval).
_DEFAULT_GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}},
    "required": ["approved"],
}


# ============================================================================
# Spec model — parsed, validated, in-memory form (the canonical representation)
# ============================================================================


@dataclass(slots=True)
class OpStep:
    """A step that runs an op on the script-runner step endpoint."""

    id: str
    op: str
    params: dict[str, Any] = field(default_factory=dict)
    # Input wiring: None = default to previous op step; "none" = no stdin;
    # a str = that step's id; a list = fan-in (not yet supported by target).
    in_: Union[str, list[str], None] = None


@dataclass(slots=True)
class GateStep:
    """A human-in-the-loop pause; resumes with a decision matching the schema."""

    id: str
    prompt: str
    response_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_GATE_SCHEMA))


@dataclass(slots=True)
class ReviewStep:
    """Human-in-the-loop with delivery: send the previous step's output to a human
    (type-aware, via the ``notify`` op) AND pause for approval.

    Sugar over ``notify`` + ``gate``: the compiler expands it into a notify
    sub-step (id ``<id>_send``, passthrough) followed by an input gate (id
    ``<id>``). ``notify_params`` carries channel/target/message for the send.
    """

    id: str
    prompt: str
    notify_params: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_GATE_SCHEMA))


@dataclass(slots=True)
class PipelineSpec:
    """A parsed pipeline: a name and an ordered list of op/gate/review steps."""

    name: str
    steps: list[Union[OpStep, GateStep, ReviewStep]] = field(default_factory=list)


# ============================================================================
# Loading — dict | JSON file | YAML file -> PipelineSpec
# ============================================================================


def load_spec(src: Union[PipelineSpec, dict, str, Path]) -> PipelineSpec:
    """Load a spec from a PipelineSpec, an in-memory dict, or a .json/.yaml file.

    Raises ``PipelineError`` on a malformed spec (the single error type callers
    already handle). YAML support is optional: a ``.yaml`` path without PyYAML
    installed raises a clear PipelineError rather than a bare ImportError.
    """
    if isinstance(src, PipelineSpec):
        return src
    if isinstance(src, dict):
        return _parse_spec(src)
    if isinstance(src, (str, Path)):
        path = Path(src)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            data = _load_yaml(text, path)
        else:
            try:
                data = json.loads(text)
            except ValueError as e:
                raise PipelineError(f"{path}: invalid JSON: {e}") from e
        if not isinstance(data, dict):
            raise PipelineError(f"{path}: top level must be a mapping, got {type(data).__name__}")
        return _parse_spec(data)
    raise PipelineError(f"cannot load spec from {type(src).__name__}")


def _load_yaml(text: str, path: Path) -> Any:
    try:
        import yaml  # optional dependency; JSON is the default format
    except ModuleNotFoundError as e:
        raise PipelineError(
            f"{path} is YAML but PyYAML is not installed — write the spec as JSON "
            "or `pip install pyyaml`."
        ) from e
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:  # type: ignore[attr-defined]
        raise PipelineError(f"{path}: invalid YAML: {e}") from e


def _parse_spec(data: dict) -> PipelineSpec:
    """Validate a raw mapping and build a PipelineSpec (assigns default ids)."""
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise PipelineError("spec needs a non-empty string 'name'")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PipelineError("spec needs a non-empty 'steps' list")

    steps: list[Union[OpStep, GateStep, ReviewStep]] = [
        _parse_step(i, rs) for i, rs in enumerate(raw_steps)
    ]
    _assign_gate_ids(steps)
    _assign_review_ids(steps)
    _check_unique_ids(steps)
    return PipelineSpec(name=name, steps=steps)


def _parse_step(index: int, raw: Any) -> Union[OpStep, GateStep, ReviewStep]:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise PipelineError(
            f"step {index}: each step is a single-key mapping "
            f"({{op: params}}, {{gate: prompt}} or {{review: prompt}}), got {raw!r}"
        )
    (key, value), = raw.items()

    if key == "gate":
        return _parse_gate(index, value)
    if key == "review":
        return _parse_review(index, value)

    # An op step. Value may be a params dict or null (no params).
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise PipelineError(f"step {index} ({key!r}): value must be a mapping of params")
    step_id = value.get("id") or key.split(".")[0]
    in_ = value.get("in")
    params = {k: v for k, v in value.items() if k not in _CONTROL_KEYS}
    return OpStep(id=str(step_id), op=key, params=params, in_=in_)


def _parse_gate(index: int, value: Any) -> GateStep:
    # Shorthand: a bare string is the prompt. Long form: a dict with prompt,
    # optional id, optional custom responseSchema (alias: schema).
    if isinstance(value, str):
        return GateStep(id="", prompt=value)
    if isinstance(value, dict):
        prompt = value.get("prompt")
        if not prompt or not isinstance(prompt, str):
            raise PipelineError(f"step {index} (gate): needs a string 'prompt'")
        schema = value.get("responseSchema") or value.get("schema") or dict(_DEFAULT_GATE_SCHEMA)
        gate = GateStep(id=str(value["id"]) if value.get("id") else "", prompt=prompt)
        gate.response_schema = schema
        return gate
    raise PipelineError(f"step {index} (gate): value must be a prompt string or a mapping")


def _parse_review(index: int, value: Any) -> ReviewStep:
    # Shorthand: a bare string is the prompt (used for both the gate and the
    # notify caption). Long form: a dict with prompt + optional id, target,
    # channel, message, responseSchema.
    if isinstance(value, str):
        prompt = value
        cfg: dict[str, Any] = {}
    elif isinstance(value, dict):
        prompt = value.get("prompt")
        if not prompt or not isinstance(prompt, str):
            raise PipelineError(f"step {index} (review): needs a string 'prompt'")
        cfg = value
    else:
        raise PipelineError(f"step {index} (review): value must be a prompt string or a mapping")

    # The notify sub-step carries delivery params; default its caption to the
    # prompt so the human sees context alongside the media.
    notify_params: dict[str, Any] = {"message": cfg.get("message") or prompt}
    for k in ("target", "channel"):
        if cfg.get(k):
            notify_params[k] = cfg[k]
    review = ReviewStep(id=str(cfg["id"]) if cfg.get("id") else "", prompt=prompt)
    review.notify_params = notify_params
    review.response_schema = cfg.get("responseSchema") or cfg.get("schema") or dict(_DEFAULT_GATE_SCHEMA)
    return review


def _assign_gate_ids(steps: list[Union[OpStep, GateStep, ReviewStep]]) -> None:
    """Name unnamed gates: a single gate -> 'gate', multiple -> gate1, gate2, …."""
    gates = [s for s in steps if isinstance(s, GateStep)]
    multiple = len(gates) > 1
    for i, g in enumerate(gates, 1):
        if not g.id:
            g.id = f"gate{i}" if multiple else "gate"


def _assign_review_ids(steps: list[Union[OpStep, GateStep, ReviewStep]]) -> None:
    """Name unnamed reviews: a single review -> 'review', multiple -> review1, …."""
    reviews = [s for s in steps if isinstance(s, ReviewStep)]
    multiple = len(reviews) > 1
    for i, r in enumerate(reviews, 1):
        if not r.id:
            r.id = f"review{i}" if multiple else "review"


def _check_unique_ids(steps: list[Union[OpStep, GateStep, ReviewStep]]) -> None:
    seen: set[str] = set()
    for s in steps:
        if s.id in seen:
            raise PipelineError(
                f"duplicate step id {s.id!r} — add an explicit 'id' to disambiguate"
            )
        seen.add(s.id)


# ============================================================================
# Compiler — PipelineSpec -> Lobster workflow dict (PURE, no IO)
# ============================================================================


def compile_to_lobster(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Compile a spec to a Lobster workflow dict. Pure — no filesystem, no runner.

    Inference rules (derived from the Increment 1-3 spikes):
      - stdin: an op step reads the previous op step's stdout by default; ``in:``
        overrides the source, ``in: "none"`` suppresses it (a producer).
      - condition: every step after a gate carries ``$<lastGate>.response.approved``
        (the most recent gate only — matching the spike behaviour).
      - run: a fully-formed ``curl -fsS`` POST to the step endpoint with params
        URL-encoded and ``fmt=out`` appended; ``--data-binary @-`` when it has stdin.

    When ``run_id`` is given, ``run_id`` and the step's ``step_id`` are baked into
    every step's curl query so the step endpoint can correlate its per-step log
    lines to the run (see runlog). Omitting ``run_id`` (tests / inspection) leaves
    the output byte-identical to a plain compile.
    """
    spec = load_spec(spec)

    out_steps: list[dict[str, Any]] = []
    defined_ids: set[str] = set()
    last_op_id: str | None = None
    last_gate_id: str | None = None

    for step in spec.steps:
        if isinstance(step, GateStep):
            out_steps.append(
                {
                    "id": step.id,
                    "input": {"prompt": step.prompt, "responseSchema": step.response_schema},
                }
            )
            defined_ids.add(step.id)
            last_gate_id = step.id
            continue

        if isinstance(step, ReviewStep):
            # Expand to: notify sub-step (send prev output, type-aware passthrough)
            # then an input gate. Subsequent steps gate on $<review.id>.response.approved.
            if not is_wired("notify"):
                raise PipelineError("review needs the 'notify' op, which is not wired")
            send_id = f"{step.id}_send"
            if send_id in defined_ids:
                raise PipelineError(
                    f"review {step.id!r}: generated id {send_id!r} collides with an existing step"
                )
            send: dict[str, Any] = {"id": send_id}
            if last_op_id is not None:
                send["stdin"] = f"${last_op_id}.stdout"
            if last_gate_id is not None:
                send["condition"] = f"${last_gate_id}.response.approved"
            send["run"] = _build_run(
                "notify", step.notify_params, has_stdin=last_op_id is not None,
                run_id=run_id, step_id=send_id,
            )
            out_steps.append(send)
            defined_ids.add(send_id)
            last_op_id = send_id  # passthrough: downstream chains from the sent ref

            out_steps.append(
                {
                    "id": step.id,
                    "input": {"prompt": step.prompt, "responseSchema": step.response_schema},
                }
            )
            defined_ids.add(step.id)
            last_gate_id = step.id
            continue

        ref_params = {k: v["from"] for k, v in step.params.items() if _is_ref(v)}
        arg_params = {k: v["arg"] for k, v in step.params.items() if _is_arg(v)}
        literal_params = {
            k: v for k, v in step.params.items() if not _is_ref(v) and not _is_arg(v)
        }
        validate_op(step.op, literal_params, ref_params=set(ref_params) | set(arg_params))
        if not is_wired(step.op):
            raise PipelineError(
                f"op {step.op!r} is in the vocabulary but not implemented yet "
                "(status: planned) — it cannot be compiled into a runnable pipeline. "
                "Build its handler first."
            )
        # A step-output reference must point at an EARLIER-defined step (the bucket
        # only holds outputs of steps that already ran).
        for pname, src in ref_params.items():
            if not isinstance(src, str) or not src:
                raise PipelineError(
                    f"step {step.id!r}: param {pname!r} 'from' must be a step id string"
                )
            if src not in defined_ids:
                raise PipelineError(
                    f"step {step.id!r}: param {pname!r} refers to unknown or later "
                    f"step id {src!r}"
                )
        # An arg reference just needs a non-empty name; its value is seeded into the
        # bucket at run start (args.<name>), so it is always available.
        for pname, an in arg_params.items():
            if not isinstance(an, str) or not an:
                raise PipelineError(
                    f"step {step.id!r}: param {pname!r} 'arg' must be a name string"
                )
        # Fan-in on the input side: `in: [a, b, c]` collects several earlier steps'
        # outputs into a "many"-consuming op (e.g. clip.generate). Lobster can't pipe
        # multiple stdouts into one stdin, so the collect is resolved from the run
        # bucket in the executor — the compiled step carries `__collect=a,b,c`.
        collect_ids = None
        if isinstance(step.in_, list):
            for cid in step.in_:
                if cid not in defined_ids:
                    raise PipelineError(
                        f"step {step.id!r}: in-list refers to unknown or later step {cid!r}"
                    )
            collect_ids = list(step.in_)
            source_id = None
        else:
            source_id = _resolve_source(step, last_op_id, defined_ids)
        compiled: dict[str, Any] = {"id": step.id}
        if source_id is not None:
            compiled["stdin"] = f"${source_id}.stdout"
        if last_gate_id is not None:
            compiled["condition"] = f"${last_gate_id}.response.approved"
        compiled["run"] = _build_run(
            step.op, step.params, has_stdin=source_id is not None,
            run_id=run_id, step_id=step.id, collect=collect_ids,
        )

        out_steps.append(compiled)
        defined_ids.add(step.id)
        last_op_id = step.id

    return {"name": spec.name, "steps": out_steps}


def _resolve_source(step: OpStep, last_op_id: str | None, defined_ids: set[str]) -> str | None:
    """Resolve an op step's input source id (or None for no stdin)."""
    in_ = step.in_
    if isinstance(in_, list):
        raise PipelineError(
            f"step {step.id!r}: fan-in (in: [..]) is not yet supported by the Lobster "
            "target — wire a single source for now"
        )
    if in_ == "none":
        return None
    if isinstance(in_, str):
        if in_ not in defined_ids:
            raise PipelineError(
                f"step {step.id!r}: in:{in_!r} refers to an unknown or later step"
            )
        return in_
    # Default: chain from the previous op step (None if this is the first one).
    return last_op_id


def _build_run(
    op: str,
    params: dict[str, Any],
    *,
    has_stdin: bool,
    run_id: str | None = None,
    step_id: str | None = None,
    collect: list[str] | None = None,
) -> str:
    """Build the curl command for one op step (params URL-encoded, fmt=out).

    A param whose value is a step-output reference (``{"from": "<id>"}``) is emitted
    in the reserved ``__ref_<param>=<id>`` namespace — a short placeholder the
    executor expands from the run bucket before calling the handler (the real, and
    possibly large, value never travels in the URL).
    """
    pairs = []
    for k, v in params.items():
        if _is_ref(v):
            pairs.append(f"__ref_{quote(str(k), safe='')}={quote(str(v['from']), safe='')}")
        elif _is_arg(v):
            pairs.append(f"__ref_{quote(str(k), safe='')}={quote('args.' + str(v['arg']), safe='')}")
        else:
            pairs.append(f"{quote(str(k), safe='')}={quote(str(v), safe='')}")
    pairs.append("fmt=out")
    if collect:
        pairs.append("__collect=" + quote(",".join(collect), safe=","))
    if run_id:
        pairs.append(f"run_id={quote(run_id, safe='')}")
        pairs.append(f"step_id={quote(str(step_id), safe='')}")
    url = f"{STEP_BASE_URL}/pipeline/step/{op}?" + "&".join(pairs)
    run = f"curl -fsS -X POST '{url}'"
    if has_stdin:
        run += " --data-binary @-"
    return run
