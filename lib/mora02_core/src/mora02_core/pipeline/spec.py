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
    happens to not be first. A list is fan-in: several earlier steps collected
    into one "many"-consuming op, in the order written.

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
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Union
from urllib.parse import quote

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.vocab import get_op, is_wired, validate_op

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
    # a str = that step's id; a list = fan-in, collected in the order written.
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


# A flow name doubles as its file name, so it has to survive both a file system
# and a URL. Owned by the library: the HTTP door and the MCP door both build a
# path from it, and a rule with two copies is a rule with two versions.
FLOW_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
FLOW_NAME_RULE = "flow name must be 2-64 chars of lowercase letters, digits and dashes"


class BadFlowName(PipelineError):
    """The name cannot become a file name (or a URL)."""


class FlowExists(PipelineError):
    """A flow of that name is in the library and overwrite was not asked for."""


def specs_dir() -> Path:
    """Where the flows SHIPPED with the platform live (tracked in git)."""
    return Path(os.environ.get("MORA02_PIPELINE_SPECS_DIR", "/data/pipelines/specs"))


def local_specs_dir() -> Path:
    """Where the flows of THIS installation live.

    The same split the agents have (agents/ shipped, data/agents/ local): the
    builder saves here and only here, the shipped set changes through git, and
    a local flow with a shipped flow's name wins. Inside the pipelines mount
    next to logs/ and bucket/, so it needs no extra mount; gitignored like them.
    """
    return Path(os.environ.get("MORA02_PIPELINE_SPECS_LOCAL_DIR", "/data/pipelines/local/specs"))


def spec_dirs() -> list[Path]:
    """The library's directories in precedence order: local first, then shipped."""
    return [local_specs_dir(), specs_dir()]


def spec_source(path: Path) -> str:
    """``"local"`` or ``"shipped"`` for a flow file the library returned."""
    return "local" if Path(path).parent == local_specs_dir() else "shipped"


def list_specs() -> list[tuple[Path, dict]]:
    """Every readable flow file, as (path, raw dict), sorted by name.

    Both directories, local before shipped; a name present in both is listed
    once, from the local one.

    Four independent readers of this directory existed -- two HTTP endpoints,
    the op-usage scan and the MCP tool -- each with its own copy of the env
    variable and its own guard against a broken file. The guards had already
    drifted: only one of them checked that a file which PARSES is actually an
    object, so a spec containing a bare list crashed two of the four (review 3,
    2026-09-04).

    A file that cannot be read, or does not hold an object, is skipped: a
    broken spec hides itself and must not hide the others.
    """
    out: list[tuple[Path, dict]] = []
    seen: set[str] = set()
    for root in spec_dirs():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            if path.stem in seen:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                out.append((path, data))
                seen.add(path.stem)
    return sorted(out, key=lambda pd: pd[0].stem)


def resolve_spec_path(name: str) -> Path | None:
    """The file a flow name refers to, trying it bare then .json/.yaml/.yml.

    Written twice before, once with pathlib and once with os.path, and the two
    sanitised the incoming name differently.
    """
    leaf = os.path.basename(str(name))
    for root in spec_dirs():
        base = root / leaf
        cands = [base] if base.suffix else [base.with_suffix(e) for e in (".json", ".yaml", ".yml")]
        hit = next((p for p in cands if p.is_file()), None)
        if hit is not None:
            return hit
    return None


def check_flow(data: dict) -> tuple[list[str], list[str]]:
    """Everything the library would refuse a flow for, and what it would warn about.

    ``(problems, warnings)``: an empty ``problems`` means the flow saves and
    loads back. The checks are the save endpoint's, gathered in one place so
    the two doors (HTTP, MCP) and an author asking "is this right yet" get the
    same answer - and as many answers at once as the shape allows, because a
    model fixing one error per round is a model that gives up after three.
    Warnings do not block saving: an op that is planned but not wired may be
    authored ahead of its handler; it is compiling that refuses to run it.
    """
    problems: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["the flow must be a JSON object with a \"steps\" list"], warnings
    try:
        parsed = load_spec(data)
    except PipelineError as e:
        return [str(e)], warnings
    for check, what in ((check_references, "wiring"), (check_wire_types, "wiring")):
        try:
            check(parsed)
        except PipelineError as e:
            problems.append(f"{what}: {e}")
    for st in parsed.steps:
        if not isinstance(st, OpStep):
            continue
        refs = {k for k, v in st.params.items() if isinstance(v, dict) and ("from" in v or "arg" in v)}
        literal = {k: v for k, v in st.params.items() if k not in refs}
        try:
            validate_op(st.op, literal, ref_params=refs)
        except PipelineError as e:
            problems.append(f"step {st.id!r}: {e}")
            continue
        if not is_wired(st.op):
            warnings.append(f"step {st.id!r}: op {st.op!r} is planned, not runnable yet - "
                            "the flow can be saved but not run")
    return problems, warnings


