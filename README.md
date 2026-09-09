# mora02

A locally-hosted creative AI factory I run on a single workstation. Twenty-eight Docker services stitched together with a decreasing amount of duct tape.

## What is this

mora02 is a one-machine pipeline for creative work:

- Chat with a **Pilot bot** that routes prompts to the right model (local Qwen or Claude in the cloud), remembers context across sessions and hosts the tools below in one UI
- Generate images, video and music via **ComfyUI** workflows
- Render animated GIFs, video clips and text-on-image frames through custom scripts (**Script-Runner**)
- Chain all of that into **pipelines** — a vocabulary of 39 steps (generate, upscale, clip, classify, publish, …) that compile to runs with human-in-the-loop gates: the pipeline pauses, a preview lands on my phone via **Signal**, I approve or reject, it continues
- Let small **local agents** do the chores: draft a pipeline from a conversation, run one, write a briefing, research a topic — all on the local model, never the cloud
- Search the web locally via **SearXNG** instead of going through a cloud search API
- Store state in **Baserow** as a CMS — posts, personas, sessions, known issues, cost tracking
- Publish finished posts to **LinkedIn** on a schedule
- Use **Penpot** + **Excalidraw** for design work, all on the same machine

The whole thing comes up with `docker compose --profile <llm> up -d`. There are no cloud services in the loop except the Anthropic API and Google's Gemini image models, both used only when actively selected — and never for anything that steers the system itself.

## Why does this exist

My long term goal is to create a machine or a chain of machines (call it a factory) that supports creative work in a good way. What "in a good way" exactly means is to be explored. I want an environment that is open, that doesn't leak data to ten different cloud providers, doesn't get arbitrarily expensive when experimenting, and stays available even when half the internet is down. Building it has also been the most fun side project I've worked on in years.

## What's inside

| Service | What it does | Port |
|---|---|---|
| `pilot` | Chat orchestrator + UI (FastAPI + vanilla JS); also serves the flow builder, run view and agent console | 8098 |
| `script-runner` | Media pipelines (Gifer, Clipper, Typer), stock photo proxy, and the executor for pipeline steps | 8096 |
| `llama-server` | Local LLM via llama.cpp, one of eight profiles at a time | 8080 |
| `comfyui` | Image, video and music generation | 8188 |
| `mora02-openclaw` | Gateway for the local agents and the pipeline runner (Lobster) | — |
| `mora02-signal-cli` | The Signal channel for approvals and previews | 8099 |
| `baserow` | Database / CMS | 8085 |
| `nginx-images` | Serves generated assets and the wiki | 8092 |
| `searxng` | Metasearch | 8094 |
| `piper-tts`, `kokoro-tts`, `chatterbox-tts` | Speech: German, English, voice cloning | — |
| `blender-worker` | Blender-rendered text-in-3D (PixelText) | 8097 |
| `penpot` (3 containers) | Vector design tool | 8101 |
| `excalidraw` (2 containers) | Whiteboard / sketch tool | 8102 |
| `postgres` ×2, `redis` | Backing services | — |

All on one Docker bridge network (`mora02-net`), data in host-mounted volumes for persistence and easy backup. Only Pilot, Baserow and the asset server are reachable from the LAN; everything else binds to `127.0.0.1`.

Shared logic lives in one Python library, `lib/mora02_core` — Baserow access, LLM clients, ComfyUI workflow building, the pipeline vocabulary and runner, notifications, publishing. The apps consume it; nothing is implemented twice.

### Interfaces

Pilot and Script-Runner are FastAPI services, so each documents its own HTTP API: `http://mora02.local:8098/docs` and `http://localhost:8096/docs` (OpenAPI, generated from the code). Pipelines are JSON specs under `pipelines/specs/`; the step vocabulary that a spec may use is listed at `GET /pipeline/vocab-stats` on the Script-Runner and rendered in the Pilot UI.

## Tech stack

