import uuid, json, os
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import List
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from config import settings, MODELS, DEFAULT_SYSTEM_PROMPT, get_local_profile_label
from router import classify_input
from session_manager import store
from mora02_core.llm import stream_llm
from bot_bridge import call_runner, call_script_runner, call_comfyui, call_search, call_pixeltext
from mora02_core.baserow import api as baserow_api
from mora02_core.baserow import (
    write_session, read_last_sessions, read_all_sessions,
    read_context, read_known_issues, headers as _baserow_headers,
    format_sessions_context, format_known_issues, format_context_table,
    read_personas, create_persona_row, increment_persona_usage, update_persona,
    write_feedback, list_feedback, update_feedback,
    save_bucket, list_buckets, delete_bucket,
    save_style_pack, list_style_packs, get_style_pack,
    update_style_pack, delete_style_pack,
    list_posts, create_post, update_post,
)

# Backward-compat alias: app.py has ~9 spots doing direct httpx calls with
# BASEROW_HEADERS. Phase 1.x future cleanup will migrate them to api.update/
# api.query/etc. For now, evaluate once at startup like the old client did.
BASEROW_HEADERS = _baserow_headers()


async def _check_schema_drift() -> None:
    """Boot-check: every MODELS entry needs a `cost_<key>` column in bot_costs.

    Missing columns get reported as `bot_feedback` rows the user sees via
    `/feedback`, with step-by-step instructions. Existing reminders for
    columns that have since been added are auto-resolved.
    """
    try:
        live_fields = await baserow_api.list_fields("bot_costs")
    except Exception as e:
        print(f"[schema-drift] skipped (Baserow unreachable): {e}")
        return
    live_names = {f["name"] for f in live_fields}

    expected = {f"cost_{k}": k for k in MODELS.keys()}
    missing = {col: k for col, k in expected.items() if col not in live_names}

    try:
        existing = await baserow_api.query(
            "bot_feedback",
            filter={"Type": "missing-schema-column", "Status": "new"},
            all_pages=True,
        )
    except Exception as e:
        print(f"[schema-drift] couldn't list existing feedback: {e}")
        existing = []

    existing_by_col: dict[str, int] = {}
    for row in existing:
        desc = row.get("Description") or ""
        for col in expected.keys():
            if col in desc:
                existing_by_col[col] = row["id"]
                break

    for col, model_key in missing.items():
        if col in existing_by_col:
            continue
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        desc = (
            f"Baserow Table 574 (bot_costs) fehlt Spalte {col}.\n"
            f"Das Modell '{model_key}' wurde in lib/.../llm/models.py "
            f"eingetragen, aber die Kosten-Spalte in Baserow existiert nicht.\n"
            f"\n"
            f"→ Was tun:\n"
            f"  1. http://mora02.local:8085/database/113/table/574 öffnen\n"
            f"  2. '+' am rechten Tabellen-Rand → 'Number'-Feld anlegen\n"
            f"  3. Name: {col}\n"
            f"  4. Dezimalstellen: 6\n"
            f"  5. Speichern\n"
            f"\n"
            f"Sobald die Spalte existiert, verschwindet diese Meldung beim\n"
            f"nächsten Pilot-Boot automatisch."
        )
        await baserow_api.insert("bot_feedback", {
            "Name": f"[schema] {col} missing — {ts}",
            "Type": "missing-schema-column",
            "Severity": "medium",
            "Description": desc,
            "Page": "boot-check",
            "Status": "new",
        })
        print(f"[schema-drift] reminder created: {col}")

    for col, row_id in existing_by_col.items():
        if col not in missing:
            await baserow_api.update("bot_feedback", row_id, {"Status": "resolved"})
            print(f"[schema-drift] auto-resolved: {col}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await _check_schema_drift()
    yield


app = FastAPI(title="Pilot Bot", version="0.1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

session_settings: dict[str, dict] = {}
session_personas: dict[str, dict] = {}

DEFAULT_SETTINGS = {
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.7,
    "max_tokens": 4096,
}

END_SESSION_PROMPT = """Analyze this conversation and produce a JSON summary. Respond ONLY with valid JSON, no markdown fences, no preamble.

{
  "goal": "One sentence: what was the user trying to accomplish",
  "summary": "2-3 sentences summarizing what happened",
  "decisions": "Key decisions made (or 'none')",
  "open_items": "Unresolved items or next steps (or 'none')"
}"""


def get_session_settings(sid: str) -> dict:
    return {**DEFAULT_SETTINGS, **session_settings.get(sid, {})}


def get_system_prompt(session_id: str, model_key: str) -> str:
    s = get_session_settings(session_id)
    base = s["system_prompt"]
    model = MODELS[model_key]
    # For local LLMs the routing key is fixed but the actual loaded model
    # rotates via the profile switcher — read the real name from
    # /llm-switch/current.json so the identity block doesn't lie.
    if model["type"] == "openai_compatible":
        identity_name = get_local_profile_label()
    else:
        identity_name = model["name"]
    identity = f"\n\n## Your Identity\nYou are currently running as: {identity_name} ({model['icon']})\nModel key: {model_key}\nWhen asked which model you are, state this clearly."

    # Persona injection
    persona = session_personas.get(session_id)
    if persona and persona.get("prompt"):
        persona_block = (
            f"\n\n---\n"
            f"## Active Persona: {persona['icon']} {persona['name']}\n\n"
            f"{persona['prompt']}"
        )
    else:
        persona_block = ""

    return base + identity + persona_block


async def get_cost_summary() -> str:
    """Read costs from bot_costs table + calculate current week from bot_sessions."""
    import httpx as _httpx
    from datetime import timedelta
    from config import settings

    # Monthly data from bot_costs
    async with _httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true&size=100",
            headers=BASEROW_HEADERS)
        months = resp.json().get("results", []) if resp.status_code == 200 else []

    # Current week from bot_sessions (Monday 00:00)
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    current_month = now.strftime("%Y-%m")

    sessions = await read_all_sessions()
    week_cost = 0.0
    week_sessions = 0
    week_models: dict[str, float] = {}
    for s in sessions:
        ended = s.get("ended_at") or ""
        if not ended:
            continue
        try:
            ts = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            if ts >= monday:
                cost = float(s.get("cost_usd") or 0)
                model = s.get("model_used") or "qwen"
                week_cost += cost
                week_sessions += 1
                week_models[model] = week_models.get(model, 0) + cost
        except (ValueError, TypeError):
            pass

    # Build output
    out = "## API Costs\n\n"

    # This week
    out += f"### This Week (since Monday {monday.strftime('%Y-%m-%d')})\n"
    out += f"Sessions: {week_sessions} · Cost: **${week_cost:.4f}**\n"
    if week_models:
        for m, c in sorted(week_models.items(), key=lambda x: -x[1]):
            out += f"  - {m}: ${c:.4f}\n"
    out += "\n"

    # Monthly breakdown
    out += "### Monthly\n| Month | Sessions | Qwen | Haiku | Sonnet | Opus | NanBan | Total |\n"
    out += "|-------|----------|------|-------|--------|------|--------|-------|\n"
    for row in sorted([r for r in months if r.get("month")], key=lambda r: r.get("month", ""), reverse=True)[:6]:
        m = row.get("month", "?")
        s = int(float(row.get("sessions_total") or 0))
        q = float(row.get("cost_qwen") or 0)
        h = float(row.get("cost_haiku") or 0)
        sn = float(row.get("cost_sonnet") or 0)
        o = float(row.get("cost_opus") or 0)
        nb = float(row.get("cost_nanban") or 0)
        t = float(row.get("cost_total") or 0)
        bold = "**" if m == current_month else ""
        out += f"| {bold}{m}{bold} | {s} | ${q:.2f} | ${h:.2f} | ${sn:.2f} | ${o:.2f} | ${nb:.2f} | {bold}${t:.2f}{bold} |\n"

    total_all = sum(float(r.get("cost_total") or 0) for r in months if r.get("month"))
    out += f"\n**All time total: ${total_all:.2f}**"
    return out


async def handle_ctx(session, subcommand: str) -> str:
    """Handle /ctx commands. Returns context text to inject into conversation."""
    sub = subcommand.strip().lower()

    if sub in ("", "help"):
        return """Available context commands:
- `/ctx system` — Full system status (GPU, VRAM, ports, containers, backup, LLM)
- `/ctx issues` — Known issues & solutions from Baserow
- `/ctx sessions` — Last 3 session summaries
- `/ctx costs` — API costs this week/month
- `/ctx all` — Load everything (except costs)

Run `pilot-sync.sh` on host to refresh system data."""

    parts = []

    if sub in ("system", "ports", "all"):
        sys_info = await read_context("system_info")
        if sys_info:
            parts.append(sys_info)
        else:
            parts.append("⚠ No system data. Run `bash /opt/mora02/scripts/pilot-sync.sh` on host first.")

    if sub in ("issues", "all"):
        issues = await read_known_issues()
        parts.append(format_known_issues(issues))

    if sub in ("sessions", "all"):
        sessions = await read_last_sessions(3)
        parts.append(format_sessions_context(sessions))

    if sub in ("costs", ):
        costs = await get_cost_summary()
        parts.append(costs)

    if not parts:
        return f"Unknown context: '{sub}'. Try /ctx help"

    context_text = "\n\n---\n\n".join(parts)

    # Inject into session history as system knowledge
    session.add_assistant_message(f"[Context loaded: {sub}]\n\n{context_text}", model="context")

    return f"✅ Context loaded: **{sub}** ({len(context_text)} chars)\n\n{context_text}"


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pilot", "port": settings.port}


# ── File deletion ────────────────────────────────────────────────
FILE_PATH_MAP = {
    "/comfyui/wip/": "/output/comfyui-wip/",
    "/tool-assets/gifer/": "/output/gifer/",
    "/tool-assets/clipper/": "/output/clipper/",
    "/tool-assets/typer/": "/output/typer/",
    "/tool-assets/tts/": "/output/tts/",
}

@app.delete("/api/files/delete")
async def delete_file(request: Request):
    """Delete a generated asset from the filesystem."""
    import shutil
    body = await request.json()
    url = body.get("url", "")

    # Extract path portion from the full URL (strip http://host:port)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    url_path = parsed.path  # e.g. /comfyui/wip/image.png

    # Map URL path to container filesystem path
    local_path = None
    for prefix, mount in FILE_PATH_MAP.items():
        if url_path.startswith(prefix):
            relative = url_path[len(prefix):]
            local_path = os.path.join(mount, relative)
            break

    if not local_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Unknown file location"})

    # Resolve and validate against path traversal
    resolved = Path(local_path).resolve()
    allowed = [Path(m).resolve() for m in FILE_PATH_MAP.values()]
    if not any(str(resolved).startswith(str(a)) for a in allowed):
        return JSONResponse(status_code=403, content={"success": False, "error": "Access denied"})

    if not resolved.exists():
        return JSONResponse(status_code=404, content={"success": False, "error": "File not found"})

    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return JSONResponse(content={"success": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/upload/post-media")
async def upload_post_media(file: UploadFile = File(...)):
    """Upload media file for social media posts."""
    import shutil
    from datetime import datetime
    try:
        ts = datetime.now().strftime("%y%m%d%H%M")
        ext = os.path.splitext(file.filename or "upload")[1] or ".jpg"
        filename = f"{ts}_post{ext}"
        dest = f"/socialmedia/{filename}"
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)
        return {"success": True, "filename": filename, "path": dest}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/upload/comfyui")
async def upload_to_comfyui(image: UploadFile = File(...)):
    """Proxy image upload to ComfyUI (avoids CORS issues from browser)."""
    import httpx
    try:
        content = await image.read()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://comfyui:8188/upload/image",
                files={"image": (image.filename, content, image.content_type)},
                data={"overwrite": "true"},
            )
            if resp.status_code == 200:
                return resp.json()
            return JSONResponse(status_code=resp.status_code,
                                content={"error": f"ComfyUI upload failed: {resp.text[:200]}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/models")
async def list_models():
    # Ordered list. Iteration order = UI dropdown order.
    return [
        {
            "key": k,
            "name": m["name"],
            "label": m["label"],
            "color": m["color"],
            "tier": m["tier"],
            "icon": m["icon"],
            "supports_vision": m["supports_vision"],
            "cost_input_per_1m": m["cost_input_per_1m"],
            "cost_output_per_1m": m["cost_output_per_1m"],
        }
        for k, m in MODELS.items()
    ]


@app.get("/posts/list")
async def list_posts():
    """Return posts from Baserow for the post picker."""
    import httpx as _httpx
    posts = []
    page = 1
    async with _httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/557/?user_field_names=true&size=50&page={page}",
                headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            for r in data.get("results", []):
                status_val = r.get("status")
                if isinstance(status_val, dict):
                    status_val = status_val.get("value", "")
                posts.append({
                    "id": r["id"],
                    "title": r.get("title") or "",
                    "caption": (r.get("caption_master") or "")[:100],
                    "status": status_val or "",
                })
            if not data.get("next"):
                break
            page += 1
    return {"posts": posts}


@app.post("/assign-image")
async def assign_image(request: Request):
    """Assign a generated image to a Baserow post: copy to socialmedia + set media_path."""
    import httpx as _httpx
    import shutil
    import os
    body = await request.json()
    post_id = body.get("post_id")
    filename = body.get("filename")

    if not post_id or not filename:
        return JSONResponse(content={"success": False, "error": "post_id and filename required"})

    # Copy image from comfyui wip to socialmedia assets
    src = f"/images/wip/{filename}"
    dst_dir = "/socialmedia/"
    dst = f"{dst_dir}{filename}"

    try:
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            return JSONResponse(content={"success": False, "error": f"Source file not found: {filename}"})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": f"Copy failed: {e}"})

    # Write only filename to media_path in Baserow
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{settings.baserow_url}/api/database/rows/table/557/{post_id}/?user_field_names=true",
                headers=BASEROW_HEADERS,
                json={"media_path": filename})
            if resp.status_code == 200:
                return JSONResponse(content={"success": True, "post_id": post_id, "filename": filename})
            return JSONResponse(content={"success": False, "error": f"Baserow {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})


@app.get("/costs/monthly")
async def monthly_costs():
    """Return current month costs per model: Baserow (historical) + RAM (active sessions)."""
    import httpx as _httpx
    from config import MODELS
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    costs = {"qwen": 0.0, "haiku": 0.0, "sonnet": 0.0, "opus": 0.0, "nanban": 0.0}

    # 1. Historical: bot_costs table (Baserow 574)
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true&size=100",
                headers=BASEROW_HEADERS)
            months = resp.json().get("results", []) if resp.status_code == 200 else []
        for row in months:
            if row.get("month") == current_month:
                for k in costs:
                    costs[k] += float(row.get(f"cost_{k}") or 0)
    except Exception:
        pass

    # 2. Active RAM sessions
    for sid, session in store.sessions.items():
        for msg in session.messages:
            if msg.model and msg.model in MODELS and msg.role == "assistant":
                m = MODELS[msg.model]
                cost = (msg.tokens_in / 1_000_000) * m["cost_input_per_1m"] + \
                       (msg.tokens_out / 1_000_000) * m["cost_output_per_1m"]
                costs[msg.model] = costs.get(msg.model, 0.0) + cost

    # 3. Ended sessions this month (bot_sessions table)
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_sessions}/?user_field_names=true&size=200&order_by=-id",
                headers=BASEROW_HEADERS)
            rows = resp.json().get("results", []) if resp.status_code == 200 else []
        for row in rows:
            ended = row.get("ended_at") or ""
            if ended[:7] == current_month:
                model = row.get("model_used", "qwen")
                cost = float(row.get("cost_usd") or 0)
                if model in costs:
                    costs[model] += cost
    except Exception:
        pass

    total = round(sum(costs.values()), 4)
    return {
        "month": current_month,
        "qwen": round(costs["qwen"], 4),
        "haiku": round(costs["haiku"], 4),
        "sonnet": round(costs["sonnet"], 4),
        "opus": round(costs["opus"], 4),
        "nanban": round(costs["nanban"], 4),
        "total": total,
    }


