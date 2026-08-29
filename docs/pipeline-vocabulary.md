# Pipeline Vocabulary

> Generated from `mora02_core.pipeline.vocab` by `scripts/gen-pipeline-vocab-doc.py`. Do not edit by hand — edit the registry and regenerate.

The step *ops* a mora02 pipeline is built from, grouped by kind. Each op has a plain-language line (what it does) and the technical contract (what it reads/emits, its parameters). A pipeline spec lists steps by op name; the compiler validates each against this vocabulary and emits a Lobster workflow. Step outputs are named refs — by default a step's id is the text before the first dot (`image.generate` → `image`), and a step reads the previous step's output unless `in:` overrides it.

**Status:** 🟢 `wired` = runnable today · 🟡 `planned` = capability exists (lib/endpoint) but no pipeline handler yet; the compiler refuses to build a pipeline that uses it until it is wired.

## Spec constructs (not ops)

- **`gate`** 🟢 — a pure human pause: `- gate: "Approve?"`. Resumes with a yes/no decision; nothing is sent.
- **`review`** 🟢 — human-in-the-loop with delivery: `- review: "Approve?"` sends the previous step's output to a human *type-aware* (image/video/audio/text, inferred from the prior op's output) **and** pauses for approval. Compiles to a `notify` sub-step + an input gate; supersedes the manual `notify.image` + `gate` pattern.

## At a glance

### Sources