- **Backend:** Python 3.11, FastAPI, httpx, pydantic
- **Frontend:** Vanilla HTML/CSS/JS — no framework, no build step, no `npm install` purgatory
- **LLMs:** local Qwen / Mistral / Magistral via llama.cpp + Anthropic Claude API for edge cases
- **Agents / runner:** OpenClaw gateway with Lobster as the deterministic pipeline runner
- **Infra:** Docker Compose, NVIDIA CUDA runtime, PostgreSQL 15, Redis 7

## Models in use

None of these are in the repo (weights are huge, license-bound, or both). They live under `/opt/mora02/ai-models/` on my host. Listed here so you know what to bring if you fork.

**Local LLMs (llama.cpp, switchable profiles):**
- Qwen3.6-27B (UD-IQ3_XXS) — the base model since the last benchmark round
- Qwen3-14B and Qwen3-8B (Q4_K_M) — the previous defaults, kept for comparison
- Qwen2.5-7B-Instruct, Qwen2.5-Coder-14B-Instruct (Q4_K_M)
- Nous-Hermes-2-Mistral-7B (Q4_K_M) — alternative voice
- Magistral-Small-24B (Q4_K_M) — slow but good at hard reasoning
- Muse-Glimmer-30B (UD-Q3_K_XL) — creative writing, too slow for daily use

**Cloud (only when selected):**
- Claude Haiku 4.5 — cheap default for the Pilot
- Claude Sonnet 4.5 — vision, longer chains
- Claude Opus 4.6 — the heavy stuff
- Gemini 2.5 Flash Image / Gemini 3 Pro Image — image editing with reference images ("nano banana")

**Image / Video / Music (ComfyUI):**
- Image: **Flux.1** (schnell, fill), SDXL checkpoints (**DreamShaperXL**, **Juggernaut XL**, **epiCRealism XL**) with add-detail-xl and IP-Adapter Plus
- Video: **Wan 2.2** I2V and T2V 14B (fp8) with lightx2v 4-step LoRAs, **AnimateDiff**
- Music: **ACE-Step 1.5**
- Auxiliary: CLIP ViT-H/14, umt5-xxl text encoder, 4x-UltraSharp upscaler

**Speech & Audio:**
- **Piper** (German TTS, local)
- **Kokoro** (English TTS, local)
- **Chatterbox** (voice cloning, local) — custom voices live in `volumes/chatterbox/voices/`

## How it is kept in shape

- Every third-party image is pinned to a version; `scripts/docker/image-check.py` asks the registries what is newer and names the build that is actually running
- A three-stage pre-commit hook: gitleaks (no secrets), a boundary guard (no host-specific artefacts in this public repo), ruff (no broken Python)
- 34 test suites under `tests/` and `lib/mora02_core/tests/`, each directory with a `run-all.sh` that says which suites need the running stack
- Pipeline runs write an execution log (inputs, outputs with hashes, gate decisions, who triggered it) that the run view and the archive read
- Backups: hourly Borg to a NAS, restore rehearsed

## Hardware this assumes

- AMD Ryzen 9 7950X
- NVIDIA RTX 5090, 32 GB VRAM
- 64 GB system RAM
- Ubuntu 24.04
- Hostname `mora02.local` resolving to the host on the LAN

Won't run unmodified on anything significantly smaller, especially without a CUDA-capable GPU.

## Can you run it?

Honestly, probably not without surgery. This is my personal lab, not a deployable product. The Compose file has paths hardcoded under `/opt/mora02/`, several services assume the `mora02.local` hostname, and the LLM profiles expect specific model files in place. `docker/.env.example` lists every variable the stack reads.

## Status

Actively maintained, single-author, evenings and weekends. The big refactors are done: shared logic in `mora02_core`, a native pipeline layer with gates instead of external workflow tools, agents on the local model, the stack trimmed from forty services to twenty-eight with every image pinned. Next up: a review pass over Pilot, then authentication in front of it.

Questions, ideas and bug reports: see [CONTRIBUTING.md](CONTRIBUTING.md). Security findings: see [SECURITY.md](SECURITY.md).

## License

No formal license yet. Code is here to read and learn from. If you want to lift a specific piece, drop me a line or fork freely for personal use.