@app.post("/session/create")
async def create_session():
    sid = str(uuid.uuid4())[:8]
    session = store.create(sid)
    return {"session_id": sid, "model": session.current_model}


@app.post("/session/{sid}/model")
async def switch_model(sid: str, request: Request):
    body = await request.json()
    model_key = body.get("model", "qwen")
    if model_key not in MODELS:
        return JSONResponse(status_code=400, content={"error": f"Unknown model: {model_key}"})
    session = store.get_or_create(sid)
    session.current_model = model_key
    return {"session_id": sid, "model": model_key,
            "model_name": MODELS[model_key]["name"], "icon": MODELS[model_key]["icon"]}


@app.get("/session/{sid}/status")
async def session_status(sid: str):
    session = store.get(sid)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    return {"session_id": sid, "model": session.current_model,
            "message_count": len(session.messages),
            "tokens_in": session.total_tokens_in,
            "tokens_out": session.total_tokens_out,
            "cost_usd": session.get_total_cost()}


@app.get("/session/{sid}/system-prompt")
async def get_prompt(sid: str):
    s = get_session_settings(sid)
    return {
        "session_id": sid,
        "system_prompt": s["system_prompt"],
        "temperature": s["temperature"],
        "max_tokens": s["max_tokens"],
        "is_default": sid not in session_settings,
    }


