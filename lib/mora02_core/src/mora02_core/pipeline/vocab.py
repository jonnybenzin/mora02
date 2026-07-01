"""mora02_core.pipeline.vocab — the pipeline step VOCABULARY (single source of truth).

The set of step *ops* a pipeline is built from, described structurally: name,
purpose, params (with defaults / required flags), what they consume on stdin, and
what they emit. This registry is the one place the contract lives; everything else
derives from it:

  - the compiler (:mod:`mora02_core.pipeline.spec`) validates a spec against it —
    an unknown op or a mistyped param fails at COMPILE time, not at runtime;
  - the script-runner serves it at ``GET /pipeline/ops`` so the rapid-authoring
    front-ends (visual builder / recording / LLM dialog) can enumerate + validate;
  - the human-readable reference (docs/pipeline-vocabulary.md) is GENERATED from it.

The ops are *implemented* by handlers in ``apps/script-runner/app/main.py``
(``_PIPELINE_STEPS``); that module guards at startup that its handler keys match
this registry, so the two cannot silently drift. Adding an op = add a handler
there AND an :class:`Op` here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mora02_core.pipeline._errors import PipelineError

# Cardinality of what a step reads from stdin (the previous step's output ref/value).
Consumes = str  # "none" | "one" | "many"
# Asset/value type flowing on a wire.
WireType = str  # "image" | "video" | "audio" | "text" | "any"


@dataclass(frozen=True, slots=True)
class Param:
    """One query parameter of an op."""

    name: str
    type: str = "string"  # string | int | bool | enum
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] | None = None
    desc: str = ""


@dataclass(frozen=True, slots=True)
class Op:
    """One pipeline step verb — its contract, independent of the HTTP handler."""

    name: str
    summary: str
    params: tuple[Param, ...] = ()
    consumes: Consumes = "none"  # how many input refs/values it reads on stdin
    consumes_optional: bool = False  # stdin may be absent (value also from a param)
    input_type: WireType = "any"  # expected type of the stdin input(s)
    output_type: WireType = "text"  # type of the single value emitted on stdout
    # "wired" = a script-runner handler exists and the op is runnable today.
    # "planned" = the underlying capability exists (lib/endpoint) but no pipeline
    # handler yet — the op is in the vocabulary as a menu/contract, but compiling
    # a pipeline that USES it is refused until it is built (see spec.compile).
    status: str = "wired"
    bucket: str = ""  # service family for grouping in docs / front-ends

    @property
    def default_id(self) -> str:
        """Default step id when ``id:`` is omitted — the text before the first dot."""
        return self.name.split(".", 1)[0]

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["params"] = [asdict(p) for p in self.params]
        d["default_id"] = self.default_id
        return d


# ============================================================================
# The registry — the full vocabulary (catalog from the v1 design pass).
#
# status="wired"  -> a script-runner handler in _PIPELINE_STEPS exists; runnable.
# status="planned"-> the capability exists as a lib/endpoint, but no pipeline
#                    handler yet. It is here as a contract/menu for the authoring
#                    front-ends; the compiler refuses to build a pipeline that
#                    uses it until it is wired (one build wave per bucket).
#
# Param sets for planned ops mirror the underlying lib/endpoint and may be
# refined when the handler is actually built. Publishing (publish.*) and music
# (music.generate) are intentionally omitted from v1.
# ============================================================================

_IMAGE_FLOWS = (
    "sd15", "photo", "concept", "epic", "flux",       # local diffusion
    "nanban", "nanban-pro", "gpt-image", "flux-ultra",  # external API
)

# Valid llama.cpp switch targets for llm.switch. Kept STATIC here on purpose: this
# vocabulary is the lightweight contract read by the front-ends, the compiler and
# scripts/vocab.py — it must not pull the llm package (which eagerly imports the
# anthropic SDK, absent on the host CLI). Keep in sync by hand with the profile
# catalog in mora02_core/llm/profiles.py::PROFILES — the same deliberate, hand-
# maintained duplication the host-side switcher whitelist already carries. The
# handler additionally validates the profile against the live catalog at runtime.
_LLM_PROFILES = (
    "qwen3-14b", "qwen3-8b", "qwen25-7b", "qwen25-coder", "nous-hermes", "magistral",
)

_OPS: tuple[Op, ...] = (
    # ----- HITL / delivery / sources (wired) --------------------------------
    Op(
        name="source.file",
        summary="Bring an existing file from a store into the pipeline as a ref.",
        bucket="source",
        params=(
            Param("store", default="comfyui", desc="logical store to read from"),
            Param("name", desc="exact filename; omit to auto-pick from the store"),
            Param("pick", type="enum", default="latest", choices=("latest", "oldest"),
                  desc="which file to pick when 'name' is omitted (by mtime)"),
        ),
        consumes="none",
        output_type="image",
    ),
    Op(
        name="notify.image",
        summary="(superseded by 'notify') Send an image ref to a chat for review, pass it through.",
        bucket="delivery",
        params=(
            Param("target", desc="E.164 recipient; falls back to env MORA02_SIGNAL_TARGET"),
            Param("channel", default="signal", desc="notify channel"),
            Param("message", desc="optional caption sent with the image"),
        ),
        consumes="one",
        input_type="image",
        output_type="image",  # passthrough: emits the same ref it received
    ),

    # ----- ComfyUI / visual -------------------------------------------------
    Op(
        name="image.generate",
        summary="Generate an image from a prompt via ComfyUI (9 selectable flows).",
        bucket="visual",
        params=(
            Param("prompt", desc="prompt text; falls back to the stdin value if omitted"),
            Param("flow", type="enum", default="photo", choices=_IMAGE_FLOWS,
                  desc="model/flow preset (local diffusion or external API)"),
            Param("format", desc="portrait|landscape|square or WIDTHxHEIGHT"),
            Param("batch_size", type="int", desc="number of images to generate"),
            Param("testrun", type="bool", desc="set '1' for a fast low-quality test run"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="image",
    ),
    Op(
        name="image.upscale",
        summary="Upscale an image (hybrid SDXL-Tile + UltraSharp).",
        bucket="visual",
        params=(
            Param("factor", type="int", default="2", desc="scale factor 1.5–4.0"),
            Param("prompt", desc="optional guidance prompt"),
            Param("denoise", desc="refinement denoise 0.05–0.5 (default 0.2)"),
            Param("seed", type="int"),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="image.expand",
        summary="Outpaint / expand an image to a larger canvas (FLUX).",
        bucket="visual",
        params=(
            Param("prompt", desc="what to paint into the new area"),
            Param("target_size", type="int", default="1920", desc="target long edge in px"),
            Param("feathering", desc="edge blend amount"),
            Param("seed", type="int"),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="video.generate",
        summary="Generate video via WAN 2.2 — text-to-video, image-to-video, or start+end frames.",
        bucket="visual",
        params=(
            Param("prompt", desc="prompt; falls back to stdin"),
            Param("mode", type="enum", default="t2v", choices=("t2v", "i2v", "i2i2v"),
                  desc="t2v=text only, i2v=from start image, i2i2v=start+end frames"),
            Param("start_image", desc="start frame ref (i2v / i2i2v)"),
            Param("end_image", desc="end frame ref (i2i2v)"),
            Param("length", type="int", desc="frames 17–201"),
            Param("fps", type="int", desc="frames per second 8–60"),
            Param("seed", type="int"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="any",
        output_type="video",
    ),

    # ----- Media finishing --------------------------------------------------
    Op(
        name="clip.generate",
        summary="Assemble one or more image/video refs into a single MP4 (Ken-Burns).",
        bucket="media",
        params=(
            Param("name", desc="output filename; auto-generated if omitted"),
            Param("resolution", default="1080p", desc="1080p|720p|4k|square|story|reels or WxH"),
            Param("durations", default="4", desc="per-input seconds (single or comma list)"),
            Param("animation", type="enum", default="pan",
                  choices=("pan", "zoom_in", "zoom_out", "none"), desc="motion style"),
        ),
        consumes="many",
        input_type="any",
        output_type="video",
    ),
    Op(
        name="text.overlay",
        summary="Render multi-line text onto a flat-color background as a PNG.",
        bucket="media",
        params=(
            Param("text", desc="the text; falls back to stdin"),
            Param("size", default="1080x1080", desc="canvas WxH"),
            Param("template", type="enum", default="dark",
                  choices=("dark", "darker", "light", "black"), desc="background theme"),
            Param("font", type="enum", default="bold",
                  choices=("bold", "bold-italic", "thin", "thin-italic")),
            Param("fontsize", default="medium", desc="small|medium|large or px"),
            Param("layout", type="enum", default="left", choices=("left", "centered")),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="image",
    ),
    Op(
        name="gif.create",
        summary="Animate multiple images into an animated GIF.",
        bucket="media",
        params=(
            Param("durations", default="1", desc="per-frame seconds (single or comma list)"),
            Param("quality", type="enum", default="medium",
                  choices=("low", "medium", "high", "ultra")),
            Param("size", desc="output WxH or width-only"),
        ),
        consumes="many",
        input_type="image",
        output_type="video",  # gif file; closest wire type
    ),
    Op(
        name="tts.speak",
        summary="Synthesize speech audio from text (piper/kokoro/chatterbox).",
        bucket="audio",
        params=(
            Param("text", desc="text to speak; falls back to stdin"),
            Param("language", default="en", desc="e.g. en, de"),
            Param("voice", desc="voice id; default per language"),
            Param("format", type="enum", default="wav", choices=("wav", "mp3")),
            Param("engine", type="enum", default="auto",
                  choices=("auto", "piper", "kokoro", "chatterbox")),
            Param("speed", desc="rate multiplier (default 1.0)"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="audio",
    ),

    # ----- LLM (local control-plane) ---------------------------------------
    Op(
        name="llm.image_prompt",
        summary="Expand a short subject into one rich text-to-image prompt (local qwen).",
        bucket="llm",
        params=(
            Param("subject", desc="the subject; falls back to the stdin value if omitted"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.complete",
        summary="Free-form text completion (local qwen).",
        bucket="llm",
        params=(
            Param("prompt", desc="user prompt; falls back to stdin"),
            Param("system", desc="system prompt"),
            Param("temperature", desc="sampling temperature (default 0.7)"),
            Param("max_tokens", type="int", desc="max output tokens (default 512)"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.summarize",
        summary="Summarize the input text (local qwen, thin wrapper over llm.complete).",
        bucket="llm",
        params=(Param("max_tokens", type="int", desc="summary length budget"),),
        consumes="one",
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.classify",
        summary="Classify the input text into one of the given labels (local qwen).",
        bucket="llm",
        params=(
            Param("labels", required=True, desc="comma-separated candidate labels"),
        ),
        consumes="one",
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.extract",
        summary="Extract structured fields from the input text as JSON (local qwen).",
        bucket="llm",
        params=(
            Param("fields", required=True, desc="comma-separated fields to extract"),
        ),
        consumes="one",
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.translate",
        summary="Translate the input text to a target language (local qwen).",
        bucket="llm",
        params=(
            Param("to", required=True, desc="target language, e.g. de, en"),
            Param("from", desc="source language; auto-detect if omitted"),
        ),
        consumes="one",
        input_type="text",
        output_type="text",
    ),

    # ----- LLM (cloud — peripheral only, control-plane guardrail) -----------
    Op(
        name="cloud.complete",
        summary="Text completion via Claude (cloud; peripheral content tasks only).",
        bucket="cloud",
        params=(
            Param("prompt", desc="user prompt; falls back to stdin"),
            Param("system", desc="system prompt"),
            Param("model", type="enum", default="sonnet", choices=("haiku", "sonnet", "opus")),
            Param("temperature", desc="sampling temperature (default 0.7)"),
            Param("max_tokens", type="int"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="cloud.vision",
        summary="Describe / analyze an image with an optional question (Claude vision).",
        bucket="cloud",
        params=(
            Param("query", desc="what to ask about the image"),
            Param("model", type="enum", default="haiku", choices=("haiku", "sonnet", "opus")),
        ),
        consumes="one",
        input_type="image",
        output_type="text",
    ),

    # ----- Data (Baserow generic CRUD) -------------------------------------
    Op(
        name="baserow.query",
        summary="Query rows from a table with filter/order/pagination.",
        bucket="data",
        params=(
            Param("table", required=True, desc="table name or numeric id"),
            Param("filter", desc="filter expression / JSON"),
            Param("order_by", desc="e.g. -created_at"),
            Param("size", type="int", default="50", desc="rows per page (max 200)"),
        ),
        consumes="none",
        output_type="text",  # JSON rows
    ),
    Op(
        name="baserow.get",
        summary="Fetch a single row by id.",
        bucket="data",
        params=(
            Param("table", required=True),
            Param("row_id", type="int", required=True),
        ),
        consumes="none",
        output_type="text",
    ),
    Op(
        name="baserow.insert",
        summary="Create a new row (field values from stdin JSON or 'data').",
        bucket="data",
        params=(
            Param("table", required=True),
            Param("data", desc="JSON field values; falls back to stdin"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="baserow.update",
        summary="Patch an existing row by id (partial update).",
        bucket="data",
        params=(
            Param("table", required=True),
            Param("row_id", type="int", required=True),
            Param("data", desc="JSON field values; falls back to stdin"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="baserow.delete",
        summary="Delete a row by id.",
        bucket="data",
        params=(
            Param("table", required=True),
            Param("row_id", type="int", required=True),
        ),
        consumes="none",
        output_type="text",
    ),
    Op(
        name="baserow.list_fields",
        summary="Get the field schema for a table.",
        bucket="data",
        params=(Param("table", required=True),),
        consumes="none",
        output_type="text",
    ),

    # ----- Web & stock ------------------------------------------------------
    Op(
        name="web.search",
        summary="Search the web via local SearXNG.",
        bucket="web",
        params=(
            Param("query", desc="search query; falls back to stdin"),
            Param("categories", default="general", desc="SearXNG category"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="web.fetch",
        summary="Fetch a web page and return its text.",
        bucket="web",
        params=(Param("url", desc="page URL; falls back to stdin"),),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="stock.search",
        summary="Search stock photos (Pexels / Pixabay).",
        bucket="web",
        params=(
            Param("query", desc="search term; falls back to stdin"),
            Param("source", type="enum", default="pexels", choices=("pexels", "pixabay")),
            Param("count", type="int", default="5"),
            Param("orientation", type="enum", default="landscape",
                  choices=("landscape", "portrait", "square")),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",  # JSON results
    ),
    Op(
        name="stock.download",
        summary="Download a stock photo into a store as an image ref.",
        bucket="web",
        params=(
            Param("source", type="enum", required=True, choices=("pexels", "pixabay")),
            Param("image_url", required=True, desc="full image URL"),
            Param("image_id", desc="stock API image id"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="image",
    ),

    # ----- Delivery (generalized notify) -----------------------------------
    Op(
        name="notify",
        summary="Send the previous step's output (type-aware) to a channel, no pause; pass it through.",
        bucket="delivery",
        params=(
            Param("channel", default="signal", desc="notify channel"),
            Param("target", desc="recipient; falls back to env MORA02_SIGNAL_TARGET"),
            Param("message", desc="optional caption / text body"),
            Param("title", desc="optional title prepended to message"),
            Param("link", desc="optional link appended to message"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="any",
        output_type="any",  # passthrough
    ),
    # ----- LLM model switch (local control-plane) --------------------------
    Op(
        name="llm.switch",
        summary="Switch the active local LLM (llama.cpp profile), like the Pilot "
                "model switcher. Takes ~10-20s; the swap is global and persistent "
                "across the whole box. Passes stdin through unchanged.",
        bucket="llm",
        params=(
            Param("profile", type="enum", required=True, choices=_LLM_PROFILES,
                  desc="target llama.cpp profile to load"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="any",
        output_type="any",  # passthrough: emits its stdin unchanged
    ),

    # ----- Music generation (local, ComfyUI ACE-Step) ----------------------
    Op(
        name="music.generate",
        summary="Generate music/song audio from style tags + optional lyrics via "
                "ComfyUI ACE-Step 1.5 (local).",
        bucket="audio",
        params=(
            Param("prompt", desc="music style/genre tags; falls back to the stdin value"),
            Param("lyrics", desc="lyrics text; empty = instrumental"),
            Param("duration", type="int", default="30", desc="length in seconds"),
            Param("bpm", type="int", default="120", desc="tempo in beats per minute"),
            Param("key", default="C major", desc="musical key/scale, e.g. 'C major', 'A minor'"),
            Param("time_signature", default="4", desc="time signature (beats per bar)"),
            Param("language", default="en", desc="lyrics language, e.g. en, de"),
            Param("steps", type="int", default="8", desc="sampler steps (turbo default 8)"),
            Param("seed", type="int"),
            Param("cfg_scale", desc="text guidance strength (default 2.0)"),
            Param("temperature", desc="sampling temperature (default 0.85)"),
            Param("top_p", desc="nucleus sampling top-p (default 0.9)"),
            Param("top_k", type="int", desc="top-k sampling (default 0 = off)"),
            Param("min_p", desc="min-p sampling (default 0.0)"),
            Param("ref_audio", desc="optional reference-audio ref for timbre transfer"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="audio",
    ),

    # ----- Publishing (external channels) ----------------------------------
    Op(
        name="publish.linkedin",
        summary="Publish an image or text post to LinkedIn (UGC API). Image ref on "
                "stdin (optional — omit for a text-only post). Returns the post URL.",
        bucket="publish",
        params=(
            Param("text", desc="post caption/body text (often a {\"from\": <llm step>} ref)"),
            Param("author", desc="author URN urn:li:person:…; falls back to env MORA02_LINKEDIN_AUTHOR"),
            Param("visibility", type="enum", default="PUBLIC",
                  choices=("PUBLIC", "CONNECTIONS"), desc="post visibility"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="image",
        output_type="text",  # the post URL
    ),

    # <<< add-vocab: scripts/add-vocab.py inserts new Op() entries above this line >>>
)

_BY_NAME: dict[str, Op] = {op.name: op for op in _OPS}


# ============================================================================
# Lookup + validation
# ============================================================================


def all_ops() -> tuple[Op, ...]:
    """Every registered op, in declaration order."""
    return _OPS


def op_names() -> set[str]:
    """The set of ALL registered op names (wired + planned)."""
    return set(_BY_NAME)


def wired_op_names() -> set[str]:
    """Names of ops that must have a script-runner handler (drift-check target)."""
    return {op.name for op in _OPS if op.status == "wired"}


def get_op(name: str) -> Op | None:
    return _BY_NAME.get(name)


def is_wired(name: str) -> bool:
    """True if the op is registered AND runnable today (has a handler)."""
    op = _BY_NAME.get(name)
    return op is not None and op.status == "wired"


def to_dict() -> dict[str, Any]:
    """Serialize the whole vocabulary (for ``GET /pipeline/ops`` / front-ends)."""
    return {"ops": [op.to_dict() for op in _OPS]}


def validate_op(
    name: str, params: dict[str, Any], *, ref_params: "set[str] | frozenset[str]" = frozenset()
) -> None:
    """Validate one op invocation against the vocabulary. Raises PipelineError.

    Checks: the op exists, every supplied param is known (catches typos), required
    params are present, and enum params hold an allowed value. Stdin/env fallbacks
    mean most params are not hard-required — that is intentional.

    Params supplied as step-output references (a spec value ``{"from": "<id>"}``)
    pass their NAMES in ``ref_params``: they count as present (satisfy required)
    but are not enum/value-checked, since their value is only known at run time.
    """
    op = _BY_NAME.get(name)
    if op is None:
        known = ", ".join(sorted(_BY_NAME)) or "(none)"
        raise PipelineError(f"unknown op {name!r}; known ops: {known}")

    known_params = {p.name for p in op.params}
    for key in (*params, *ref_params):
        if key not in known_params:
            allowed = ", ".join(sorted(known_params)) or "(none)"
            raise PipelineError(
                f"op {name!r}: unknown param {key!r}; allowed: {allowed}"
            )
    for p in op.params:
        if p.required and p.name not in params and p.name not in ref_params:
            raise PipelineError(f"op {name!r}: missing required param {p.name!r}")
        if p.choices and p.name in params and str(params[p.name]) not in p.choices:
            raise PipelineError(
                f"op {name!r}: param {p.name!r}={params[p.name]!r} not in "
                f"{list(p.choices)}"
            )
