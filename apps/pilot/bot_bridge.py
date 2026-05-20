import httpx
import json
from config import settings


def _wrap_image_assets(result: dict) -> dict:
    """Mirror result['assets'] (list[Asset], phase 1.4) into result['images']
    so the chat frontend keeps its {filename,url,variant} shape.

    Drops the assets key from the result — JSONResponse can't serialize
    dataclasses, and the frontend doesn't need them.
    """
    assets = result.pop("assets", [])
    images = []
    for a in assets:
        item = {
            "filename": a.filename,
            "url": a.metadata.get("url", str(a.path)),
        }
        if "variant" in a.metadata:
            item["variant"] = a.metadata["variant"]
        images.append(item)
    result["images"] = images
    return result


def _wrap_video_asset(result: dict) -> dict:
    """Same idea as _wrap_image_assets, but the video subtype expects
    flat video_url + filename instead of an images list."""
    assets = result.pop("assets", [])
    if assets:
        a = assets[0]
        result["video_url"] = a.metadata.get("url", str(a.path))
        result["filename"] = a.filename.split("/")[-1]
    else:
        result.setdefault("video_url", None)
    return result


async def call_runner(command: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.dify_api_url}/v1/chat-messages",
            headers={"Authorization": f"Bearer {settings.dify_api_key}",
                     "Content-Type": "application/json"},
            json={"inputs": {}, "query": command,
                  "response_mode": "blocking", "user": "pilot"})
        if resp.status_code == 200:
            return resp.json().get("answer", "Keine Antwort vom Runner")
        return f"Runner Error: {resp.status_code} - {resp.text}"


async def call_script_runner(command: str) -> dict:
    """Returns dict with type info for frontend rendering."""
    stripped = command.strip()
    if stripped.lower().startswith("/stock"):
        query = stripped[6:].strip()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{settings.script_runner_url}/search/pexels",
                                      json={"query": query})
            if resp.status_code == 200:
                data = resp.json()
                return {"subtype": "stock_results", "data": data}
            return {"subtype": "text", "data": f"Script-Runner Error: {resp.status_code} - {resp.text}"}
    if stripped.lower().startswith("/gif"):
        return {"subtype": "text", "data": "GIF braucht Bilder \u2192 mora02.local:8092/script-bot/"}
    if stripped.lower().startswith("/typ"):
        return {"subtype": "text", "data": "Typer braucht Parameter \u2192 mora02.local:8092/script-bot/"}
    if stripped.lower().startswith("/clip"):
        return {"subtype": "text", "data": "Clipper braucht Medien \u2192 mora02.local:8092/script-bot/"}
    return {"subtype": "text", "data": f"Unbekannter Script-Command: {stripped}"}