@app.put("/session/{sid}/system-prompt")
async def set_prompt(sid: str, request: Request):
    body = await request.json()
    updates = {}
    prompt = body.get("system_prompt", "").strip()
    if prompt:
        updates["system_prompt"] = prompt
    if "temperature" in body:
        updates["temperature"] = max(0.0, min(1.5, float(body["temperature"])))
    if "max_tokens" in body:
        updates["max_tokens"] = max(256, min(8192, int(body["max_tokens"])))
    if not prompt and "temperature" not in body and "max_tokens" not in body:
        session_settings.pop(sid, None)
        return {**DEFAULT_SETTINGS, "session_id": sid, "is_default": True, "action": "reset"}
    session_settings[sid] = {**session_settings.get(sid, {}), **updates}
    s = get_session_settings(sid)
    return {
        "session_id": sid,
        "system_prompt": s["system_prompt"],
        "temperature": s["temperature"],
        "max_tokens": s["max_tokens"],
        "is_default": False,
        "action": "updated",
    }


@app.post("/session/{sid}/end")
async def end_session(sid: str, request: Request):
    # Parse optional JSON body (may contain bucket)
    bucket_items = []
    try:
        body = await request.json()
        bucket_items = body.get("bucket", []) if isinstance(body, dict) else []
    except Exception:
        pass

    session = store.get(sid)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Session not found"})

    if len(session.messages) < 2:
        return JSONResponse(content={
            "type": "session_done",
            "result": "Session too short to summarize (< 2 messages)."
        })

    # Summaries always run via a cloud model — local LLMs (openai_compatible)
    # don't reliably emit valid JSON. Fall back to haiku for any local profile.
    current = session.current_model
    model_key = current if MODELS.get(current, {}).get("type") != "openai_compatible" else "haiku"
    history = session.get_history_for_llm()
    history.append({"role": "user", "content": END_SESSION_PROMPT})

    full_response = ""
    try:
        async for chunk in stream_llm(history, "You are a conversation summarizer. Respond only with valid JSON.",
                                       model_key):
            if chunk["type"] == "text":
                full_response += chunk["content"]
    except Exception as e:
        full_response = json.dumps({
            "goal": "Error generating summary", "summary": str(e),
            "decisions": "none", "open_items": "none"
        })

    try:
        clean = full_response.strip().replace("```json", "").replace("```", "").strip()
        summary_data = json.loads(clean)
    except json.JSONDecodeError:
        summary_data = {
            "goal": "Summary parse error", "summary": full_response[:500],
            "decisions": "none", "open_items": "none"
        }

    model_counts = {}
    for msg in session.messages:
        if msg.model and msg.model not in ("runner", "script-runner", "searxng", "system", "context"):
            model_counts[msg.model] = model_counts.get(msg.model, 0) + 1
    primary_model = max(model_counts, key=model_counts.get) if model_counts else "qwen"

    now = datetime.now(timezone.utc).isoformat()
    persona = session_personas.get(sid)
    models_used = ", ".join(sorted(model_counts.keys())) if model_counts else "qwen"
    row_data = {
        "Name": summary_data.get("goal", "")[:255],
        "started_at": datetime.fromtimestamp(session.started_at, tz=timezone.utc).isoformat(),
        "ended_at": now,
        "model_used": primary_model,
        "goal": summary_data.get("goal", ""),
        "summary": summary_data.get("summary", ""),
        "decisions": summary_data.get("decisions", ""),
        "open_items": summary_data.get("open_items", ""),
        "tokens_in": session.total_tokens_in,
        "tokens_out": session.total_tokens_out,
        "cost_usd": str(session.get_total_cost()),
        "persona_name": persona["name"] if persona else "",
        "models_used": models_used,
    }
    if bucket_items:
        row_data["bucket"] = json.dumps(bucket_items, ensure_ascii=False)

    baserow_result = await write_session(row_data)

    # Save full chat history as JSON before deleting session
    try:
        history_dir = Path("/chathistory")
        history_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        history_file = history_dir / f"{ts}_{sid}.json"
        chat_data = {
            "session_id": sid,
            "started_at": datetime.fromtimestamp(session.started_at, tz=timezone.utc).isoformat(),
            "ended_at": now,
            "primary_model": primary_model,
            "models_used": models_used,
            "persona": persona["name"] if persona else None,
            "summary": summary_data,
            "tokens": {"in": session.total_tokens_in, "out": session.total_tokens_out},
            "cost_usd": session.get_total_cost(),
            "bucket": bucket_items if bucket_items else None,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "model": m.model,
                    "tokens_in": m.tokens_in,
                    "tokens_out": m.tokens_out,
                    "timestamp": m.timestamp if hasattr(m, 'timestamp') else None,
                }
                for m in session.messages
            ],
        }
        history_file.write_text(json.dumps(chat_data, ensure_ascii=False, indent=2))
        print(f"[pilot] Chat history saved: {history_file}")
    except Exception as e:
        print(f"[pilot] Failed to save chat history: {e}")

    store.delete(sid)
    session_settings.pop(sid, None)
    session_personas.pop(sid, None)

    return JSONResponse(content={
        "type": "session_ended",
        "summary": summary_data,
        "tokens": {"in": session.total_tokens_in, "out": session.total_tokens_out},
        "cost_usd": session.get_total_cost(),
        "baserow_saved": baserow_result is not None,
        "bucket_items": len(bucket_items),
    })


