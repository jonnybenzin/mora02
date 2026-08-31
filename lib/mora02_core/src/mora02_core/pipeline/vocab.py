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
    # "advanced" = a detail/"kleinkram" param (seed, steps, quality, cfg …). The
    # block-authoring UI shows non-advanced params as basics and tucks the advanced
    # ones behind an inner "detailed settings" sub-collapse. Purely a display hint.
    advanced: bool = False


@dataclass(frozen=True, slots=True)
class Op:
    """One pipeline step verb — its contract, independent of the HTTP handler."""

    name: str
    summary: str
    # A jargon-free one-liner of what the op does, for the human-readable doc
    # (docs/pipeline-vocabulary.md). The technical `summary` stays for engineers.
    plain: str = ""
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

    # ---- what it costs a human to use ------------------------------------
    # Written for the VOCABULARY table in the Pilot wiki, where someone decides
    # whether to put an op in a loop, in a nightly job, or in front of an
    # audience. Duration and actual spend are NOT here: those are measured from
    # the run log rather than declared, because a number somebody typed once
    # ages into a lie. What is declared here is what cannot be measured -
    # where the work happens, whether money moves, and whether it can be undone.
    runs_on: str = ""       # local-gpu | local-cpu | local-service | cloud | gateway
    service: str = ""       # the backend behind it: "ComfyUI (SDXL)", "Anthropic API", …
    cost: str = "free"      # free | paid | mixed (mixed: depends on the chosen flow)
    cost_note: str = ""     # list price in EUR, or what makes it "mixed"
    effect: str = "none"    # none | writes | outward (outward = leaves the house)
    caveats: tuple[str, ...] = ()   # what surprises people, in one sentence each
    requires: tuple[str, ...] = ()  # services that must run, keys that must be set

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
    "nanban", "nanban-pro", "flux-ultra",  # external API
)

# Valid llama.cpp switch targets for llm.switch. Kept STATIC here on purpose: this
# vocabulary is the lightweight contract read by the front-ends, the compiler and
# scripts/vocab.py — it must not pull the llm package (which eagerly imports the
# anthropic SDK, absent on the host CLI). Keep in sync by hand with the profile
# catalog in mora02_core/llm/profiles.py::PROFILES — the same deliberate, hand-
# maintained duplication the host-side switcher whitelist already carries. The
# handler additionally validates the profile against the live catalog at runtime.
_LLM_PROFILES = (
    "qwen3-14b", "qwen3-8b", "qwen36-27b", "glimmer-30b",
)
# Four profiles retired 2026-08-31 after the tool-calling bench measured them:
# see _archive/2608311230_llm-profile-retirement. The weights are still on disk;
# only the wiring is gone, so a rollback is three files and a compose block.

# PixelText .blend templates for pixeltext.render (empty = worker procedural
# default). A curated subset of apps/blender-worker/templates/*.blend — only the
# ones that render a usable result were kept (surveyed 2026-07: bulle.blend has no
# valid TEMPLATE_CUBE mesh and degrades to procedural; test2.blend renders the
# text nearly invisible). Kept static here (that app is not on the pip path /
# importable); keep in sync by hand when templates are added or vetted.
_PIXELTEXT_TEMPLATES = (
    "", "default.blend", "test3.blend", "test4.blend", "test5.blend",
)

# Named TTS voices for tts.speak (empty = auto by language). Mirrors the VOICES
# catalog in mora02_core/media/tts.py (kokoro EN + piper DE) — kept static here so
# this SDK-free vocabulary need not import the tts module; keep in sync by hand.
# Chatterbox cloned voices are dynamic (managed in the Pilot TTS studio) and are
# addressed separately, so they are not enumerated here.
_TTS_VOICES = (
    "",                                              # auto by language
    "af_bella", "af_nova", "am_adam", "am_michael",  # en / kokoro
    "thorsten", "thorsten_emotional", "kerstin",     # de / piper
)