| Op | What it does | Status |
|----|--------------|--------|
| [`source.file`](#sourcefile) | Grabs a file that already exists (e.g. the latest image ComfyUI made) and hands it to the next step. | 🟢 |

### Image generation

| Op | What it does | Status |
|----|--------------|--------|
| [`image.generate`](#imagegenerate) | Makes a brand-new picture from a text description. | 🟢 |
| [`image.upscale`](#imageupscale) | Enlarges a picture and sharpens it, without making it blurry. | 🟢 |
| [`image.expand`](#imageexpand) | Extends a picture beyond its edges, inventing more scenery around it (outpainting). | 🟢 |
| [`image.edit`](#imageedit) | Changes a picture you already have — e.g. put a blue hat on the rabbit — instead of drawing a new one. | 🟢 |
| [`image.cutout`](#imagecutout) | Frees the main subject from its background and hands on a picture with a see-through background. | 🟢 |
| [`image.erase`](#imageerase) | Takes the main subject out of a picture and paints the background back in where it stood. | 🟢 |
| [`image.facefix`](#imagefacefix) | Sharpens the faces in a picture — useful when people stand far enough away that their features came out mushy. | 🟢 |

### Video

| Op | What it does | Status |
|----|--------------|--------|
| [`video.generate`](#videogenerate) | Turns a prompt (or a still image) into a short moving video clip. | 🟢 |
| [`video.last_frame`](#videolast_frame) | Grabs the final still frame of a video, handy to keep a scene going into the next clip. | 🟢 |

### 3D text (Blender / PixelText)

| Op | What it does | Status |
|----|--------------|--------|
| [`pixeltext.render`](#pixeltextrender) | Renders your word(s) as chunky 3D pixel-cube typography, as a short animated video. | 🟢 |

### Media finishing

| Op | What it does | Status |
|----|--------------|--------|
| [`clip.generate`](#clipgenerate) | Stitches several videos together into one clip, optionally laying a music track over it. | 🟢 |
| [`text.overlay`](#textoverlay) | Writes text onto a colored background as a simple image card. | 🟢 |
| [`gif.create`](#gifcreate) | Turns several images into one looping animated GIF. | 🟢 |

### Audio

| Op | What it does | Status |
|----|--------------|--------|
| [`tts.speak`](#ttsspeak) | Reads text out loud and saves it as an audio file (text-to-speech). | 🟢 |
| [`music.generate`](#musicgenerate) | Composes an original piece of music from a description (mood, tempo, optional lyrics). | 🟢 |

### Local LLM

| Op | What it does | Status |
|----|--------------|--------|
| [`llm.image_prompt`](#llmimage_prompt) | Takes a short idea and expands it into a rich, detailed prompt for image generation. | 🟢 |
| [`llm.complete`](#llmcomplete) | Asks the local AI to write or answer something freely. | 🟢 |
| [`llm.summarize`](#llmsummarize) | Shortens a long text down to its key points. | 🟢 |
| [`llm.classify`](#llmclassify) | Sorts a text into one of a set of labels you provide. | 🟢 |
| [`llm.extract`](#llmextract) | Pulls specific facts (e.g. name, date, price) out of a text. | 🟢 |
| [`llm.translate`](#llmtranslate) | Translates text into another language. | 🟢 |
| [`llm.switch`](#llmswitch) | Swaps which local AI model is running (a bigger or smaller brain), then continues the chain. | 🟢 |

### Cloud LLM

| Op | What it does | Status |
|----|--------------|--------|
| [`cloud.complete`](#cloudcomplete) | Asks a cloud AI (Claude) to write or answer something, for the few tasks the local model can't handle. | 🟢 |
| [`cloud.vision`](#cloudvision) | Shows a cloud AI (Claude) an image and asks it to describe or analyze it. | 🟢 |

### Data (tables)

| Op | What it does | Status |
|----|--------------|--------|
| [`db.query`](#dbquery) | Looks up rows in a table that match a filter. | 🟢 |
| [`db.get`](#dbget) | Fetches one specific row from a table by its id. | 🟢 |
| [`db.insert`](#dbinsert) | Adds a new row to a table. | 🟢 |
| [`db.update`](#dbupdate) | Changes fields on an existing row. | 🟢 |
| [`db.delete`](#dbdelete) | Removes a row from a table. | 🟢 |
| [`db.list_fields`](#dblist_fields) | Lists the columns (fields) a table has. | 🟢 |

### Web & stock

| Op | What it does | Status |
|----|--------------|--------|
| [`web.search`](#websearch) | Searches the web (via your local SearXNG) and returns the hits. | 🟢 |
| [`web.fetch`](#webfetch) | Downloads a web page and strips it down to plain readable text. | 🟢 |
| [`stock.search`](#stocksearch) | Searches stock-photo sites (Pexels/Pixabay) for pictures matching a query. | 🟢 |
| [`stock.download`](#stockdownload) | Downloads a chosen stock photo into your library so later steps can use it. | 🟢 |

### Publishing

| Op | What it does | Status |
|----|--------------|--------|
| [`publish.linkedin`](#publishlinkedin) | Posts text (and optionally an image) to LinkedIn and returns the post link. | 🟢 |

### Delivery / notify

| Op | What it does | Status |
|----|--------------|--------|
| [`notify.image`](#notifyimage) | Sends an image to your phone chat so you can look at it, then passes it along unchanged. | 🟢 |
| [`notify`](#notify) | Sends the previous step's result (image/video/text) to a chat without pausing, just a heads-up. | 🟢 |

## Reference

### Sources

#### `source.file` 🟢

Grabs a file that already exists (e.g. the latest image ComfyUI made) and hands it to the next step.

*Technical:* Bring an existing file from a store into the pipeline as a ref.

- **Default step id:** `source`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `store` | string | no | `comfyui` | logical store to read from |
| `name` | string | no |  | exact filename; omit to auto-pick from the store |
| `pick` | enum | no | `latest` | which file to pick when 'name' is omitted (by mtime) (one of: latest, oldest) |

### Image generation

#### `image.generate` 🟢

Makes a brand-new picture from a text description.

*Technical:* Generate an image from a prompt via ComfyUI (9 selectable flows).

- **Default step id:** `image`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | prompt text; falls back to the stdin value if omitted |
| `flow` | enum | no | `photo` | model/flow preset (local diffusion or external API) (one of: sd15, photo, concept, epic, flux, nanban, nanban-pro, flux-ultra) |
| `format` | string | no |  | portrait|landscape|square or WIDTHxHEIGHT |
| `batch_size` | int | no |  | number of images to generate |
| `testrun` | bool | no |  | set '1' for a fast low-quality test run |

#### `image.upscale` 🟢

Enlarges a picture and sharpens it, without making it blurry.

*Technical:* Upscale an image (hybrid SDXL-Tile + UltraSharp).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `factor` | int | no | `2` | scale factor 1.5–4.0 |
| `prompt` | string | no |  | optional guidance prompt |
| `denoise` | string | no |  | refinement denoise 0.05–0.5 (default 0.2) |
| `seed` | int | no |  |  |

#### `image.expand` 🟢

Extends a picture beyond its edges, inventing more scenery around it (outpainting).

*Technical:* Outpaint / expand an image to a larger canvas (FLUX).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | what to paint into the new area |
| `target_size` | int | no | `1920` | target long edge in px |
| `feathering` | string | no |  | edge blend amount |
| `seed` | int | no |  |  |

#### `image.edit` 🟢

Changes a picture you already have — e.g. put a blue hat on the rabbit — instead of drawing a new one.

*Technical:* Edit an existing image from a prompt (Gemini image models).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | yes |  | what to change about the incoming image, e.g. 'add a blue hat' |
| `flow` | enum | no | `nanban` | editing model (external API) (one of: nanban, nanban-pro) |
| `format` | string | no |  | portrait|landscape|square — omit to keep the source shape |
| `temperature` | string | no |  | how freely the model reinterprets, 0.0-2.0 |

#### `image.cutout` 🟢

Frees the main subject from its background and hands on a picture with a see-through background.

*Technical:* Cut the subject out of an image and return a PNG with an alpha channel.

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | enum | no | `isnet` | matting model; 'human' for people, 'inspyrenet' is finer on hair and fur but slower (one of: isnet, u2net, human, anime, silueta, inspyrenet) |
| `device` | enum | no | `CUDA` | where the matting model runs; ignored by inspyrenet (one of: CUDA, CPU) |

#### `image.erase` 🟢

Takes the main subject out of a picture and paints the background back in where it stood.

*Technical:* Remove the subject from an image and fill the gap with the surrounding scene (Flux Fill).

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | what the emptied area should show; omit for a plain continuation of the scene |
| `model` | enum | no | `isnet` | which model decides where the subject is (one of: isnet, u2net, human, anime, silueta) |
| `grow` | int | no | `90` | how many pixels the hole is widened. Not cosmetic: at a small value the subject's silhouette stays readable, and a fill model reads a subject-shaped hole as an invitation to paint one |
| `seed` | int | no |  | fix the noise to repeat the same fill |
| `steps` | int | no |  | sampling steps; more is slower and slightly cleaner |

#### `image.facefix` 🟢

Sharpens the faces in a picture — useful when people stand far enough away that their features came out mushy.

*Technical:* Re-render the faces in an image at higher detail, leaving the rest untouched.

- **Default step id:** `image`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | what the refined face should look like; omit for a plain detail pass |
| `denoise` | string | no | `0.4` | how far the face may change, 0.1-0.6; past roughly 0.6 it stops being the same person |
| `seed` | int | no |  | fix the noise to repeat the same pass |
| `steps` | int | no |  | sampling steps for the face crop |

### Video

#### `video.generate` 🟢

Turns a prompt (or a still image) into a short moving video clip.

*Technical:* Generate video via WAN 2.2 — text-to-video, image-to-video, or start+end frames.

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

#### `video.last_frame` 🟢

Grabs the final still frame of a video, handy to keep a scene going into the next clip.

*Technical:* Extract the last frame of a video as an image ref — chains i2v videos (each new video starts from the previous one's final frame).

- **Default step id:** `video`  
- **Consumes (stdin):** one (video)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `position` | enum | no | `last` | which frame to grab (one of: last, first) |

### 3D text (Blender / PixelText)

#### `pixeltext.render` 🟢

Renders your word(s) as chunky 3D pixel-cube typography, as a short animated video.

*Technical:* Render a 3D pixel-cube text/word animation via the Blender PixelText worker (GPU). Text on stdin or ?text=. Returns an MP4 (or PNG) asset ref.

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

### Media finishing

#### `clip.generate` 🟢

Stitches several videos together into one clip, optionally laying a music track over it.

*Technical:* Assemble one or more image/video refs into a single MP4 (Ken-Burns).

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

#### `text.overlay` 🟢

Writes text onto a colored background as a simple image card.

*Technical:* Render multi-line text onto a flat-color background as a PNG.

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

#### `gif.create` 🟢

Turns several images into one looping animated GIF.

*Technical:* Animate multiple images into an animated GIF.

- **Default step id:** `gif`  
- **Consumes (stdin):** many (image)  
- **Emits (stdout):** video

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `durations` | string | no | `1` | per-frame seconds (single or comma list) |
| `quality` | enum | no | `medium` |  (one of: low, medium, high, ultra) |
| `size` | string | no |  | output WxH or width-only |

### Audio

#### `tts.speak` 🟢

Reads text out loud and saves it as an audio file (text-to-speech).

*Technical:* Synthesize speech audio from text (piper/kokoro/chatterbox).

- **Default step id:** `tts`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** audio

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | text to speak; falls back to stdin |
| `language` | string | no | `en` | e.g. en, de |
| `voice` | enum | no | `` | named voice (en=kokoro af_*/am_*, de=piper thorsten/kerstin); empty = auto by language (one of: , af_bella, af_nova, am_adam, am_michael, thorsten, thorsten_emotional, kerstin) |
| `format` | enum | no | `wav` |  (one of: wav, mp3) |
| `engine` | enum | no | `auto` |  (one of: auto, piper, kokoro, chatterbox) |
| `speed` | string | no |  | rate multiplier (default 1.0) |

#### `music.generate` 🟢

Composes an original piece of music from a description (mood, tempo, optional lyrics).

*Technical:* Generate music/song audio from style tags + optional lyrics via ComfyUI ACE-Step 1.5 (local).

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

### Local LLM

#### `llm.image_prompt` 🟢

Takes a short idea and expands it into a rich, detailed prompt for image generation.

*Technical:* Expand a short subject into one rich text-to-image prompt (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subject` | string | no |  | the subject; falls back to the stdin value if omitted |

#### `llm.complete` 🟢

Asks the local AI to write or answer something freely.

*Technical:* Free-form text completion (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | no |  | user prompt; falls back to stdin |
| `system` | string | no |  | system prompt |
| `temperature` | string | no |  | sampling temperature (default 0.7) |
| `max_tokens` | int | no |  | optional ceiling; empty = the model stops when the answer ends |

#### `llm.summarize` 🟢

Shortens a long text down to its key points.

*Technical:* Summarize the input text (local qwen, thin wrapper over llm.complete).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `max_tokens` | int | no |  | summary length budget |

#### `llm.classify` 🟢

Sorts a text into one of a set of labels you provide.

*Technical:* Classify the input text into one of the given labels (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `labels` | string | yes |  | comma-separated candidate labels |

#### `llm.extract` 🟢

Pulls specific facts (e.g. name, date, price) out of a text.

*Technical:* Extract structured fields from the input text as JSON (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `fields` | string | yes |  | comma-separated fields to extract |

#### `llm.translate` 🟢

Translates text into another language.

*Technical:* Translate the input text to a target language (local qwen).

- **Default step id:** `llm`  
- **Consumes (stdin):** one (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `to` | string | yes |  | target language, e.g. de, en |
| `from` | string | no |  | source language; auto-detect if omitted |

#### `llm.switch` 🟢

Swaps which local AI model is running (a bigger or smaller brain), then continues the chain.

*Technical:* Switch the active local LLM (llama.cpp profile), like the Pilot model switcher. Takes ~10-20s; the swap is global and persistent across the whole box. Passes stdin through unchanged.

- **Default step id:** `llm`  
- **Consumes (stdin):** one (optional) (any)  
- **Emits (stdout):** any

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `profile` | enum | yes |  | target llama.cpp profile to load (one of: qwen3-14b, qwen3-8b, qwen25-7b, qwen25-coder, nous-hermes, magistral) |

### Cloud LLM

#### `cloud.complete` 🟢

Asks a cloud AI (Claude) to write or answer something, for the few tasks the local model can't handle.

*Technical:* Text completion via Claude (cloud; peripheral content tasks only).

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

#### `cloud.vision` 🟢

Shows a cloud AI (Claude) an image and asks it to describe or analyze it.

*Technical:* Describe / analyze an image with an optional question (Claude vision).

- **Default step id:** `cloud`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | what to ask about the image |
| `model` | enum | no | `haiku` |  (one of: haiku, sonnet, opus) |
| `max_tokens` | int | no |  | optional ceiling; empty = 1024 (cloud answers cost money) |

### Data (tables)

#### `db.query` 🟢

Looks up rows in a table that match a filter.

*Technical:* Query rows from a table with filter/order/pagination.

- **Default step id:** `db`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  | table name or numeric id |
| `filter` | string | no |  | filter expression / JSON |
| `order_by` | string | no |  | e.g. -created_at |
| `size` | int | no | `50` | rows per page (max 200) |

#### `db.get` 🟢

Fetches one specific row from a table by its id.

*Technical:* Fetch a single row by id.

- **Default step id:** `db`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |

#### `db.insert` 🟢

Adds a new row to a table.

*Technical:* Create a new row (field values from stdin JSON or 'data').

- **Default step id:** `db`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `data` | string | no |  | JSON field values; falls back to stdin |

#### `db.update` 🟢

Changes fields on an existing row.

*Technical:* Patch an existing row by id (partial update).

- **Default step id:** `db`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |
| `data` | string | no |  | JSON field values; falls back to stdin |

#### `db.delete` 🟢

Removes a row from a table.

*Technical:* Delete a row by id.

- **Default step id:** `db`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |
| `row_id` | int | yes |  |  |

#### `db.list_fields` 🟢

Lists the columns (fields) a table has.

*Technical:* Get the field schema for a table.

- **Default step id:** `db`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `table` | string | yes |  |  |

### Web & stock

#### `web.search` 🟢

Searches the web (via your local SearXNG) and returns the hits.

*Technical:* Search the web via local SearXNG.

- **Default step id:** `web`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | search query; falls back to stdin |
| `categories` | string | no | `general` | SearXNG category |

#### `web.fetch` 🟢

Downloads a web page and strips it down to plain readable text.

*Technical:* Fetch a web page and return its text (cut at max_chars, and the cut is reported in the run log).

- **Default step id:** `web`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | no |  | page URL; falls back to stdin |
| `max_chars` | int | no | `20000` | length ceiling; a cut page reports its true length |

#### `stock.search` 🟢

Searches stock-photo sites (Pexels/Pixabay) for pictures matching a query.

*Technical:* Search stock photos (Pexels / Pixabay).

- **Default step id:** `stock`  
- **Consumes (stdin):** one (optional) (text)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no |  | search term; falls back to stdin |
| `source` | enum | no | `pexels` |  (one of: pexels, pixabay) |
| `count` | int | no | `5` |  |
| `orientation` | enum | no | `landscape` |  (one of: landscape, portrait, square) |

#### `stock.download` 🟢

Downloads a chosen stock photo into your library so later steps can use it.

*Technical:* Download a stock photo into a store as an image ref. Takes no stdin: source and image_url are picked out of a stock.search result by a field-pick step, not by this op.

- **Default step id:** `stock`  
- **Consumes (stdin):** none (any)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | enum | yes |  |  (one of: pexels, pixabay) |
| `image_url` | string | yes |  | full image URL |
| `image_id` | string | no |  | stock API image id |

### Publishing

#### `publish.linkedin` 🟢

Posts text (and optionally an image) to LinkedIn and returns the post link.

*Technical:* Publish an image or text post to LinkedIn (UGC API). Stdin takes either an image ref or the post text (optional — omit both and pass ?text=). Returns the post URL.

- **Default step id:** `publish`  
- **Consumes (stdin):** one (optional) (any)  
- **Emits (stdout):** text

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | no |  | post caption/body text (often a {"from": <llm step>} ref) |
| `author` | string | no |  | author URN urn:li:person:…; falls back to env MORA02_LINKEDIN_AUTHOR |
| `visibility` | enum | no | `PUBLIC` | post visibility (one of: PUBLIC, CONNECTIONS) |

### Delivery / notify

#### `notify.image` 🟢

Sends an image to your phone chat so you can look at it, then passes it along unchanged.

*Technical:* (superseded by 'notify') Send an image ref to a chat for review, pass it through.

- **Default step id:** `notify`  
- **Consumes (stdin):** one (image)  
- **Emits (stdout):** image

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `target` | string | no |  | E.164 recipient; falls back to env MORA02_SIGNAL_TARGET |
| `channel` | string | no | `signal` | notify channel |
| `message` | string | no |  | optional caption sent with the image |

#### `notify` 🟢

Sends the previous step's result (image/video/text) to a chat without pausing, just a heads-up.

*Technical:* Send the previous step's output (type-aware) to a channel, no pause; pass it through.

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