@app.get("/personas")
async def list_personas():
    personas = await read_personas()
    return [
        {"id": p["id"], "name": p.get("name", ""), "icon": p.get("icon", "🎭"),
         "description": p.get("description", ""),
         "prompt": p.get("prompt", ""),
         "briefing_target": p.get("briefing_target", ""),
         "usage_count": p.get("usage_count", 0)}
        for p in personas
    ]


@app.post("/personas")
async def create_persona(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Name is required"})
    row = await create_persona_row(
        name=name, icon=body.get("icon", "🎭").strip() or "🎭",
        description=body.get("description", "").strip(),
        prompt=body.get("prompt", "").strip(),
        briefing_target=body.get("briefing_target", "").strip(),
    )
    if not row:
        return JSONResponse(status_code=500, content={"error": "Failed to create persona"})
    return {"id": row["id"], "name": row.get("name", name),
            "icon": row.get("icon", "🎭"), "description": row.get("description", ""),
            "briefing_target": row.get("briefing_target", ""), "action": "created"}


@app.post("/session/{sid}/persona")
async def set_persona(sid: str, request: Request):
    body = await request.json()
    persona_id = body.get("persona_id")
    if persona_id is None:
        session_personas.pop(sid, None)
        return {"session_id": sid, "persona": None, "action": "deactivated"}
    personas = await read_personas()
    persona = next((p for p in personas if p["id"] == persona_id), None)
    if not persona:
        return JSONResponse(status_code=404, content={"error": f"Persona {persona_id} not found"})
    session_personas[sid] = {
        "id": persona["id"], "name": persona.get("name", ""),
        "icon": persona.get("icon", "🎭"), "prompt": persona.get("prompt", ""),
        "briefing_target": persona.get("briefing_target", ""),
    }
    await increment_persona_usage(persona["id"], persona.get("usage_count", 0))
    return {"session_id": sid, "persona": {"id": persona["id"], "name": persona.get("name", ""),
            "icon": persona.get("icon", "🎭"), "briefing_target": persona.get("briefing_target", "")},
            "action": "activated"}


@app.delete("/session/{sid}/persona")
async def clear_persona(sid: str):
    session_personas.pop(sid, None)
    return {"session_id": sid, "persona": None, "action": "deactivated"}


@app.get("/session/{sid}/persona")
async def get_persona(sid: str):
    persona = session_personas.get(sid)
    if persona:
        return {"session_id": sid, "persona": {"id": persona["id"], "name": persona["name"],
                "icon": persona["icon"], "briefing_target": persona.get("briefing_target", "")}}
    return {"session_id": sid, "persona": None}


@app.patch("/personas/{persona_id}")
async def update_persona_endpoint(persona_id: int, request: Request):
    body = await request.json()
    row = await update_persona(persona_id, body)
    if not row:
        return JSONResponse(status_code=500, content={"error": "Failed to update persona"})
    return {"id": row["id"], "action": "updated"}


# ============================================================
# POSTS (sm_content)
# ============================================================

@app.get("/posts")
async def get_posts():
    return {"results": await list_posts(), "next": None}


@app.post("/posts")
async def create_post_endpoint(request: Request):
    body = await request.json()
    row = await create_post(body)
    if not row:
        return JSONResponse(status_code=500, content={"error": "Failed to create post"})
    return row


@app.patch("/posts/{post_id}")
async def update_post_endpoint(post_id: int, request: Request):
    body = await request.json()
    row = await update_post(post_id, body)
    if not row:
        return JSONResponse(status_code=500, content={"error": "Failed to update post"})
    return row


# ── Feedback / Bug Reporting ─────────────────────────────────

@app.post("/feedback")
async def submit_feedback(request: Request):
    """Save a feedback/bug report to Baserow."""
    body = await request.json()
    description = (body.get("description") or "").strip()
    if not description:
        return JSONResponse(status_code=400, content={"error": "Description is required"})

    fb_type = body.get("type", "bug")
    severity = body.get("severity", "medium")
    page = body.get("page", "")
    now = datetime.now(timezone.utc).isoformat()

    row_data = {
        "Name": f"[{fb_type.upper()}] {page or 'general'} — {now[:16]}",
        "Type": fb_type,
        "Severity": severity,
        "Description": description,
        "Page": page,
        "Session_ID": body.get("session_id", ""),
        "Model": body.get("model", ""),
        "Persona": body.get("persona", ""),
        "Status": "new",
        "created_at": now,
    }

    # Screenshot: stored as base64 data URL or external URL
    screenshot = body.get("screenshot")
    if screenshot:
        row_data["Screenshot"] = screenshot

    result = await write_feedback(row_data)
    if result:
        return JSONResponse(content={"success": True, "id": result.get("id")})
    return JSONResponse(status_code=500, content={"success": False, "error": "Failed to save feedback"})


@app.get("/feedback/list")
async def get_feedback_list(status: str = None):
    """List feedback entries, optionally filtered by status."""
    entries = await list_feedback(status_filter=status)
    return {"feedback": entries, "count": len(entries)}


@app.patch("/feedback/{row_id}")
async def patch_feedback(row_id: int, request: Request):
    """Update a feedback entry (e.g. change status to resolved)."""
    body = await request.json()
    result = await update_feedback(row_id, body)
    if result:
        return JSONResponse(content={"success": True, "id": row_id})
    return JSONResponse(status_code=500, content={"success": False, "error": "Update failed"})


# ── Bucket Persistence ───────────────────────────────────────

@app.post("/bucket/save")
async def bucket_save(request: Request):
    """Save the current bucket with a name."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    items = body.get("items", [])
    if not name:
        return JSONResponse(status_code=400, content={"error": "Name is required"})
    if not items:
        return JSONResponse(status_code=400, content={"error": "Bucket is empty"})
    result = await save_bucket(name, items)
    if result:
        return JSONResponse(content={"success": True, "id": result.get("id")})
    return JSONResponse(status_code=500, content={"success": False, "error": "Failed to save bucket"})


@app.get("/bucket/list")
async def bucket_list():
    """List all saved buckets."""
    buckets = await list_buckets()
    return {"buckets": [
        {"id": b["id"], "name": b.get("Name", ""), "item_count": b.get("item_count", 0),
         "created_at": b.get("created_at", "")}
        for b in buckets
    ]}


@app.get("/bucket/{row_id}")
async def bucket_get(row_id: int):
    """Get a single bucket with its items."""
    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_buckets}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            row = resp.json()
            items = []
            try:
                items = json.loads(row.get("Items", "[]"))
            except (json.JSONDecodeError, TypeError):
                pass
            return {"id": row["id"], "name": row.get("Name", ""), "items": items,
                    "item_count": row.get("item_count", 0), "created_at": row.get("created_at", "")}
    return JSONResponse(status_code=404, content={"error": "Bucket not found"})


@app.delete("/bucket/{row_id}")
async def bucket_delete(row_id: int):
    """Delete a saved bucket."""
    ok = await delete_bucket(row_id)
    if ok:
        return JSONResponse(content={"success": True})
    return JSONResponse(status_code=500, content={"success": False, "error": "Delete failed"})


# ============================================================
# STYLE PACKS
# ============================================================

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def _scan_image_folder(folder_path: str) -> dict:
    """Scan a folder for image files and return count + first images."""
    p = Path(folder_path)
    if not p.is_dir():
        return {"exists": False, "count": 0, "images": []}
    images = sorted(
        f for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )
    return {
        "exists": True,
        "count": len(images),
        "images": [f.name for f in images[:12]],
    }


@app.get("/api/styles")
async def styles_list():
    """List all style packs."""
    packs = await list_style_packs()
    return JSONResponse(content={"results": packs})


@app.post("/api/styles")
async def styles_create(request: Request):
    """Create a new style pack from folder path or upload."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Name is required"})

    source_type = body.get("source_type", "folder")
    source_path = body.get("source_path", "")
    style_weight = body.get("style_weight", 0.7)
    image_count = 0

    if source_type == "folder":
        # Resolve path: accept relative (to styles_base_path) or absolute
        if not source_path.startswith("/"):
            source_path = f"{settings.styles_base_path}/{source_path}"
        scan = _scan_image_folder(source_path)
        if not scan["exists"]:
            return JSONResponse(status_code=400, content={"error": f"Folder not found: {source_path}"})
        image_count = scan["count"]
        if image_count == 0:
            return JSONResponse(status_code=400, content={"error": "No images found in folder"})

    row = await save_style_pack({
        "name": name,
        "source_type": source_type,
        "source_path": source_path,
        "image_count": image_count,
        "style_weight": style_weight,
    })
    if row:
        return JSONResponse(content=row)
    return JSONResponse(status_code=500, content={"error": "Failed to save style pack"})