_OPS: tuple[Op, ...] = (
    # ----- HITL / delivery / sources (wired) --------------------------------
    Op(
        name="source.file",
        summary="Bring an existing file from a store into the pipeline as a ref.",
        plain="Grabs a file that already exists (e.g. the latest image ComfyUI made) and hands it to the next step.",
        bucket="source",
        runs_on='local-cpu',
        service='the asset stores',
        caveats=(
            'pick=latest looks at image files only.',
        ),
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
        plain="Sends an image to your phone chat so you can look at it, then passes it along unchanged.",
        bucket="delivery",
        runs_on='gateway',
        service='OpenClaw gateway → Signal',
        effect='outward',
        caveats=(
            'Superseded by notify, which handles any media type.',
            'Same two-message behaviour for the caption.',
        ),
        requires=(
            'the OpenClaw gateway container',
            'MORA02_SIGNAL_TARGET, unless ?target= is given',
        ),
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
        plain="Makes a brand-new picture from a text description.",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        cost='mixed',
        cost_note='sd15/photo/concept/epic/flux run locally and cost nothing. Paid, '
                  'per image, at the rate below: nanban (Nano Banana 2, Google) ~0,058 € '
                  'at 1K and 0,039-0,130 € depending on resolution; nanban-pro (Nano '
                  'Banana, Google) ~0,034 €; flux-ultra (FLUX 1.1 Pro Ultra via fal.ai) '
                  '~0,052 €. List prices looked up 2026-08-29.',
        caveats=(
            'Which flow you pick decides both the look and whether it costs money.',
            'The labels are the wrong way round: nanban runs Nano Banana 2, while '
            'nanban-pro runs the older Nano Banana.',
        ),
        requires=(
            'ComfyUI running',
            'GOOGLE_API_KEY / FAL_KEY for the paid flows',
        ),
        params=(
            Param("prompt", desc="prompt text; falls back to the stdin value if omitted"),
            Param("flow", type="enum", default="photo", choices=_IMAGE_FLOWS,
                  desc="model/flow preset (local diffusion or external API)"),
            Param("format", desc="portrait|landscape|square or WIDTHxHEIGHT"),
            Param("batch_size", type="int", desc="number of images to generate", advanced=True),
            Param("testrun", type="bool", desc="set '1' for a fast low-quality test run", advanced=True),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="image",
    ),
    Op(
        name="image.upscale",
        summary="Upscale an image (hybrid SDXL-Tile + UltraSharp).",
        plain="Enlarges a picture and sharpens it, without making it blurry.",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        requires=(
            'ComfyUI running',
        ),
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
        plain="Extends a picture beyond its edges, inventing more scenery around it (outpainting).",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        caveats=(
            'The slowest of the image ops by a wide margin — check the measured time before putting it in a loop.',
        ),
        requires=(
            'ComfyUI running',
        ),
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
        plain="Turns a prompt (or a still image) into a short moving video clip.",
        bucket="video",
        runs_on='local-gpu',
        service='ComfyUI (WAN 2.2)',
        caveats=(
            'Minutes per clip — with pixeltext.render the heaviest op in the vocabulary.',
            'Three modes: t2v, i2v and start+end frame.',
        ),
        requires=(
            'ComfyUI running',
        ),
        params=(
            Param("prompt", desc="prompt; falls back to stdin"),
            Param("mode", type="enum", default="t2v", choices=("t2v", "i2v", "i2i2v"),
                  desc="t2v=text only, i2v=from start image, i2i2v=start+end frames"),
            Param("start_image", desc="start frame ref (i2v / i2i2v)"),
            Param("end_image", desc="end frame ref (i2i2v)"),
            Param("length", type="int", desc="frames 17–201", advanced=True),
            Param("fps", type="int", desc="frames per second 8–60", advanced=True),
            Param("seed", type="int", advanced=True),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="any",
        output_type="video",
    ),
    Op(
        name="video.last_frame",
        summary="Extract the last frame of a video as an image ref — chains i2v videos "
                "(each new video starts from the previous one's final frame).",
        plain="Grabs the final still frame of a video, handy to keep a scene going into the next clip.",
        bucket="video",
        runs_on='local-cpu',
        service='ffmpeg',
        caveats=(
            'The way to chain i2v videos into one another.',
        ),
        params=(
            Param("position", type="enum", default="last", choices=("last", "first"),
                  desc="which frame to grab", advanced=True),
        ),
        consumes="one",
        input_type="video",
        output_type="image",
    ),

    # ----- Media finishing --------------------------------------------------
    Op(
        name="clip.generate",
        summary="Assemble one or more image/video refs into a single MP4 (Ken-Burns).",
        plain="Stitches several videos together into one clip, optionally laying a music track over it.",
        bucket="media",
        runs_on='local-cpu',
        service='ffmpeg',
        caveats=(
            'Takes images and videos in the same list; the order follows the list, not the ids.',
        ),
        params=(
            Param("name", desc="output filename; auto-generated if omitted", advanced=True),
            Param("resolution", default="1080p", desc="1080p|720p|4k|square|story|reels or WxH"),
            Param("durations", default="4", desc="per-input seconds (single or comma list)"),
            Param("animation", type="enum", default="pan",
                  choices=("pan", "zoom_in", "zoom_out", "none"), desc="motion style"),
            Param("soundtrack", desc="optional audio ref to lay over the clip as its music "
                                     "track (handler support planned)"),
        ),
        consumes="many",
        input_type="any",
        output_type="video",
    ),
    Op(
        name="text.overlay",
        summary="Render multi-line text onto a flat-color background as a PNG.",
        plain="Writes text onto a colored background as a simple image card.",
        bucket="media",
        runs_on='local-cpu',
        service='Pillow',
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
        plain="Turns several images into one looping animated GIF.",
        bucket="media",
        runs_on='local-cpu',
        service='ffmpeg / Pillow',
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
        plain="Reads text out loud and saves it as an audio file (text-to-speech).",
        bucket="audio",
        runs_on='local-cpu',
        service='piper / kokoro / chatterbox',
        caveats=(
            'The voice list depends on the engine; an empty voice picks one by language.',
        ),
        params=(
            Param("text", desc="text to speak; falls back to stdin"),
            Param("language", default="en", desc="e.g. en, de"),
            Param("voice", type="enum", default="", choices=_TTS_VOICES,
                  desc="named voice (en=kokoro af_*/am_*, de=piper thorsten/kerstin); "
                  "empty = auto by language"),
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
        plain="Takes a short idea and expands it into a rich, detailed prompt for image generation.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        caveats=(
            'Writes the prompt, it does not draw — chain image.generate after it.',
        ),
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
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
        plain="Asks the local AI to write or answer something freely.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        caveats=(
            'No length limit by default; a cut answer is flagged as truncated in the run log.',
        ),
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
        params=(
            Param("prompt", desc="user prompt; falls back to stdin"),
            Param("system", desc="system prompt"),
            Param("temperature", desc="sampling temperature (default 0.7)", advanced=True),
            # Not "advanced": this is the length dial. Hidden behind a sub-collapse
            # it looks like the model gave up, when the output was simply cut.
            Param("max_tokens", type="int",
                  desc="optional ceiling; empty = the model stops when the answer ends"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.summarize",
        summary="Summarize the input text (local qwen, thin wrapper over llm.complete).",
        plain="Shortens a long text down to its key points.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
        params=(Param("max_tokens", type="int", desc="summary length budget"),),
        consumes="one",
        input_type="text",
        output_type="text",
    ),
    Op(
        name="llm.classify",
        summary="Classify the input text into one of the given labels (local qwen).",
        plain="Sorts a text into one of a set of labels you provide.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        caveats=(
            'Refuses an answer that is none of the labels — llm.complete is the op for free-form text.',
            "Handed its predecessor's own label as text, the model tends to echo that instead of choosing.",
        ),
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
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
        plain="Pulls specific facts (e.g. name, date, price) out of a text.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        caveats=(
            'Returns JSON — chain data.pick to get a single field out of it.',
        ),
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
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
        plain="Translates text into another language.",
        bucket="llm",
        runs_on='local-gpu',
        service='llama.cpp (local qwen)',
        requires=(
            'llama-server running — llm.switch names the active profile',
        ),
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
        plain="Asks a cloud AI (Claude) to write or answer something, for the few tasks the local model can't handle.",
        bucket="cloud",
        runs_on='cloud',
        service='Anthropic API (Claude)',
        cost='paid',
        cost_note='Per token, and the rate differs by model — the price list is shown with the op.',
        caveats=(
            'No temperature — the current models removed the sampling parameters.',
            'Answers are capped at 16000 tokens; a cut answer is flagged.',
        ),
        requires=(
            'ANTHROPIC_API_KEY',
        ),
        params=(
            Param("prompt", desc="user prompt; falls back to stdin"),
            Param("system", desc="system prompt"),
            Param("model", type="enum", default="sonnet", choices=("haiku", "sonnet", "opus")),
            # No temperature. Anthropic removed the sampling parameters on the
            # current models, and the SDK this runs against no longer accepts the
            # argument at all - offering a knob that can only fail is worse than
            # not offering it. The model's own sampling applies.
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
        plain="Shows a cloud AI (Claude) an image and asks it to describe or analyze it.",
        bucket="cloud",
        runs_on='cloud',
        service='Anthropic API (Claude)',
        cost='paid',
        cost_note='Per token, and the rate differs by model — the price list is shown with the op.',
        caveats=(
            'The answer is capped at 1024 tokens.',
            'Its parameter is called query, while cloud.complete calls it prompt.',
        ),
        requires=(
            'ANTHROPIC_API_KEY',
        ),
        params=(
            Param("query", desc="what to ask about the image"),
            Param("model", type="enum", default="haiku", choices=("haiku", "sonnet", "opus")),
            Param("max_tokens", type="int",
                  desc="optional ceiling; empty = 1024 (cloud answers cost money)"),
        ),
        consumes="one",
        input_type="image",
        output_type="text",
    ),

    # ----- Data (generic table CRUD) ---------------------------------------
    Op(
        name="db.query",
        summary="Query rows from a table with filter/order/pagination.",
        plain="Looks up rows in a table that match a filter.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
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
        name="db.get",
        summary="Fetch a single row by id.",
        plain="Fetches one specific row from a table by its id.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
        params=(
            Param("table", required=True),
            Param("row_id", type="int", required=True),
        ),
        consumes="none",
        output_type="text",
    ),
    Op(
        name="db.insert",
        summary="Create a new row (field values from stdin JSON or 'data').",
        plain="Adds a new row to a table.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        effect='writes',
        caveats=(
            'Field values arrive as JSON — chain data.pick when they have to be built from an earlier step.',
        ),
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
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
        name="db.update",
        summary="Patch an existing row by id (partial update).",
        plain="Changes fields on an existing row.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        effect='writes',
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
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
        name="db.delete",
        summary="Delete a row by id.",
        plain="Removes a row from a table.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        effect='writes',
        caveats=(
            'Deletes without asking; the pipeline has no undo.',
        ),
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
        params=(
            Param("table", required=True),
            Param("row_id", type="int", required=True),
        ),
        consumes="none",
        output_type="text",
    ),
    Op(
        name="db.list_fields",
        summary="Get the field schema for a table.",
        plain="Lists the columns (fields) a table has.",
        bucket="db",
        runs_on='local-service',
        service='Baserow',
        requires=(
            'Baserow running',
            'BASEROW_TOKEN',
        ),
        params=(Param("table", required=True),),
        consumes="none",
        output_type="text",
    ),

    # ----- Web & stock ------------------------------------------------------
    Op(
        name="web.search",
        summary="Search the web via local SearXNG.",
        plain="Searches the web (via your local SearXNG) and returns the hits.",
        bucket="web",
        runs_on='local-service',
        service='SearXNG',
        requires=(
            'SearXNG running',
        ),
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
        summary="Fetch a web page and return its text (cut at max_chars, and the "
                "cut is reported in the run log).",
        plain="Downloads a web page and strips it down to plain readable text.",
        bucket="web",
        runs_on='cloud',
        service='the open web',
        caveats=(
            'Cuts at max_chars (20000 by default) and reports the true length.',
        ),
        params=(
            Param("url", desc="page URL; falls back to stdin"),
            Param("max_chars", type="int", default="20000",
                  desc="length ceiling; a cut page reports its true length"),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="text",
    ),
    Op(
        name="stock.search",
        summary="Search stock photos (Pexels / Pixabay).",
        plain="Searches stock-photo sites (Pexels/Pixabay) for pictures matching a query.",
        bucket="web",
        runs_on='cloud',
        service='Pexels / Pixabay',
        requires=(
            'PEXELS_API_KEY / PIXABAY_API_KEY',
        ),
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
        name="data.pick",
        summary="Take one value out of an earlier step's JSON (dotted path, list "
                "indices as numbers). The joint between ops that emit a structure "
                "and ops that want single values.",
        plain="Picks a single value out of an earlier step's result — the address of "
              "the first search hit, say.",
        bucket="data",
        runs_on='local-cpu',
        service='in-process',
        caveats=(
            'A missing path is an error unless `default` is set — an empty value would travel on unnoticed.',
            'A scalar travels on as itself, a branch as JSON.',
        ),
        params=(
            Param("path", required=True,
                  desc="dotted path, e.g. results.0.url; -1 is the last entry"),
            Param("default",
                  desc="value to emit when the path is missing; without it a "
                       "missing path is an error"),
        ),
        consumes="one",
        input_type="text",
        output_type="text",
    ),

    Op(
        name="stock.download",
        summary="Download a stock photo into a store as an image ref. Takes no "
                "stdin: source and image_url are picked out of a stock.search "
                "result by a field-pick step, not by this op.",
        plain="Downloads a chosen stock photo into your library so later steps can use it.",
        bucket="web",
        runs_on='cloud',
        service='Pexels / Pixabay',
        caveats=(
            'Takes no stdin: chain stock.search → data.pick → this op.',
        ),
        requires=(
            'PEXELS_API_KEY / PIXABAY_API_KEY',
        ),
        params=(
            Param("source", type="enum", required=True, choices=("pexels", "pixabay")),
            Param("image_url", required=True, desc="full image URL"),
            Param("image_id", desc="stock API image id"),
        ),
        # Declares no stdin because the handler reads none. It previously claimed
        # one text input, which no wiring could satisfy: stock.search emits a
        # RESULT LIST as JSON, and this op needs two single values out of it.
        # Pulling one field out of a JSON is a general need (the scheduled-publish
        # layer has the same one), so it belongs in its own field-pick op rather
        # than hidden inside this one - where nobody would look for it.
        consumes="none",
        output_type="image",
    ),

    # ----- Delivery (generalized notify) -----------------------------------
    Op(
        name="notify",
        summary="Send the previous step's output (type-aware) to a channel, no pause; pass it through.",
        plain="Sends the previous step's result (image/video/text) to a chat without pausing, just a heads-up.",
        bucket="delivery",
        runs_on='gateway',
        service='OpenClaw gateway → Signal',
        effect='outward',
        caveats=(
            'An image with a caption goes as TWO messages: the picture, then the words. The gateway cuts a caption sent with media down to its first character.',
            'Passes its input through unchanged, so the chain continues.',
        ),
        requires=(
            'the OpenClaw gateway container',
            'MORA02_SIGNAL_TARGET, unless ?target= is given',
        ),
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
        plain="Swaps which local AI model is running (a bigger or smaller brain), then continues the chain.",
        bucket="llm",
        runs_on='local-service',
        service='llama.cpp profile switcher',
        effect='writes',
        caveats=(
            'Takes the local model down for about a minute; no llm.* op can answer meanwhile.',
            'Passes its input through unchanged, so the chain continues.',
        ),
        requires=(
            'the profile watcher on the host (/opt/mora02/llm-switch)',
        ),
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
        plain="Composes an original piece of music from a description (mood, tempo, optional lyrics).",
        bucket="audio",
        runs_on='local-gpu',
        service='ComfyUI (music flow)',
        caveats=(
            'Style tags carry further than full sentences; lyrics are optional.',
        ),
        requires=(
            'ComfyUI running',
        ),
        params=(
            Param("prompt", desc="music style/genre tags; falls back to the stdin value"),
            Param("lyrics", desc="lyrics text; empty = instrumental"),
            Param("duration", type="int", default="30", desc="length in seconds"),
            Param("bpm", type="int", default="120", desc="tempo in beats per minute"),
            Param("key", default="C major", desc="musical key/scale, e.g. 'C major', 'A minor'"),
            Param("time_signature", default="4", desc="time signature (beats per bar)"),
            Param("language", default="en", desc="lyrics language, e.g. en, de"),
            Param("steps", type="int", default="8", desc="sampler steps (turbo default 8)", advanced=True),
            Param("seed", type="int", advanced=True),
            Param("cfg_scale", desc="text guidance strength (default 2.0)", advanced=True),
            Param("temperature", desc="sampling temperature (default 0.85)", advanced=True),
            Param("top_p", desc="nucleus sampling top-p (default 0.9)", advanced=True),
            Param("top_k", type="int", desc="top-k sampling (default 0 = off)", advanced=True),
            Param("min_p", desc="min-p sampling (default 0.0)", advanced=True),
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
        summary="Publish an image or text post to LinkedIn (UGC API). Stdin takes "
                "either an image ref or the post text (optional — omit both and "
                "pass ?text=). Returns the post URL.",
        plain="Posts text (and optionally an image) to LinkedIn and returns the post link.",
        bucket="publish",
        runs_on='cloud',
        service='LinkedIn UGC API',
        effect='outward',
        caveats=(
            'Publishes publicly, and nothing here can take it back.',
            'An asset ref on stdin becomes an image post; any other value becomes the text.',
        ),
        requires=(
            'MORA02_LINKEDIN_TOKEN (expires after about 60 days)',
            'MORA02_LINKEDIN_AUTHOR',
        ),
        params=(
            Param("text", desc="post caption/body text (often a {\"from\": <llm step>} ref)"),
            Param("author", desc="author URN urn:li:person:…; falls back to env MORA02_LINKEDIN_AUTHOR"),
            Param("visibility", type="enum", default="PUBLIC",
                  choices=("PUBLIC", "CONNECTIONS"), desc="post visibility"),
        ),
        consumes="one",
        consumes_optional=True,
        # "any", not "image": an asset ref on stdin becomes an image share, any
        # other value becomes the post text (the handler discriminates on the
        # asset:// prefix, exactly as notify does). Declaring "image" made the
        # builder refuse the commonest wiring of all - an llm step into a post.
        input_type="any",
        output_type="text",  # the post URL
    ),

    # ----- 3D typography (Blender PixelText worker) ------------------------
    Op(
        name="pixeltext.render",
        summary="Render a 3D pixel-cube text/word animation via the Blender "
                "PixelText worker (GPU). Text on stdin or ?text=. Returns an "
                "MP4 (or PNG) asset ref.",
        plain="Renders your word(s) as chunky 3D pixel-cube typography, as a short animated video.",
        bucket="blender",
        runs_on='local-gpu',
        service='Blender PixelText worker',
        caveats=(
            'Minutes per render — one of the two slowest ops.',
        ),
        requires=(
            'the Blender worker container',
        ),
        params=(
            Param("text", desc="the word(s) to render; falls back to stdin. In "
                  "multi mode, split on '/' into a word sequence"),
            Param("mode", type="enum", default="single", choices=("single", "multi"),
                  desc="single word, or a multi-word transition sequence (split "
                  "text on '/'). multi animates on its own; single is static "
                  "unless an effect_* below is on"),
            Param("template", type="enum", default="", choices=_PIXELTEXT_TEMPLATES,
                  desc="Blender .blend template (empty = worker procedural default)"),
            Param("render_format", type="enum", default="MP4", choices=("MP4", "PNG"),
                  desc="animated MP4 or single-frame PNG"),
            Param("cube_color", default="#FFFFFF", desc="pixel cube color (hex)"),
            Param("bg_color", default="#000000", desc="background color (hex)"),
            Param("duration", type="int", default=5,
                  desc="seconds (single mode / per-word hold)", advanced=True),
            # Single-mode motion: without one of these, a single word renders as a
            # motionless clip. multi mode animates via word transitions regardless.
            Param("effect_pulse", type="bool", default=False,
                  desc="single mode: pulse cube size — adds motion", advanced=True),
            Param("effect_float", type="bool", default=False,
                  desc="single mode: bob/float the cubes — adds motion", advanced=True),
            Param("effect_shuffle", type="bool", default=False,
                  desc="single mode: random blink in/out loop — adds motion", advanced=True),
        ),
        consumes="one",
        consumes_optional=True,
        input_type="text",
        output_type="video",
    ),

    Op(
        name="image.edit",
        summary="Edit an existing image from a prompt (Gemini image models).",
        plain="Changes a picture you already have — e.g. put a blue hat on the rabbit — instead of drawing a new one.",
        bucket="image",
        runs_on='cloud',
        service='ComfyUI → Gemini image models',
        cost='paid',
        cost_note='Per image, by the flow it uses. The default nanban (Nano Banana 2) '
                  'is ~0,058 € at 1K, 0,039-0,130 € depending on resolution; nanban-pro '
                  '~0,034 €. List prices looked up 2026-08-29.',
        requires=(
            'ComfyUI running',
            'GOOGLE_API_KEY',
        ),
        status="wired",
        params=(
            Param("prompt", required=True,
                  desc="what to change about the incoming image, e.g. 'add a blue hat'"),
            Param("flow", type="enum", default="nanban",
                  choices=("nanban", "nanban-pro"), desc="editing model (external API)"),
            Param("format", desc="portrait|landscape|square — omit to keep the source shape",
                  advanced=True),
            Param("temperature", desc="how freely the model reinterprets, 0.0-2.0",
                  advanced=True),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="image.cutout",
        summary="Cut the subject out of an image and return a PNG with an alpha channel.",
        plain="Frees the main subject from its background and hands on a picture with a see-through background.",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        requires=(
            'ComfyUI running',
        ),
        status="wired",
        params=(
            Param("model", type="enum", default="isnet", choices=("isnet", "u2net", "human", "anime", "silueta", "inspyrenet",), desc="matting model; 'human' for people, 'inspyrenet' is finer on hair and fur but slower"),
            Param("device", type="enum", default="CUDA", choices=("CUDA", "CPU",), desc="where the matting model runs; ignored by inspyrenet", advanced=True),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="image.erase",
        summary="Remove the subject from an image and fill the gap with the surrounding scene (Flux Fill).",
        plain="Takes the main subject out of a picture and paints the background back in where it stood.",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        caveats=(
            'Needs a recognisable subject; on an empty scene it has nothing to remove.',
        ),
        requires=(
            'ComfyUI running',
        ),
        status="wired",
        params=(
            Param("prompt", desc="what the emptied area should show; omit for a plain continuation of the scene"),
            Param("model", type="enum", default="isnet", choices=("isnet", "u2net", "human", "anime", "silueta",), desc="which model decides where the subject is"),
            Param("grow", type="int", default="90",
                  desc="how many pixels the hole is widened. Not cosmetic: at a small "
                       "value the subject's silhouette stays readable, and a fill model "
                       "reads a subject-shaped hole as an invitation to paint one",
                  advanced=True),
            Param("seed", type="int", desc="fix the noise to repeat the same fill", advanced=True),
            Param("steps", type="int", desc="sampling steps; more is slower and slightly cleaner", advanced=True),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="image.facefix",
        summary="Re-render the faces in an image at higher detail, leaving the rest untouched.",
        plain="Sharpens the faces in a picture — useful when people stand far enough away that their features came out mushy.",
        bucket="image",
        runs_on='local-gpu',
        service='ComfyUI',
        caveats=(
            'Touches faces only; the rest of the picture is left alone.',
        ),
        requires=(
            'ComfyUI running',
        ),
        status="wired",
        params=(
            Param("prompt", desc="what the refined face should look like; omit for a plain detail pass"),
            Param("denoise", default="0.4", desc="how far the face may change, 0.1-0.6; past roughly 0.6 it stops being the same person", advanced=True),
            Param("seed", type="int", desc="fix the noise to repeat the same pass", advanced=True),
            Param("steps", type="int", desc="sampling steps for the face crop", advanced=True),
        ),
        consumes="one",
        input_type="image",
        output_type="image",
    ),
    Op(
        name="source.find",
        summary="Pick a named file out of a store by path or pattern, never by date.",
        plain="Fetches exactly the file you asked for - the product photo for SKU 4711 - instead of whatever happened to be made last.",
        bucket="source",
        runs_on="local-cpu",
        service="the asset stores",
        caveats=(
            "pick=one is the default and refuses an ambiguous match: it lists the candidates instead of choosing one for you.",
            "Sorting for first/last is alphabetical by path, not by modification date - that is the whole difference to source.file.",
            "A store has no customer border. asset://library/kunde-b/... is a valid ref for anyone who can reach the store.",
        ),
        status="wired",
        params=(
            Param("store", default="library", desc="logical store to look in"),
            Param("path", desc="exact path inside the store, e.g. kunde-a/produktfotos/4711.png"),
            Param("match", desc="glob instead of an exact path, e.g. kunde-a/produktfotos/*.png"),
            Param("pick", type="enum", default="one", choices=("one", "first", "last", "all",), desc="what to do when the pattern matches more than one file"),
        ),
        consumes="none",
        output_type="any",
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