async def call_search(query: str) -> dict:
    """Search via local SearXNG instance."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{settings.searxng_url}/search",
            params={"q": query, "format": "json", "categories": "general"})
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get("results", [])[:8]:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "engines": r.get("engines", []),
                })
            return {"subtype": "search_results", "query": query, "results": results}
        return {"subtype": "text", "data": f"SearXNG Error: {resp.status_code}"}


async def call_comfyui(command: str) -> dict:
    stripped = command.strip().lower()
    if stripped.startswith("/vid"):
        return await call_comfyui_video(command)
    if stripped.startswith("/expand"):
        return await call_comfyui_expand(command)
    if stripped.startswith("/upscale") or stripped.startswith("/up "):
        return await call_comfyui_upscale(command)
    from comfyui_client import (
        generate_images, parse_img_command,
        prepare_style_images_via_api, IPADAPTER_FLOWS,
    )
    try:
        parsed = parse_img_command(command)
        if not parsed["prompt"]:
            return {"subtype": "text", "data": "Usage: /img [prompt] --flow [sd15|photo|illustration] --count [1-8]"}

        # Resolve style reference → prepare images for IP-Adapter
        style_images = None
        style_weight = parsed.get("style_weight") or 0.7
        style_name = parsed.get("style")
        if style_name:
            from comfyui_client import resolve_flow
            resolved_flow = resolve_flow(parsed["flow"])
            if resolved_flow in IPADAPTER_FLOWS:
                from mora02_core.baserow import get_style_pack_by_name
                pack = await get_style_pack_by_name(style_name)
                if pack and pack.get("source_path"):
                    style_images = await prepare_style_images_via_api(
                        pack["source_path"], count=4
                    )
                    if pack.get("style_weight"):
                        style_weight = parsed.get("style_weight") or float(pack["style_weight"])

        style_type = parsed.get("style_type") or "style transfer"

        result = await generate_images(
            parsed["prompt"],
            flow=parsed["flow"],
            batch_size=parsed["count"],
            format=parsed.get("format"),
            cfg=parsed.get("cfg"),
            steps=parsed.get("steps"),
            seed=parsed.get("seed"),
            upscale=parsed.get("upscale", False),
            facedetail=parsed.get("facedetail", False),
            testrun=parsed.get("testrun", False),
            style_images=style_images,
            style_weight=style_weight,
            style_type=style_type,
        )
        return _wrap_image_assets(result)
    except Exception as e:
        return {"subtype": "text", "data": f"ComfyUI Error: {str(e)}"}


async def call_pixeltext(command: str) -> dict:
    """Minimal /pixel slash command — single word render with defaults.

    Usage:
        /pixel HELLO              → single word, MP4
        /pixel multi: A / B / C   → multi-word transition, MP4

    The full parameter set lives in the PixelText UI page; this command
    is intentionally thin and exists as a quick trigger from chat.
    """
    text = command.strip()
    # Strip the leading slash command word ("/pix" — case-insensitive)
    if text.lower().startswith("/pix"):
        text = text[4:].strip()
    if not text:
        return {"subtype": "text",
                "data": "Usage: /pix TEXT  or  /pix multi: WORD1 / WORD2 / WORD3"}

    if text.lower().startswith("multi:"):
        body = text[6:].strip()
        words = [w.strip().upper() for w in body.split("/") if w.strip()]
        if not words:
            return {"subtype": "text", "data": "Usage: /pix multi: WORD1 / WORD2"}
        config = {"mode": "multi", "words": words, "render_format": "MP4"}
    else:
        config = {"mode": "single", "text": text.upper(), "words": [text.upper()],
                  "render_format": "MP4"}

    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            files = {"config": (None, json.dumps(config))}
            resp = await client.post(f"{settings.blender_worker_url}/render", files=files)
        data = resp.json()
        if resp.status_code == 503 and not data.get("success"):
            return {"subtype": "text", "data": f"PixelText: {data.get('error', 'VRAM check failed')}"}
        if not data.get("success"):
            return {"subtype": "text",
                    "data": f"PixelText error: {data.get('error', 'unknown')[:500]}"}
        files_out = data.get("files", [])
        if not files_out:
            return {"subtype": "text", "data": "PixelText: render done but no output files"}
        urls = [f"{settings.pixeltext_assets_url}/{data['job_id']}/{f}" for f in files_out]
        return {"subtype": "pixeltext_result",
                "render_time_sec": data.get("render_time_sec"),
                "job_id": data["job_id"],
                "files": files_out,
                "urls": urls}
    except Exception as e:
        return {"subtype": "text", "data": f"PixelText request failed: {e}"}


async def call_comfyui_video(command: str) -> dict:
    from comfyui_client import generate_video, parse_vid_command
    try:
        parsed = parse_vid_command(command)
        if not parsed["prompt"]:
            return {"subtype": "text", "data": "Usage: /vid [prompt] --flow [wan-t2v|wan-i2v|wan-i2i2v]"}
        result = await generate_video(
            parsed["prompt"],
            flow=parsed["flow"],
            format=parsed.get("format"),
            steps=parsed.get("steps"),
            seed=parsed.get("seed"),
            length=parsed.get("length"),
            fps=parsed.get("fps"),
            start_image=parsed.get("start_image"),
            end_image=parsed.get("end_image"),
        )
        return _wrap_video_asset(result)
    except Exception as e:
        return {"subtype": "text", "data": f"ComfyUI Video Error: {str(e)}"}


async def call_comfyui_expand(command: str) -> dict:
    from comfyui_client import expand_image
    try:
        # Parse: /expand [image-url] --prompt [text] --strength [0-1] --seed [n]
        parts = command.strip().split()
        image_url = ""
        prompt = ""
        seed = None
        steps = None
        feathering = None

        i = 1  # skip /expand
        prompt_tokens = []
        while i < len(parts):
            p = parts[i].lower()
            if p.startswith("http") or p.startswith("/"):
                image_url = parts[i]
            elif p == "--prompt" and i + 1 < len(parts):
                i += 1
                while i < len(parts) and not parts[i].startswith("--"):
                    prompt_tokens.append(parts[i])
                    i += 1
                prompt = " ".join(prompt_tokens)
                continue
            elif p == "--seed" and i + 1 < len(parts):
                i += 1
                try: seed = int(parts[i])
                except ValueError: pass
            elif p == "--steps" and i + 1 < len(parts):
                i += 1
                try: steps = int(parts[i])
                except ValueError: pass
            elif p == "--feathering" and i + 1 < len(parts):
                i += 1
                try: feathering = int(parts[i])
                except ValueError: pass
            i += 1

        if not image_url:
            return {"subtype": "text", "data": "Usage: /expand [image-url] --prompt [context] --steps [n] --feathering [n]"}

        result = await expand_image(
            image_url=image_url,
            prompt=prompt,
            seed=seed,
            steps=steps,
            feathering=feathering,
        )
        return _wrap_image_assets(result)
    except Exception as e:
        return {"subtype": "text", "data": f"Expander Error: {str(e)}"}


async def call_comfyui_upscale(command: str) -> dict:
    from comfyui_client import upscale_image
    try:
        # Parse: /upscale [image-url] --factor [2|3|4] --denoise [0.1-0.4]
        #                  --prompt [hint] --seed [n] --steps [n] --cfg [n]
        parts = command.strip().split()
        image_url = ""
        prompt = ""
        factor = 2.0
        denoise = None
        seed = None
        steps = None
        cfg = None

        i = 1  # skip /upscale (or /up)
        prompt_tokens = []
        while i < len(parts):
            p = parts[i].lower()
            if p.startswith("http") or p.startswith("/comfyui/") or p.startswith("/output/"):
                image_url = parts[i]
            elif p == "--prompt" and i + 1 < len(parts):
                i += 1
                while i < len(parts) and not parts[i].startswith("--"):
                    prompt_tokens.append(parts[i])
                    i += 1
                prompt = " ".join(prompt_tokens)
                continue
            elif p == "--factor" and i + 1 < len(parts):
                i += 1
                try: factor = float(parts[i])
                except ValueError: pass
            elif p == "--denoise" and i + 1 < len(parts):
                i += 1
                try: denoise = float(parts[i])
                except ValueError: pass
            elif p == "--seed" and i + 1 < len(parts):
                i += 1
                try: seed = int(parts[i])
                except ValueError: pass
            elif p == "--steps" and i + 1 < len(parts):
                i += 1
                try: steps = int(parts[i])
                except ValueError: pass
            elif p == "--cfg" and i + 1 < len(parts):
                i += 1
                try: cfg = float(parts[i])
                except ValueError: pass
            i += 1

        if not image_url:
            return {"subtype": "text",
                    "data": "Usage: /upscale [image-url] --factor [2|3|4] --denoise [0.1-0.4] --prompt [hint] --seed [n]"}

        result = await upscale_image(
            image_url=image_url,
            factor=factor,
            prompt=prompt,
            denoise=denoise,
            seed=seed,
            steps=steps,
            cfg=cfg,
        )
        return _wrap_image_assets(result)
    except Exception as e:
        return {"subtype": "text", "data": f"Upscaler Error: {str(e)}"}