@app.get("/api/styles/scan-folder")
async def styles_scan_folder(path: str = ""):
    """Scan a folder for images. Accepts relative (to styles base) or absolute paths."""
    if not path:
        return JSONResponse(status_code=400, content={"error": "path parameter required"})
    if not path.startswith("/"):
        path = f"{settings.styles_base_path}/{path}"
    scan = _scan_image_folder(path)
    return JSONResponse(content=scan)


@app.get("/api/styles/{row_id}")
async def styles_get(row_id: int):
    """Get style pack details including image list from folder."""
    pack = await get_style_pack(row_id)
    if not pack:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    # Enrich with current folder scan
    source_path = pack.get("source_path", "")
    if source_path:
        scan = _scan_image_folder(source_path)
        pack["_images"] = scan.get("images", [])
        pack["_image_count_actual"] = scan.get("count", 0)
    return JSONResponse(content=pack)


@app.patch("/api/styles/{row_id}")
async def styles_update(row_id: int, request: Request):
    """Update a style pack."""
    body = await request.json()
    row = await update_style_pack(row_id, body)
    if row:
        return JSONResponse(content=row)
    return JSONResponse(status_code=500, content={"error": "Update failed"})


@app.delete("/api/styles/{row_id}")
async def styles_delete(row_id: int):
    """Delete a style pack."""
    ok = await delete_style_pack(row_id)
    if ok:
        return JSONResponse(content={"success": True})
    return JSONResponse(status_code=500, content={"success": False, "error": "Delete failed"})


