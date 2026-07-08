# Pipeline Vocabulary

> Generated from `mora02_core.pipeline.vocab` by `scripts/gen-pipeline-vocab-doc.py`. Do not edit by hand — edit the registry and regenerate.

The step *ops* a mora02 pipeline is built from. A pipeline spec lists steps by op name; the compiler validates each against this vocabulary and emits a Lobster workflow. Step outputs are named refs — by default a step's id is the text before the first dot (`image.generate` → `image`), and a step reads the previous op step's output unless `in:` overrides it.

**Status:** 🟢 `wired` = runnable today · 🟡 `planned` = capability exists (lib/endpoint) but no pipeline handler yet; the compiler refuses to build a pipeline that uses it until it is wired.

## Spec constructs (not ops)

- **`gate`** 🟢 — a pure human pause: `- gate: "Approve?"`. Resumes with a yes/no decision; nothing is sent.
- **`review`** 🟢 — human-in-the-loop with delivery: `- review: "Approve?"` sends the previous step's output to a human *type-aware* (image/video/audio/text, inferred from the prior op's output) **and** pauses for approval. Compiles to a `notify` sub-step + an input gate; supersedes the manual `notify.image` + `gate` pattern.

## Ops by bucket

| Op | Status | Bucket | Default id | Consumes | Input | Output |
|----|--------|--------|-----------|----------|-------|--------|
| [`source.file`](#sourcefile) | 🟢 wired | source | `source` | none | any | image |
| [`notify.image`](#notifyimage) | 🟢 wired | delivery | `notify` | one | image | image |
| [`image.generate`](#imagegenerate) | 🟢 wired | visual | `image` | one (opt) | text | image |
| [`image.upscale`](#imageupscale) | 🟢 wired | visual | `image` | one | image | image |
| [`image.expand`](#imageexpand) | 🟢 wired | visual | `image` | one | image | image |
| [`video.generate`](#videogenerate) | 🟢 wired | visual | `video` | one (opt) | any | video |
| [`video.last_frame`](#videolast_frame) | 🟢 wired | visual | `video` | one | video | image |
| [`clip.generate`](#clipgenerate) | 🟢 wired | media | `clip` | many | any | video |
| [`text.overlay`](#textoverlay) | 🟢 wired | media | `text` | one (opt) | text | image |
| [`gif.create`](#gifcreate) | 🟢 wired | media | `gif` | many | image | video |
| [`tts.speak`](#ttsspeak) | 🟢 wired | audio | `tts` | one (opt) | text | audio |
| [`llm.image_prompt`](#llmimage_prompt) | 🟢 wired | llm | `llm` | one (opt) | text | text |
| [`llm.complete`](#llmcomplete) | 🟢 wired | llm | `llm` | one (opt) | text | text |
| [`llm.summarize`](#llmsummarize) | 🟢 wired | llm | `llm` | one | text | text |
| [`llm.classify`](#llmclassify) | 🟢 wired | llm | `llm` | one | text | text |
| [`llm.extract`](#llmextract) | 🟢 wired | llm | `llm` | one | text | text |
| [`llm.translate`](#llmtranslate) | 🟢 wired | llm | `llm` | one | text | text |
| [`cloud.complete`](#cloudcomplete) | 🟢 wired | cloud | `cloud` | one (opt) | text | text |
| [`cloud.vision`](#cloudvision) | 🟢 wired | cloud | `cloud` | one | image | text |
| [`baserow.query`](#baserowquery) | 🟢 wired | data | `baserow` | none | any | text |
| [`baserow.get`](#baserowget) | 🟢 wired | data | `baserow` | none | any | text |
| [`baserow.insert`](#baserowinsert) | 🟢 wired | data | `baserow` | one (opt) | text | text |
| [`baserow.update`](#baserowupdate) | 🟢 wired | data | `baserow` | one (opt) | text | text |
| [`baserow.delete`](#baserowdelete) | 🟢 wired | data | `baserow` | none | any | text |
| [`baserow.list_fields`](#baserowlist_fields) | 🟢 wired | data | `baserow` | none | any | text |
| [`web.search`](#websearch) | 🟢 wired | web | `web` | one (opt) | text | text |
| [`web.fetch`](#webfetch) | 🟢 wired | web | `web` | one (opt) | text | text |
| [`stock.search`](#stocksearch) | 🟢 wired | web | `stock` | one (opt) | text | text |
| [`stock.download`](#stockdownload) | 🟢 wired | web | `stock` | one (opt) | text | image |
| [`notify`](#notify) | 🟢 wired | delivery | `notify` | one (opt) | any | any |
| [`llm.switch`](#llmswitch) | 🟢 wired | llm | `llm` | one (opt) | any | any |
| [`music.generate`](#musicgenerate) | 🟢 wired | audio | `music` | one (opt) | text | audio |
| [`publish.linkedin`](#publishlinkedin) | 🟢 wired | publish | `publish` | one (opt) | image | text |
| [`pixeltext.render`](#pixeltextrender) | 🟢 wired | visual | `pixeltext` | one (opt) | text | video |

## source.file

🟢 **wired** · bucket: `source`

Bring an existing file from a store into the pipeline as a ref.

- **Default step id:** `source`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `store` | string | no | `comfyui` | logical store to read from |
| `name` | string | no |  | exact filename; omit to auto-pick from the store |
| `pick` | enum | no | `latest` | which file to pick when 'name' is omitted (by mtime) (one of: latest, oldest) |

## notify.image

🟢 **wired** · bucket: `delivery`

(superseded by 'notify') Send an image ref to a chat for review, pass it through.

- **Default step id:** `notify`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `target` | string | no |  | E.164 recipient; falls back to env MORA02_SIGNAL_TARGET |
| `channel` | string | no | `signal` | notify channel |
| `message` | string | no |  | optional caption sent with the image |

## image.generate

🟢 **wired** · bucket: `visual`

Generate an image from a prompt via ComfyUI (9 selectable flows).

- **Default step id:** `image`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | prompt text; falls back to the stdin value if omitted |
| `flow` | enum | no | `photo` | model/flow preset (local diffusion or external API) (one of: sd15, photo, concept, epic, flux, nanban, nanban-pro, gpt-image, flux-ultra) |
| `format` | string | no |  | portrait|landscape|square or WIDTHxHEIGHT |
| `batch_size` | int | no |  | number of images to generate |
| `testrun` | bool | no |  | set '1' for a fast low-quality test run |

## image.upscale

🟢 **wired** · bucket: `visual`

Upscale an image (hybrid SDXL-Tile + UltraSharp).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `factor` | int | no | `2` | scale factor 1.5–4.0 |
| `prompt` | string | no |  | optional guidance prompt |
| `denoise` | string | no |  | refinement denoise 0.05–0.5 (default 0.2) |
| `seed` | int | no |  |  |

## image.expand

🟢 **wired** · bucket: `visual`

Outpaint / expand an image to a larger canvas (FLUX).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | what to paint into the new area |
| `target_size` | int | no | `1920` | target long edge in px |
| `feathering` | string | no |  | edge blend amount |
| `seed` | int | no |  |  |

## video.generate

🟢 **wired** · bucket: `visual`

Generate video via WAN 2.2 — text-to-video, image-to-video, or start+end frames.

- **Default step id:** `video`  
- **Consumes (stdin):** one (optional) (any)  
- **Emits (stdout):** video

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | prompt; falls back to stdin |
| `mode` | enum | no | `t2v` | t2v=text only, i2v=from start image, i2i2v=start+end frames (one of: t2v, i2v, i2i2v) |
| `start_image` | string | no |  | start frame ref (i2v / i2i2v) |
| `end_image` | string | no |  | end frame ref (i2i2v) |
| `length` | int | no |  | frames 17–201 |
| `fps` | int | no |  | frames per second 8–60 |
| `seed` | int | no |  |  |

## video.last_frame

🟢 **wired** · bucket: `visual`

Extract the last frame of a video as an image ref — chains i2v videos (each new video starts from the previous one's final frame).

- **Default step id:** `video`  
- **Consumes (stdin):** one (video)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `position` | enum | no | `last` | which frame to grab (one of: last, first) |

## clip.generate

🟢 **wired** · bucket: `media`

Assemble one or more image/video refs into a single MP4 (Ken-Burns).

- **Default step id:** `clip`  
- **Consumes (stdin):** many (any)  
- **Emits (stdout):** video

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | no |  | output filename; auto-generated if omitted |
| `resolution` | string | no | `1080p` | 1080p|720p|4k|square|story|reels or WxH |
| `durations` | string | no | `4` | per-input seconds (single or comma list) |
| `animation` | enum | no | `pan` | motion style (one of: pan, zoom_in, zoom_out, none) |
| `soundtrack` | string | no |  | optional audio ref to lay over the clip as its music track (handler support planned) |

## text.overlay

🟢 **wired** · bucket: `media`

Render multi-line text onto a flat-color background as a PNG.

- **Default step id:** `text`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | the text; falls back to stdin |
| `size` | string | no | `1080x1080` | canvas WxH |
| `template` | enum | no | `dark` | background theme (one of: dark, darker, light, black) |
| `font` | enum | no | `bold` |  (one of: bold, bold-italic, thin, thin-italic) |
| `fontsize` | string | no | `medium` | small|medium|large or px |
| `layout` | enum | no | `left` |  (one of: left, centered) |

## gif.create

🟢 **wired** · bucket: `media`

Animate multiple images into an animated GIF.

- **Default step id:** `gif`  
- **Consumes (stdin):** many (image)  
- **Emits (stdout):** video

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `durations` | string | no | `1` | per-frame seconds (single or comma list) |
| `quality` | enum | no | `medium` |  (one of: low, medium, high, ultra) |
| `size` | string | no |  | output WxH or width-only |

## tts.speak

🟢 **wired** · bucket: `audio`

Synthesize speech audio from text (piper/kokoro/chatterbox).

- **Default step id:** `tts`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** audio

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | text to speak; falls back to stdin |
| `language` | string | no | `en` | e.g. en, de |
| `voice` | string | no |  | voice id; default per language |
| `format` | enum | no | `wav` |  (one of: wav, mp3) |
| `engine` | enum | no | `auto` |  (one of: auto, piper, kokoro, chatterbox) |
| `speed` | string | no |  | rate multiplier (default 1.0) |

## llm.image_prompt

🟢 **wired** · bucket: `llm`

Expand a short subject into one rich text-to-image prompt (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subject` | string | no |  | the subject; falls back to the stdin value if omitted |

## llm.complete

🟢 **wired** · bucket: `llm`

Free-form text completion (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | user prompt; falls back to stdin |
| `system` | string | no |  | system prompt |
| `temperature` | string | no |  | sampling temperature (default 0.7) |
| `max_tokens` | int | no |  | max output tokens (default 512) |

## llm.summarize

🟢 **wired** · bucket: `llm`

Summarize the input text (local qwen, thin wrapper over llm.complete).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `max_tokens` | int | no |  | summary length budget |

## llm.classify

🟢 **wired** · bucket: `llm`

Classify the input text into one of the given labels (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `labels` | string | yes |  | comma-separated candidate labels |

## llm.extract

🟢 **wired** · bucket: `llm`

Extract structured fields from the input text as JSON (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `fields` | string | yes |  | comma-separated fields to extract |

## llm.translate

🟢 **wired** · bucket: `llm`

Translate the input text to a target language (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `to` | string | yes |  | target language, e.g. de, en |
| `from` | string | no |  | source language; auto-detect if omitted |

## cloud.complete

🟢 **wired** · bucket: `cloud`

Text completion via Claude (cloud; peripheral content tasks only).

- **Default step id:** `cloud`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | user prompt; falls back to stdin |
| `system` | string | no |  | system prompt |
| `model` | enum | no | `sonnet` |  (one of: haiku, sonnet, opus) |
| `temperature` | string | no |  | sampling temperature (default 0.7) |
| `max_tokens` | int | no |  |  |

## cloud.vision

🟢 **wired** · bucket: `cloud`

Describe / analyze an image with an optional question (Claude vision).

- **Default step id:** `cloud`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | what to ask about the image |
| `model` | enum | no | `haiku` |  (one of: haiku, sonnet, opus) |

## baserow.query

🟢 **wired** · bucket: `data`

Query rows from a table with filter/order/pagination.

- **Default step id:** `baserow`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  | table name or numeric id |
| `filter` | string | no |  | filter expression / JSON |
| `order_by` | string | no |  | e.g. -created_at |
| `size` | int | no | `50` | rows per page (max 200) |

## baserow.get

🟢 **wired** · bucket: `data`

Fetch a single row by id.

- **Default step id:** `baserow`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |

## baserow.insert

🟢 **wired** · bucket: `data`

Create a new row (field values from stdin JSON or 'data').

- **Default step id:** `baserow`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `data` | string | no |  | JSON field values; falls back to stdin |

## baserow.update

🟢 **wired** · bucket: `data`

Patch an existing row by id (partial update).

- **Default step id:** `baserow`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |
| `data` | string | no |  | JSON field values; falls back to stdin |

## baserow.delete

🟢 **wired** · bucket: `data`

Delete a row by id.

- **Default step id:** `baserow`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |

## baserow.list_fields

🟢 **wired** · bucket: `data`

Get the field schema for a table.

- **Default step id:** `baserow`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |

## web.search

🟢 **wired** · bucket: `web`

Search the web via local SearXNG.

- **Default step id:** `web`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | search query; falls back to stdin |
| `categories` | string | no | `general` | SearXNG category |

## web.fetch

🟢 **wired** · bucket: `web`

Fetch a web page and return its text.

- **Default step id:** `web`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | no |  | page URL; falls back to stdin |

## stock.search

🟢 **wired** · bucket: `web`

Search stock photos (Pexels / Pixabay).

- **Default step id:** `stock`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | search term; falls back to stdin |
| `source` | enum | no | `pexels` |  (one of: pexels, pixabay) |
| `count` | int | no | `5` |  |
| `orientation` | enum | no | `landscape` |  (one of: landscape, portrait, square) |

## stock.download

🟢 **wired** · bucket: `web`

Download a stock photo into a store as an image ref.

- **Default step id:** `stock`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | enum | yes |  |  (one of: pexels, pixabay) |
| `image_url` | string | yes |  | full image URL |
| `image_id` | string | no |  | stock API image id |

## notify

🟢 **wired** · bucket: `delivery`

Send the previous step's output (type-aware) to a channel, no pause; pass it through.

- **Default step id:** `notify`  
- **Consumes (stdin):** one (optional) (any)  
- **Emits (stdout):** any

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `channel` | string | no | `signal` | notify channel |
| `target` | string | no |  | recipient; falls back to env MORA02_SIGNAL_TARGET |
| `message` | string | no |  | optional caption / text body |
| `title` | string | no |  | optional title prepended to message |
| `link` | string | no |  | optional link appended to message |

## llm.switch

🟢 **wired** · bucket: `llm`

Switch the active local LLM (llama.cpp profile), like the Pilot model switcher. Takes ~10-20s; the swap is global and persistent across the whole box. Passes stdin through unchanged.

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (any)  
- **Emits (stdout):** any

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `profile` | enum | yes |  | target llama.cpp profile to load (one of: qwen3-14b, qwen3-8b, qwen25-7b, qwen25-coder, nous-hermes, magistral) |

## music.generate

🟢 **wired** · bucket: `audio`

Generate music/song audio from style tags + optional lyrics via ComfyUI ACE-Step 1.5 (local).

- **Default step id:** `music`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** audio

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | music style/genre tags; falls back to the stdin value |
| `lyrics` | string | no |  | lyrics text; empty = instrumental |
| `duration` | int | no | `30` | length in seconds |
| `bpm` | int | no | `120` | tempo in beats per minute |
| `key` | string | no | `C major` | musical key/scale, e.g. 'C major', 'A minor' |
| `time_signature` | string | no | `4` | time signature (beats per bar) |
| `language` | string | no | `en` | lyrics language, e.g. en, de |
| `steps` | int | no | `8` | sampler steps (turbo default 8) |
| `seed` | int | no |  |  |
| `cfg_scale` | string | no |  | text guidance strength (default 2.0) |
| `temperature` | string | no |  | sampling temperature (default 0.85) |
| `top_p` | string | no |  | nucleus sampling top-p (default 0.9) |
| `top_k` | int | no |  | top-k sampling (default 0 = off) |
| `min_p` | string | no |  | min-p sampling (default 0.0) |
| `ref_audio` | string | no |  | optional reference-audio ref for timbre transfer |

## publish.linkedin

🟢 **wired** · bucket: `publish`

Publish an image or text post to LinkedIn (UGC API). Image ref on stdin (optional — omit for a text-only post). Returns the post URL.

- **Default step id:** `publish`  
- **Consumes (stdin):** one (optional) (image)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | post caption/body text (often a {"from": <llm step>} ref) |
| `author` | string | no |  | author URN urn:li:person:…; falls back to env MORA02_LINKEDIN_AUTHOR |
| `visibility` | enum | no | `PUBLIC` | post visibility (one of: PUBLIC, CONNECTIONS) |

## pixeltext.render

🟢 **wired** · bucket: `visual`

Render a 3D pixel-cube text/word animation via the Blender PixelText worker (GPU). Text on stdin or ?text=. Returns an MP4 (or PNG) asset ref.

- **Default step id:** `pixeltext`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** video

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | the word(s) to render; falls back to stdin. In multi mode, split on '/' into a word sequence |
| `mode` | enum | no | `single` | single word, or a multi-word transition sequence (split text on '/'). multi animates on its own; single is static unless an effect_* below is on (one of: single, multi) |
| `template` | enum | no | `` | Blender .blend template (empty = worker procedural default) (one of: , default.blend, test3.blend, test4.blend, test5.blend) |
| `render_format` | enum | no | `MP4` | animated MP4 or single-frame PNG (one of: MP4, PNG) |
| `cube_color` | string | no | `#FFFFFF` | pixel cube color (hex) |
| `bg_color` | string | no | `#000000` | background color (hex) |
| `duration` | int | no | `5` | seconds (single mode / per-word hold) |
| `effect_pulse` | bool | no | `False` | single mode: pulse cube size — adds motion |
| `effect_float` | bool | no | `False` | single mode: bob/float the cubes — adds motion |
| `effect_shuffle` | bool | no | `False` | single mode: random blink in/out loop — adds motion |

