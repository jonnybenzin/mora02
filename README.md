# Mora02

A locally-hosted creative AI factory I run on a single workstation. Around 26 Docker containers stitched together with a fair amount of duct tape.

## What is this

Mora02 is my one-machine pipeline for creative work:

- Chat with a **Pilot bot** that routes prompts to the right model (local Qwen or Claude in the cloud) and remembers context across sessions
- Generate images and short videos via **ComfyUI** workflows
- Render animated GIFs, video clips, and text-on-image frames through custom scripts (**Script-Runner**)
- Search the web locally via **SearXNG** instead of going through a cloud search API
- Store everything in **Baserow** as a CMS — posts, personas, sessions, known issues, cost tracking
- Run multi-agent workflows in **Dify** when chains get too gnarly for the Pilot
- Use **Penpot** + **ExcaliDraw** for design work, all on the same machine

The whole thing comes up with `docker compose up -d`. There's no SaaS in the loop except for the Anthropic API (and even that's behind a router that prefers local Qwen first).

## Why does this exist

I wanted a creative environment that doesn't leak my data to ten different cloud providers, doesn't get arbitrarily expensive when I'm experimenting, and stays available even when half the internet is down. Building it has also been the most fun side project I've worked on in years.

## What's inside the box

| Service | What it does | Port |
|---|---|---|
| `pilot` | Chat orchestrator + UI (FastAPI + vanilla JS) | 8098 |
| `script-runner` | Media pipelines (Gifer, Clipper, Typer) | 8096 |
| `knowledge-api` | Knowledge sync, Claude Vision, TTS, web search proxy | 8095 |
| `llama-server` | Local LLM (Qwen profiles, switchable) | 8080 |
| `comfyui` | Image/video generation | 8188 |
| `dify-api` | Multi-agent workflow platform | 8190 |
| `baserow` | Database / CMS | 8085 |
| `activepieces` | Workflow automation (being phased out) | 8089 |
| `searxng` | Metasearch | 8094 |
| `penpot` | Vector design tool | 8101 |
| `excalidraw` | Whiteboard / sketch tool | 8102 |
| `postgres`, `redis`, `weaviate`, `ollama` | Backing services | — |

All on a Docker bridge network (`mora02-net`), data in host-mounted volumes for persistence and easy backup.

## Tech stack

- **Backend:** Python 3.11/3.12, FastAPI, Flask, Gunicorn
- **Frontend:** Vanilla HTML/CSS/JS — no framework, no build step, no `npm install` purgatory
- **LLMs:** local Qwen / Mistral / Magistral via llama.cpp + Anthropic Claude API for edge cases 
- **Infra:** Docker Compose, NVIDIA CUDA runtime, PostgreSQL 15, Redis 7, Weaviate 1.19

## Models in use

None of these are in the repo (weights are huge, license-bound, or both). They live in `/opt/mora02/ai-models/` and `docker/ComfyUI/models/` on my host. Listed here so you know what to bring if you fork.

**Local LLMs (llama.cpp, switchable profiles):**
- Qwen3-14B (Q4_K_M) — main reasoning model
- Qwen3-8B (Q4_K_M) — faster default
- Qwen2.5-7B-Instruct (Q4_K_M)
- Qwen2.5-Coder-14B-Instruct (Q4_K_M) — for code tasks
- Nous-Hermes-2-Mistral-7B (Q4_K_M) — alternative voice
- Magistral-Small-24B (Q4_K_M) — slow but excellent for hard reasoning

**Cloud LLMs (Anthropic API):**
- Claude Haiku 4.5 — cheap default for the Pilot
- Claude Sonnet 4.5 — vision, longer chains
- Claude Opus 4.6 — the heavy stuff

**Image / Video (ComfyUI):**
- Checkpoints: **DreamShaperXL 1.0**, **Juggernaut-XL v9**, **SD 1.5** (baseline)
- Video: **Wan2.1 I2V 14B** (480p + 720p), **AnimateDiff** (mm_sd_v14)
- LoRAs: lightx2v T2V/I2V step-distilled, add-detail-xl, IP-Adapter FaceID Plus v2
- Auxiliary: **CLIP ViT-H/14** (LAION-2B), **umt5-xxl** text encoder, **4x-UltraSharp** upscaler
- Detection: **YOLOv8m** (face), **SAM ViT-B** (segmentation)

**Speech & Audio:**
- **Piper** (German TTS, local)
- **Kokoro** (English TTS, local)
- **Chatterbox** (voice cloning, local) — custom voices live in `volumes/chatterbox/voices/`

**Embeddings:**
- Ollama is in the stack as embedding provider for Weaviate / Dify, but I haven't pinned a specific model yet — pull whichever embedder you prefer (`nomic-embed-text`, `mxbai-embed-large`, etc.)

## Hardware this assumes

- AMD Ryzen 9 7950X
- NVIDIA RTX 5090, 32 GB VRAM
- 64 GB system RAM
- Ubuntu 24.04
- Hostname `mora02.local` resolving to the host on the LAN

Won't run unmodified on anything significantly smaller, especially without a CUDA-capable GPU.

## Can you run it?

Honestly, probably not without surgery. This is my personal lab, not a deployable product. The Compose file has paths hardcoded under `/opt/mora02/`, several services assume the `mora02.local` hostname, and the LLM profiles expect specific Qwen model files in place.

If you want to fork and adapt, start with `docker/.env.example` and `docker/docker-compose.yml`. The architecture notes and build commands are in [`CLAUDE.md`](CLAUDE.md).

## Status

Phase 0 of a longer refactor just shipped (this commit) — secrets out of code, env-driven config, history rewritten. Next up: extracting shared logic into a `mora02_core` Python library so the apps stop duplicating Baserow / LLM / ComfyUI clients. Single-author, evenings and weekends.

## License

No formal license yet. Code is here to read and learn from. If you want to lift a specific piece, drop me a line or fork freely for personal use.