@app.post("/api/styles/upload")
async def styles_upload(name: str, files: List[UploadFile] = File(...)):
    """Upload images to create a new style pack.

    Creates folder /data/styles/{name}/, saves all uploaded images,
    then creates a Baserow entry.
    """
    name = name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Name is required"})

    # Sanitize folder name
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip().replace(" ", "_")
    if not safe_name:
        return JSONResponse(status_code=400, content={"error": "Invalid name"})

    target_dir = Path(settings.styles_base_path) / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        dest = target_dir / f.filename
        content = await f.read()
        dest.write_bytes(content)
        saved += 1

    if saved == 0:
        return JSONResponse(status_code=400, content={"error": "No valid images uploaded"})

    source_path = str(target_dir)
    row = await save_style_pack({
        "name": name,
        "source_type": "upload",
        "source_path": source_path,
        "image_count": saved,
        "style_weight": 0.7,
    })
    if row:
        return JSONResponse(content=row)
    return JSONResponse(status_code=500, content={"error": "Files saved but Baserow entry failed"})


@app.get("/api/styles/list-folders")
async def styles_list_folders():
    """List available subdirectories under the styles base path."""
    base = Path(settings.styles_base_path)
    if not base.is_dir():
        return JSONResponse(content={"folders": [], "base_path": settings.styles_base_path})
    folders = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            scan = _scan_image_folder(str(d))
            folders.append({"name": d.name, "path": str(d), "image_count": scan["count"]})
    return JSONResponse(content={"folders": folders, "base_path": settings.styles_base_path})


async def persist_cost_to_baserow(model_key: str, tokens_in: int, tokens_out: int):
    """Increment monthly costs in bot_costs table (574) after every paid API call."""
    m = MODELS.get(model_key)
    if not m or m.get("type") == "openai_compatible" or (tokens_in == 0 and tokens_out == 0):
        return
    import httpx as _httpx
    cost = (tokens_in / 1_000_000) * m["cost_input_per_1m"] +            (tokens_out / 1_000_000) * m["cost_output_per_1m"]
    if cost == 0:
        return

    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    cost_field = f"cost_{model_key}"

    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            # Find current month row
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true&size=100",
                headers=BASEROW_HEADERS)
            rows = resp.json().get("results", []) if resp.status_code == 200 else []

            row_id = None
            old_model_cost = 0.0
            old_total = 0.0
            old_tokens_in = 0
            old_tokens_out = 0
            for row in rows:
                if row.get("month") == current_month:
                    row_id = row["id"]
                    old_model_cost = float(row.get(cost_field) or 0)
                    old_total = float(row.get("cost_total") or 0)
                    old_tokens_in = int(row.get("tokens_in") or 0)
                    old_tokens_out = int(row.get("tokens_out") or 0)
                    break

            update_data = {
                cost_field: str(round(old_model_cost + cost, 4)),
                "cost_total": str(round(old_total + cost, 4)),
                "tokens_in": str(old_tokens_in + tokens_in),
                "tokens_out": str(old_tokens_out + tokens_out),
            }

            if row_id:
                # Update existing row
                await client.patch(
                    f"{settings.baserow_url}/api/database/rows/table/574/{row_id}/?user_field_names=true",
                    headers=BASEROW_HEADERS, json=update_data)
            else:
                # Create new month row
                update_data["month"] = current_month
                update_data["sessions_total"] = "0"
                for k in ["cost_qwen", "cost_haiku", "cost_sonnet", "cost_opus", "cost_nanban"]:
                    if k not in update_data:
                        update_data[k] = "0"
                await client.post(
                    f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true",
                    headers=BASEROW_HEADERS, json=update_data)
    except Exception as e:
        print(f"[persist_cost] Error: {e}")


async def persist_image_cost_to_baserow(flow_key: str, image_count: int):
    """Increment monthly image generation costs in bot_costs table (574)."""
    from comfyui_client import load_registry
    import httpx as _httpx

    registry = load_registry()
    flow_config = registry["flows"].get(flow_key, {})
    cost_per_image = flow_config.get("cost_per_image", 0)
    if cost_per_image == 0 or image_count == 0:
        print(f"[persist_image_cost] skipped: flow={flow_key}, cost_per_image={cost_per_image}, count={image_count}")
        return

    cost = cost_per_image * image_count
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")

    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true&size=100",
                headers=BASEROW_HEADERS)
            rows = resp.json().get("results", []) if resp.status_code == 200 else []

            row_id = None
            old_nanban = 0.0
            old_total = 0.0
            for row in rows:
                if row.get("month") == current_month:
                    row_id = row["id"]
                    old_nanban = float(row.get("cost_nanban") or 0)
                    old_total = float(row.get("cost_total") or 0)
                    break

            update_data = {
                "cost_nanban": str(round(old_nanban + cost, 4)),
                "cost_total": str(round(old_total + cost, 4)),
            }

            if row_id:
                await client.patch(
                    f"{settings.baserow_url}/api/database/rows/table/574/{row_id}/?user_field_names=true",
                    headers=BASEROW_HEADERS, json=update_data)
            else:
                update_data["month"] = current_month
                update_data["sessions_total"] = "0"
                for k in ["cost_qwen", "cost_haiku", "cost_sonnet", "cost_opus"]:
                    update_data[k] = "0"
                await client.post(
                    f"{settings.baserow_url}/api/database/rows/table/574/?user_field_names=true",
                    headers=BASEROW_HEADERS, json=update_data)
        print(f"[persist_image_cost] {flow_key}: {image_count} images, ${cost:.4f}")
    except Exception as e:
        print(f"[persist_image_cost] Error: {e}")