def _mkdir_owned(path: Path) -> None:
    """Create a directory (and parents), owned like the nearest existing parent.

    The service runs as root in its container; a directory it creates would be
    root:root on the host, and the person whose checkout this is could neither
    edit nor delete what lands in it. Portable, no uid in any config.
    """
    missing: list[Path] = []
    cur = path
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    if not missing:
        return
    st = cur.stat()
    for d in reversed(missing):
        d.mkdir()
        try:
            os.chown(d, st.st_uid, st.st_gid)
            os.chmod(d, 0o775)
        except OSError:
            pass


def save_flow(name: str, data: dict, *, overwrite: bool = False) -> dict:
    """Write an authored flow to this installation's library, checked first.

    The whole spec is parsed and checked against the vocabulary BEFORE anything
    touches disk, so the library can never hold a flow that fails to load back.
    Raises BadFlowName, FlowExists, or PipelineError with every problem found.
    Saves to the local directory only: the shipped set changes through git, and
    a local flow with a shipped flow's name shadows it - that is what
    ``overwrite`` means for a shipped flow, the file in git stays as it is.
    """
    if not isinstance(name, str) or not FLOW_NAME_RE.fullmatch(name):
        raise BadFlowName(FLOW_NAME_RULE)
    if not isinstance(data, dict):
        raise PipelineError("spec must be a JSON object")
    data = dict(data)
    data["name"] = name  # the name is the authority; it keeps file and spec from drifting
    problems, _ = check_flow(data)
    if problems:
        raise PipelineError("invalid spec: " + "; ".join(problems))
    # Write the implicit wiring down before it reaches disk. A step without
    # `in:` takes the previous step's output, which is invisible in the file
    # and in the builder - fine in a straight chain, silently wrong the moment
    # a flow has two branches.
    data = materialize_wiring(data)
    data.setdefault("description", "")
    data.setdefault("tags", [])
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    specs = local_specs_dir()
    _mkdir_owned(specs)
    target = specs / f"{name}.json"
    existed = resolve_spec_path(name) is not None
    if existed and not overwrite:
        raise FlowExists(f"flow {name!r} already exists - pass overwrite to replace it")
    # Through a temp file, so a crash mid-write cannot leave a half spec that
    # the library would then skip as unparsable.
    tmp = target.with_name(f".{name}.json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    try:
        st = specs.stat()
        os.chown(target, st.st_uid, st.st_gid)
        os.chmod(target, 0o664)
    except OSError:
        pass
    steps = len(data.get("steps", []))
    return {
        "ok": True, "name": name, "file": target.name, "source": "local",
        "steps": steps, "replaced": existed, "updated": data["updated"],
    }


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
    # The name becomes a file name when the spec is compiled. The save door and
    # the name door applied this rule; the inline-spec door did not, and a name
    # of "../x" wrote the compiled file outside the workspace (review 4).
    if not FLOW_NAME_RE.fullmatch(name):
        raise PipelineError(f"spec name {name!r}: {FLOW_NAME_RULE}")
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
        # A schema that is not an object passed every check, was saved, and
        # crashed the compiler with an AttributeError (review 4).
        if not isinstance(schema, dict):
            raise PipelineError(f"step {index} (gate): schema must be an object, got {type(schema).__name__}")
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
    if not isinstance(review.response_schema, dict):
        raise PipelineError(f"step {index} (review): schema must be an object, "
                            f"got {type(review.response_schema).__name__}")
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


def spec_to_dict(spec: Union[PipelineSpec, dict, str, Path]) -> dict[str, Any]:
    """Serialise a parsed spec back to the mapping form a spec file holds.

    Round-trips through :func:`load_spec`. Needed because a run has to be able to
    say what it actually ran: the run log keeps the spec itself, not just its
    name, so a later partial re-run plans against the version that ran rather
    than against a library file somebody has edited since.
    """
    loaded = load_spec(spec)
    steps: list[dict[str, Any]] = []
    for st in loaded.steps:
        if isinstance(st, GateStep):
            steps.append({"gate": {"id": st.id, "prompt": st.prompt,
                                   "schema": st.response_schema}})
        elif isinstance(st, ReviewStep):
            steps.append({"review": {"id": st.id, "prompt": st.prompt,
                                     "schema": st.response_schema,
                                     **st.notify_params}})
        else:
            body: dict[str, Any] = {"id": st.id}
            if st.in_ is not None:
                body["in"] = st.in_
            body.update(st.params)
            steps.append({st.op: body})
    return {"name": loaded.name, "steps": steps}


# ============================================================================
# Wiring — which step feeds which (the spec's edges, made explicit)
# ============================================================================


@dataclass(slots=True)
class StepWiring:
    """Where one COMPILED step gets its inputs from.

    A spec leaves most edges implicit: an op step without ``in:`` reads whatever
    op ran before it. That rule used to exist only as bookkeeping inside the
    compiler loop, so nothing but the compiler could see the graph. It lives
    here now and the compiler is merely its first consumer — selective re-runs
    and a canvas view need the same answer.

    ``step_id`` matches a compiled step 1:1, including the ``<review>_send``
    sub-step a review expands into: that is a real node in the compiled output.
    """

    step_id: str
    # stdin producer — whose stdout is piped in (None = this step reads nothing).
    source: str | None = None
    # Fan-in: several earlier steps collected into a "many"-consuming op.
    collect: list[str] | None = None
    # Param name -> step id, from ``{"from": "<id>"}`` references.
    refs: dict[str, str] = field(default_factory=dict)
    # The gate whose approval this step waits on (the most recent one).
    gate: str | None = None
    # GATES ONLY: the step whose result this gate is judging. Not an input — a
    # gate has no stdin — but it IS a dependency: re-make the image and the
    # approval given for the old one is worthless.
    reviews: str | None = None

    @property
    def depends_on(self) -> set[str]:
        """The steps whose OUTPUT this one is made of — "what goes stale if X changes?".

        ``gate`` is deliberately NOT in here. A gate is control flow: it decides
        WHETHER a step runs, not what the step produces. Re-asking an approval
        because the image changed must not invalidate the song, which never
        looked at the image.
        """
        deps = set(self.refs.values())
        if self.source:
            deps.add(self.source)
        if self.reviews:
            deps.add(self.reviews)
        if self.collect:
            deps.update(self.collect)
        return deps


def resolve_wiring(spec: Union[PipelineSpec, dict, str, Path]) -> list[StepWiring]:
    """Resolve every implicit edge in a spec into named step ids.

    Pure resolution, deliberately WITHOUT validation: it reports the wiring a
    spec asks for even when an id does not exist. :func:`compile_to_lobster`
    keeps its own checks in their original order — this removes the duplicated
    bookkeeping, not the diagnostics.

    Two rules are easy to get wrong, which is why this is not a one-liner:
      - a gate is TRANSPARENT for chaining — the step after it reads from the op
        BEFORE the gate, not from the gate;
      - a review expands into ``<id>_send`` + a gate, and that send sub-step (a
        passthrough notify) becomes the source for everything downstream.
    """
    spec = load_spec(spec)
    wiring: list[StepWiring] = []
    last_op_id: str | None = None
    last_gate_id: str | None = None

    for step in spec.steps:
        if isinstance(step, GateStep):
            wiring.append(StepWiring(step_id=step.id, reviews=last_op_id))
            last_gate_id = step.id
            continue

        if isinstance(step, ReviewStep):
            send_id = f"{step.id}_send"
            wiring.append(
                StepWiring(step_id=send_id, source=last_op_id, gate=last_gate_id)
            )
            last_op_id = send_id  # passthrough: downstream chains from the sent ref
            wiring.append(StepWiring(step_id=step.id, reviews=send_id))
            last_gate_id = step.id
            continue

        # Split a dotted field ref back to its step: the graph is about steps.
        refs = {
            k: str(v["from"]).split(".", 1)[0]
            for k, v in step.params.items() if _is_ref(v)
        }
        if isinstance(step.in_, list):
            source, collect = None, list(step.in_)
        elif step.in_ == "none":
            source, collect = None, None
        elif isinstance(step.in_, str):
            source, collect = step.in_, None
        else:
            source, collect = last_op_id, None  # the implicit default
        wiring.append(
            StepWiring(
                step_id=step.id, source=source, collect=collect,
                refs=refs, gate=last_gate_id,
            )
        )
        last_op_id = step.id

    return wiring


def check_wire_types(spec: Union["PipelineSpec", dict, str, Path]) -> None:
    """Refuse a wire that carries the wrong kind of value.

    The vocabulary states what each op emits and what it consumes, and the flow
    builder filters its palette by exactly that - but nothing checked it once a
    spec existed. A picture wired into a text op therefore ran happily: the
    reference is a perfectly good string, so the model summarised the filename
    and the step reported ok. Nobody could tell from the outside that the work
    had not happened.

    Only concrete mismatches are refused. ``any`` on either side stays permeable
    (notify and llm.switch pass whatever they are given), and a source that is
    not an op - a gate answer read through a dotted reference - carries no
    declared type to compare against.

    Raises PipelineError naming both steps and both types. Pure.
    """
    parsed = load_spec(spec)
    emits = {st.id: get_op(st.op).output_type
             for st in parsed.steps
             if isinstance(st, OpStep) and get_op(st.op) is not None}

    for w in resolve_wiring(parsed):
        step = next((s for s in parsed.steps if s.id == w.step_id), None)
        if not isinstance(step, OpStep):
            continue
        op = get_op(step.op)
        if op is None or op.input_type == "any":
            continue
        for source_id in ([w.source] if w.source else list(w.collect or ())):
            produced = emits.get(source_id)
            if produced is None or produced == "any":
                continue
            if produced != op.input_type:
                raise PipelineError(
                    f"step {w.step_id!r} ({step.op}) consumes {op.input_type} but "
                    f"step {source_id!r} emits {produced} — that wire cannot carry "
                    "what the op expects"
                )


@dataclass(slots=True)
class RerunPlan:
    """What a partial re-run has to recompute, and what it may take from a past run.

    Re-running a whole flow because one late step was wrong is the expensive
    default: in a media pipeline the wasted steps are minutes of GPU and real
    money. Given the steps that changed, this answers the only question that
    matters — what actually goes stale?
    """

    # Compiled step ids that must run again, in spec order.
    redo: list[str] = field(default_factory=list)
    # Step ids whose stored output from the earlier run still holds.
    reuse: list[str] = field(default_factory=list)
    # Gates that redone steps wait on but that are NOT themselves redone. Their
    # earlier decision has to come from somewhere, or a human is asked twice.
    gates_needed: list[str] = field(default_factory=list)


def plan_rerun(
    spec: Union[PipelineSpec, dict, str, Path],
    changed: Iterable[str],
) -> RerunPlan:
    """Work out which steps a change makes stale.

    ``changed`` names COMPILED step ids (what :func:`resolve_wiring` reports,
    so ``<review>_send`` counts as its own step). Naming a review's id also
    marks its send sub-step: the two are one thing to a human.

    A step is stale when it changed itself, or when anything it depends on is
    stale — dependency meaning any of stdin source, fan-in list, ``{"from": …}``
    params, or the gate it waits on. One forward pass suffices because a
    reference must always point at an earlier step.

    Pure: no run is read and nothing is executed. Feeding the plan with a past
    run's stored outputs is the executor's job.
    """
    wiring = resolve_wiring(spec)
    wanted = set(changed)
    # A review is one thing to a human but two steps to the compiler.
    for w in wiring:
        if w.step_id.endswith("_send") and w.step_id[: -len("_send")] in wanted:
            wanted.add(w.step_id)

    plan = RerunPlan()
    stale: set[str] = set()
    for w in wiring:
        if w.step_id in wanted or (w.depends_on & stale):
            stale.add(w.step_id)
            plan.redo.append(w.step_id)
        else:
            plan.reuse.append(w.step_id)

    reused = set(plan.reuse)
    seen: set[str] = set()
    for w in wiring:
        if w.step_id in stale and w.gate and w.gate in reused and w.gate not in seen:
            seen.add(w.gate)
            plan.gates_needed.append(w.gate)
    return plan


def check_references(spec: Union["PipelineSpec", dict, str, Path]) -> None:
    """Refuse wiring that points at a step which does not exist yet.

    The compiler already refuses this, but only when a run starts - the flow sits
    in the library looking fine until someone spends time on it. A reference
    forward or into nothing can never become valid, unlike an op with status
    "planned", which is allowed on purpose so a flow may be authored ahead of its
    handler. So this is the one structural check the library applies at save.

    Raises PipelineError naming the step and the reference. Pure.
    """
    parsed = load_spec(spec)
    defined: set[str] = set()
    for step in parsed.steps:
        if isinstance(step, OpStep):
            wanted: list[tuple[str, str]] = []
            if isinstance(step.in_, str) and step.in_ not in ("none", ""):
                wanted.append(("in", step.in_))
            elif isinstance(step.in_, list):
                wanted += [("in-list", cid) for cid in step.in_]
            for pname, value in step.params.items():
                if _is_ref(value):
                    # A dotted reference reads a field of an earlier step's answer.
                    wanted.append((pname, str(value["from"]).split(".", 1)[0]))
            for label, target in wanted:
                if target not in defined:
                    raise PipelineError(
                        f"step {step.id!r}: {label} refers to {target!r}, which is "
                        "not an earlier step in this flow"
                    )
        defined.add(step.id)
        if isinstance(step, ReviewStep):
            defined.add(f"{step.id}_send")


def materialize_wiring(data: dict) -> dict:
    """Write the implicit wiring into a spec, so what runs is what is written.

    A step without ``in:`` silently takes the previous step's output. In a
    straight chain that is convenient; the moment a flow has two independent
    branches it is wrong, and invisibly so - the second branch starts by
    swallowing the first one's result, and the authoring front-end draws no wire
    because there is none to draw. The compiler is not the place to forbid the
    default (it would break every spec written so far); the SAVE is the place to
    write it down.

    Called on save, this fills in each op step's ``id`` (needed for anything to
    refer to it) and its ``in`` - the resolved source id, or ``"none"`` for a
    step that genuinely reads nothing. Gates and reviews are left alone: they
    carry no stdin wiring of their own.

    Pure: takes and returns a spec dict, touches no disk.
    """
    parsed = load_spec(data)
    wiring = {w.step_id: w for w in resolve_wiring(parsed)}
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != len(parsed.steps):
        return data  # shapes disagree - leave the author's file untouched

    for raw, step in zip(raw_steps, parsed.steps):
        if not isinstance(step, OpStep) or not isinstance(raw, dict) or len(raw) != 1:
            continue
        key = next(iter(raw))
        cfg = raw[key]
        if not isinstance(cfg, dict):
            continue  # shorthand form; leave as written
        cfg.setdefault("id", step.id)
        if "in" not in cfg:
            w = wiring.get(step.id)
            source = getattr(w, "source", None) if w else None
            if getattr(w, "collect", None):
                continue  # a fan-in list is explicit already
            cfg["in"] = source if source else "none"
    return data


# ============================================================================
# Compiler — PipelineSpec -> Lobster workflow dict (PURE, no IO)
# ============================================================================


def _gate_schemas(spec: "PipelineSpec") -> dict[str, dict]:
    """gate/review id -> the response schema it asks for."""
    return {st.id: (getattr(st, "response_schema", None) or {})
            for st in spec.steps if isinstance(st, (GateStep, ReviewStep))}


def _gate_condition(gate_id: str, schemas: dict[str, dict]) -> str | None:
    """What a step behind this gate must satisfy before it may run.

    A yes/no gate is a veto: the step runs only when the answer is `approved`.
    A gate that asks for something else - a word, a rating, the feedback a
    dotted {"from": "<gate>.<field>"} reference is meant to read - has no "no"
    to give. Pinning its condition to `.approved` anyway leaves a field that can
    never be true, so everything behind such a gate was silently skipped while
    the run still reported success. Answering that gate IS the go-ahead.
    """
    schema = schemas.get(gate_id) or {}
    props = (schema.get("properties") if isinstance(schema, dict) else None) or {}
    if not isinstance(props, dict):
        props = {}
    approved = props.get("approved")
    if isinstance(approved, dict) and approved.get("type") == "boolean":
        return f"${gate_id}.response.approved"
    return None


def compile_to_lobster(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    run_id: str | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    reuse: Iterable[str] | None = None,
    reuse_from: str | None = None,
) -> dict[str, Any]:
    """Compile a spec to a Lobster workflow dict. Pure — no filesystem, no runner.

    Inference rules (derived from the Increment 1-3 spikes):
      - stdin: an op step reads the previous op step's stdout by default; ``in:``
        overrides the source, ``in: "none"`` suppresses it (a producer).
      - condition: every step after a gate carries ``$<lastGate>.response.approved``
        (the most recent gate only — matching the spike behaviour).
      - run: a fully-formed ``curl --fail-with-body`` POST to the step endpoint with params
        URL-encoded and ``fmt=out`` appended; ``--data-binary @-`` when it has stdin.

    When ``run_id`` is given, ``run_id`` and the step's ``step_id`` are baked into
    every step's curl query so the step endpoint can correlate its per-step log
    lines to the run (see runlog). Omitting ``run_id`` (tests / inspection) leaves
    the output byte-identical to a plain compile.

    PARTIAL RE-RUN (all three optional, omitted = a plain full compile):
      - ``overrides`` replaces params per step id before anything else is read, so
        a changed value is visible to the wiring too — ``{"img2": {"prompt": "…"}}``.
      - ``reuse`` names steps to take from an earlier run instead of running them;
        each becomes a replay step that copies that output into this run. The spec
        handed in may DIFFER from the one that produced ``reuse_from`` (an extra
        edit step, a rewired input) — only the reused ids have to still match.
      - a reused GATE is dropped entirely and the conditions pointing at it are
        stripped: the human already decided, and asking twice is the bug this
        whole path exists to avoid. Only pass a gate whose decision was "approve".
    """
    spec = load_spec(spec)
    # Checked here rather than only on save, because a spec reaches a run through
    # several doors - the library, the builder's unsaved stack, a re-run's
    # recorded spec. A wire carrying the wrong kind of value is refused at every
    # one of them.
    check_wire_types(spec)
    schemas = _gate_schemas(spec)
    if overrides:
        # Applied before the wiring is read: an override may replace a literal
        # with a {"from": …} ref, which is an edge, not just a value.
        for step in spec.steps:
            patch = overrides.get(step.id)
            if patch and isinstance(step, OpStep):
                step.params = {**step.params, **patch}
    # One walk resolves every edge; the loop below only renders and validates.
    wiring = {w.step_id: w for w in resolve_wiring(spec)}
    reuse_ids = set(reuse or ())
    if reuse_ids and not reuse_from:
        raise PipelineError("reuse needs reuse_from — the run to take the outputs from")

    out_steps: list[dict[str, Any]] = []
    defined_ids: set[str] = set()

    for step in spec.steps:
        if isinstance(step, GateStep):
            if step.id in reuse_ids:
                # Decided in the earlier run; its id stays "defined" so a later
                # {"from": …} still resolves, but nobody is asked again.
                defined_ids.add(step.id)
                continue
            out_steps.append(
                {
                    "id": step.id,
                    "input": {"prompt": step.prompt, "responseSchema": step.response_schema},
                }
            )
            defined_ids.add(step.id)
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
            sw = wiring[send_id]
            if send_id in reuse_ids:
                cond = (
                    _gate_condition(sw.gate, schemas)
                    if sw.gate and sw.gate not in reuse_ids else None
                )
                out_steps.append(_replay_step(send_id, reuse_from, run_id, condition=cond))
            else:
                send: dict[str, Any] = {"id": send_id}
                if sw.source is not None and sw.source not in reuse_ids:
                    send["stdin"] = f"${sw.source}.stdout"
                if sw.gate is not None and sw.gate not in reuse_ids:
                    cond = _gate_condition(sw.gate, schemas)
                    if cond:
                        send["condition"] = cond
                send["run"] = _build_run(
                    "notify", step.notify_params, has_stdin=sw.source is not None,
                    run_id=run_id, step_id=send_id,
                )
                out_steps.append(send)
            defined_ids.add(send_id)

            if step.id not in reuse_ids:
                out_steps.append(
                    {
                        "id": step.id,
                        "input": {"prompt": step.prompt, "responseSchema": step.response_schema},
                    }
                )
            defined_ids.add(step.id)
            continue

        w = wiring[step.id]
        if step.id in reuse_ids:
            cond = (
                _gate_condition(w.gate, schemas)
                if w.gate and w.gate not in reuse_ids else None
            )
            out_steps.append(_replay_step(step.id, reuse_from, run_id, condition=cond))
            defined_ids.add(step.id)
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
            # A dotted ref picks ONE field out of a structured output — the case
            # that matters is a gate answer: "<gate>.feedback" pulls the text a
            # human wrote, while "<gate>" alone yields the whole answer. Only the
            # part before the first dot has to name a step; the field is resolved
            # from the bucket at run time, the same way an args.<name> ref is.
            head = src.split(".", 1)[0]
            if head not in defined_ids:
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
        if w.collect is not None:
            for cid in w.collect:
                if cid not in defined_ids:
                    raise PipelineError(
                        f"step {step.id!r}: in-list refers to unknown or later step {cid!r}"
                    )
            collect_ids = list(w.collect)
            source_id = None
        else:
            source_id = w.source
            # Only an explicitly named source can be wrong; the implicit default
            # is an earlier step by construction.
            if isinstance(step.in_, str) and step.in_ != "none" and source_id not in defined_ids:
                raise PipelineError(
                    f"step {step.id!r}: in:{step.in_!r} refers to an unknown or later step"
                )
        compiled: dict[str, Any] = {"id": step.id}
        if source_id is not None:
            # A replayed step DOES emit its stdout, so the pipe still works.
            compiled["stdin"] = f"${source_id}.stdout"
        if w.gate is not None and w.gate not in reuse_ids:
            cond = _gate_condition(w.gate, schemas)
            if cond:
                compiled["condition"] = cond
        compiled["run"] = _build_run(
            step.op, step.params, has_stdin=source_id is not None,
            run_id=run_id, step_id=step.id, collect=collect_ids,
        )

        out_steps.append(compiled)
        defined_ids.add(step.id)

    return {"name": spec.name, "steps": out_steps}


def _replay_step(
    step_id: str,
    from_run: str | None,
    run_id: str | None,
    *,
    condition: str | None = None,
) -> dict[str, Any]:
    """A step that re-emits an earlier run's stored output instead of doing the work.

    Deliberately a real step rather than a hole in the workflow: the pipe
    ``$id.stdout`` keeps resolving, and the run log shows the whole flow with the
    reused parts visible instead of a torso that looks like a broken run.
    """
    pairs = [f"from_run={quote(str(from_run), safe='')}", f"step={quote(step_id, safe='')}", "fmt=out"]
    if run_id:
        pairs.append(f"run_id={quote(run_id, safe='')}")
        pairs.append(f"step_id={quote(step_id, safe='')}")
    url = f"{STEP_BASE_URL}/pipeline/replay?" + "&".join(pairs)
    out: dict[str, Any] = {"id": step_id}
    if condition:
        # A gate that is being asked AGAIN still governs this step: on a "no" the
        # replay must stay silent like every other step behind that gate.
        out["condition"] = condition
    out["run"] = f"curl -sS --fail-with-body -X POST '{url}'"
    return out


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
    # --fail-with-body instead of -f: both make curl exit non-zero on an HTTP
    # error (so the workflow stops), but -f also DISCARDS the response body —
    # which is where the step endpoint puts the reason. Without it a failing
    # step reports only "curl: (22) ... error 400" and the actual cause is lost.
    run = f"curl -sS --fail-with-body -X POST '{url}'"
    if has_stdin:
        run += " --data-binary @-"
    return run