@app.post("/chat/{sid}")
async def chat(sid: str, request: Request):
    body = await request.json()
    user_message = body.get("message", "").strip()
    image_data = body.get("image", None)
    if not user_message and not image_data:
        return JSONResponse(status_code=400, content={"error": "Empty message"})

    session = store.get_or_create(sid)
    classification = classify_input(user_message)

    if classification["type"] in ("social", "roadmap"):
        session.add_user_message(user_message)
        result = await call_runner(classification["raw"])
        session.add_assistant_message(result, model="runner")
        return JSONResponse(content={"type": "command_result", "result": result, "model": "runner"})

    if classification["type"] == "script":
        session.add_user_message(user_message)
        result_data = await call_script_runner(classification["raw"])
        if result_data.get("subtype") == "stock_results":
            session.add_assistant_message(json.dumps(result_data["data"]), model="script-runner")
            return JSONResponse(content={
                "type": "stock_results",
                "results": result_data["data"].get("results", []),
                "query": result_data["data"].get("query", ""),
                "model": "script-runner"
            })
        else:
            text = result_data.get("data", str(result_data))
            session.add_assistant_message(text, model="script-runner")
            return JSONResponse(content={"type": "command_result", "result": text, "model": "script-runner"})

    if classification["type"] == "search":
        session.add_user_message(user_message)
        query = user_message[7:].strip()
        if not query:
            return JSONResponse(content={"type": "command_result", "result": "Usage: /search <query>", "model": "searxng"})
        result_data = await call_search(query)
        if result_data.get("subtype") == "search_results":
            readable = f"Web search results for '{query}':\n\n"
            for i, r in enumerate(result_data["results"], 1):
                readable += f"{i}. {r['title']}\n   {r['url']}\n   {r['content']}\n\n"
            session.add_assistant_message(readable, model="searxng")
            return JSONResponse(content={
                "type": "search_results",
                "results": result_data["results"],
                "query": result_data["query"],
                "model": "searxng"
            })
        else:
            text = result_data.get("data", str(result_data))
            session.add_assistant_message(text, model="searxng")
            return JSONResponse(content={"type": "command_result", "result": text, "model": "searxng"})

    if classification["type"] == "post":
        session.add_user_message(user_message)
        return JSONResponse(content={"type": "post_widget"})

    if classification["type"] == "ctx":
        session.add_user_message(user_message)
        subcommand = user_message[4:].strip()  # strip "/ctx"
        result = await handle_ctx(session, subcommand)
        return JSONResponse(content={"type": "command_result", "result": result, "model": "context"})

    if classification["type"] == "pixeltext":
        session.add_user_message(user_message)
        result_data = await call_pixeltext(classification["raw"])
        if result_data.get("subtype") == "pixeltext_result":
            urls = result_data.get("urls", [])
            files = result_data.get("files", [])
            rt = result_data.get("render_time_sec")
            lines = [f"PixelText render done in {rt}s — {len(files)} file(s):"]
            for u in urls:
                lines.append(u)
            text = "\n".join(lines)
            session.add_assistant_message(text, model="blender-worker")
            return JSONResponse(content={
                "type": "command_result",
                "result": text,
                "model": "blender-worker",
            })
        text = result_data.get("data", str(result_data))
        session.add_assistant_message(text, model="blender-worker")
        return JSONResponse(content={"type": "command_result", "result": text, "model": "blender-worker"})

    if classification["type"] == "comfyui":
        session.add_user_message(user_message)
        result_data = await call_comfyui(classification["raw"])
        if result_data.get("subtype") == "image_variants":
            if result_data.get("count", 0) == 0:
                session.add_assistant_message(
                    result_data.get("error", "Image generation failed"), model="comfyui")
            else:
                session.add_assistant_message(
                    f"Generated {result_data['count']} variants for: {result_data['prompt']}", model="comfyui")
            await persist_image_cost_to_baserow(result_data.get("flow", ""), result_data.get("count", 0))
            return JSONResponse(content={"type": "image_variants", **result_data})
        if result_data.get("subtype") == "video_result":
            msg = f"Generated video for: {result_data.get('prompt', '')}" if result_data.get("video_url") else "Video generation failed"
            session.add_assistant_message(msg, model="comfyui")
            return JSONResponse(content={"type": "video_result", **result_data})
        if result_data.get("subtype") == "expand_result":
            session.add_assistant_message(
                f"Expanded image to {result_data.get('target', '1920x1920')}", model="comfyui")
            return JSONResponse(content={"type": "expand_result", **result_data})
        if result_data.get("subtype") == "upscale_result":
            session.add_assistant_message(
                f"Upscaled image by {result_data.get('factor', 2)}x", model="comfyui")
            return JSONResponse(content={"type": "upscale_result", **result_data})
        text = result_data.get("data", str(result_data))
        session.add_assistant_message(text, model="comfyui")
        return JSONResponse(content={"type": "command_result", "result": text, "model": "comfyui"})

    if classification["type"] == "tool_widget":
        return JSONResponse(content={"type": "tool_widget"})

    if classification["type"] == "session_done":
        return JSONResponse(content={"type": "session_done",
                                      "result": "Use the Session Done button or POST /session/{sid}/end"})

    session.add_user_message(user_message)
    model_key = session.current_model
    if image_data and not MODELS[model_key]["supports_vision"]:
        model_key = "haiku"

    s = get_session_settings(sid)

    async def event_generator():
        full_response = ""
        usage = {"input_tokens": 0, "output_tokens": 0}
        async for chunk in stream_llm(session.get_history_for_llm(),
                                       get_system_prompt(sid, model_key), model_key,
                                       image_data, s["temperature"], s["max_tokens"]):
            if chunk["type"] == "text":
                full_response += chunk["content"]
                yield {"event": "text", "data": json.dumps({"content": chunk["content"]})}
            elif chunk["type"] == "done":
                usage = chunk.get("usage", usage)
                yield {"event": "done", "data": json.dumps({"model": model_key, "usage": usage})}
        session.add_assistant_message(full_response, model=model_key,
                                       tokens_in=usage.get("input_tokens", 0),
                                       tokens_out=usage.get("output_tokens", 0))
        await persist_cost_to_baserow(model_key, usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    return EventSourceResponse(event_generator())


## ═══════════════════════════════════════════════════════════════
##  VIDEO GENERATION WITH PROGRESS (SSE)
## ═══════════════════════════════════════════════════════════════

@app.post("/vid/generate")
async def vid_generate(request: Request):
    """Queue a video generation job, return prompt_id immediately."""
    from comfyui_client import (parse_vid_command, build_video_workflow,
                                 queue_prompt, resolve_flow, get_flow_info)
    import random
    try:
        body = await request.json()
        command = body.get("command", "")
        parsed = parse_vid_command(command)
        if not parsed["prompt"]:
            return JSONResponse(status_code=400, content={"error": "No prompt provided"})

        flow = resolve_flow(parsed["flow"])
        flow_info = get_flow_info(flow)
        actual_seed = parsed.get("seed") or random.randint(0, 2**32 - 1)

        workflow = build_video_workflow(
            parsed["prompt"], flow=flow, seed=actual_seed,
            format=parsed.get("format"), steps=parsed.get("steps"),
            length=parsed.get("length"), fps=parsed.get("fps"),
            start_image=parsed.get("start_image"), end_image=parsed.get("end_image"),
        )
        prompt_id = await queue_prompt(workflow)

        return JSONResponse(content={
            "prompt_id": prompt_id,
            "seed": actual_seed,
            "flow": flow,
            "flow_name": flow_info["name"],
            "prompt": parsed["prompt"],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/vid/status/{prompt_id}")
async def vid_status(prompt_id: str):
    """Simple poll endpoint: check if a ComfyUI job is done."""
    import httpx
    COMFYUI_URL = "http://comfyui:8188"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            if r.status_code == 200:
                data = r.json()
                if prompt_id in data:
                    from comfyui_client import extract_video_filenames
                    fnames = extract_video_filenames(data[prompt_id])
                    if fnames:
                        return {"status": "done", "video_url": f"/comfyui/wip/{fnames[0]}", "filename": fnames[0].split("/")[-1]}
                    status = data[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        err = msgs[-1][-1].get("exception_message", "Error") if msgs else "Error"
                        return {"status": "error", "message": err}
                    return {"status": "error", "message": "No video output"}
            return {"status": "working"}
    except Exception as e:
        return {"status": "working"}


## ═══════════════════════════════════════════════════════════════
##  MUSIC GENERATION WITH ACE-STEP 1.5 (ComfyUI)
## ═══════════════════════════════════════════════════════════════

@app.post("/upload/comfyui-audio")
async def upload_audio_to_comfyui(file: UploadFile = File(...)):
    """Proxy audio upload to ComfyUI input directory for reference audio."""
    import httpx
    COMFYUI_URL = "http://comfyui:8188"
    try:
        content = await file.read()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={"image": (file.filename, content, file.content_type or "audio/mpeg")},
                data={"overwrite": "true"},
            )
            if resp.status_code == 200:
                return resp.json()
            return JSONResponse(status_code=resp.status_code,
                                content={"error": f"ComfyUI upload failed: {resp.text[:200]}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/music/generate")
async def music_generate(request: Request):
    """Queue a music generation job via ComfyUI ACE-Step 1.5, return prompt_id."""
    from comfyui_client import queue_prompt
    import random, json

    try:
        body = await request.json()
        tags = body.get("tags", "")
        lyrics = body.get("lyrics", "")
        duration = int(body.get("duration", 30))
        seed = body.get("seed", -1)
        steps = int(body.get("steps", 8))
        bpm = int(body.get("bpm", 120))
        key = body.get("key", "C major")
        time_sig = body.get("time_signature", "4")
        language = body.get("language", "en")
        ref_audio_filename = body.get("ref_audio_filename", None)

        if not tags and not lyrics:
            return JSONResponse(status_code=400, content={"error": "Provide tags or lyrics"})

        actual_seed = seed if seed >= 0 else random.randint(0, 2**32 - 1)
        use_ref = bool(ref_audio_filename)

        # Build API-format workflow (AIO checkpoint)
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "ace_step_1.5_turbo_aio.safetensors"
                }
            },
            "5": {
                "class_type": "EmptyAceStep1.5LatentAudio",
                "inputs": {
                    "seconds": duration,
                    "batch_size": 1
                }
            },
            "6": {
                "class_type": "TextEncodeAceStepAudio1.5",
                "inputs": {
                    "tags": tags,
                    "lyrics": lyrics,
                    "seed": actual_seed,
                    "bpm": bpm,
                    "duration": duration,
                    "timesignature": time_sig,
                    "language": language,
                    "keyscale": key,
                    "generate_audio_codes": True,
                    "cfg_scale": 2.0,
                    "temperature": 0.85,
                    "top_p": 0.9,
                    "top_k": 0,
                    "min_p": 0.0,
                    "clip": ["1", 1]
                }
            },
            "7": {
                "class_type": "ConditioningZeroOut",
                "inputs": {
                    "conditioning": ["6", 0]
                }
            },
            "8": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": actual_seed,
                    "control_after_generate": "fixed",
                    "steps": steps,
                    "cfg": 1,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1,
                    "model": ["1", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                }
            },
            "9": {
                "class_type": "VAEDecodeAudio",
                "inputs": {
                    "samples": ["8", 0],
                    "vae": ["1", 2]
                }
            },
            "10": {
                "class_type": "SaveAudioMP3",
                "inputs": {
                    "filename_prefix": f"music/mus_{datetime.now().strftime('%y%m%d-%H%M')}",
                    "quality": "V0",
                    "audio": ["9", 0]
                }
            }
        }

        # Reference audio: encode to latent, inject into conditioning
        if use_ref:
            workflow["11"] = {
                "class_type": "LoadAudio",
                "inputs": {
                    "audio": ref_audio_filename,
                }
            }
            workflow["12"] = {
                "class_type": "VAEEncodeAudio",
                "inputs": {
                    "audio": ["11", 0],
                    "vae": ["1", 2],
                }
            }
            workflow["13"] = {
                "class_type": "ReferenceTimbreAudio",
                "inputs": {
                    "conditioning": ["6", 0],
                    "latent": ["12", 0],
                }
            }
            # KSampler uses reference-augmented conditioning
            workflow["8"]["inputs"]["positive"] = ["13", 0]

        prompt_id = await queue_prompt(workflow)

        return JSONResponse(content={
            "prompt_id": prompt_id,
            "seed": actual_seed,
            "tags": tags,
            "duration": duration,
            "bpm": bpm,
            "mode": "reference" if use_ref else "text2music",
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/music/status/{prompt_id}")
async def music_status(prompt_id: str):
    """Poll endpoint: check if a music generation job is done."""
    import httpx
    COMFYUI_URL = "http://comfyui:8188"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            if r.status_code == 200:
                data = r.json()
                if prompt_id in data:
                    outputs = data[prompt_id].get("outputs", {})
                    for node_id, node_output in outputs.items():
                        # Audio files appear under "audio" key in SaveAudioMP3
                        audios = node_output.get("audio", [])
                        for a in audios:
                            if a.get("type") == "output":
                                subfolder = a.get("subfolder", "")
                                fname = a["filename"]
                                path = f"{subfolder}/{fname}" if subfolder else fname
                                return {"status": "done", "audio_url": f"/comfyui/wip/{path}", "filename": fname}
                    status_info = data[prompt_id].get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        err = msgs[-1][-1].get("exception_message", "Error") if msgs else "Error"
                        return {"status": "error", "message": err}
                    return {"status": "error", "message": "No audio output found"}
            return {"status": "working"}
    except Exception as e:
        return {"status": "working"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
