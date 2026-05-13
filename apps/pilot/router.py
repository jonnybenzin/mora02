def starts_with_any(text: str, prefixes: list[str]) -> bool:
    t = text.strip().lower()
    return any(t.startswith(p) for p in prefixes)


def classify_input(user_input: str) -> dict:
    s = user_input.strip()
    if s.lower().startswith("/post"):
        return {"type": "post", "raw": s}
    if s.lower().startswith("/rd"):
        return {"type": "roadmap", "raw": s}
    if starts_with_any(s, ["/gif", "/typ", "/clip", "/stock"]):
        return {"type": "script", "raw": s}
    if starts_with_any(s, ["/img", "/vid", "/expand"]):
        return {"type": "comfyui", "raw": s}
    if starts_with_any(s, ["/music", "/voice"]):
        return {"type": "tool_widget", "raw": s}
    if s.lower().startswith("/pix"):
        return {"type": "pixeltext", "raw": s}
    if s.lower().startswith("/search"):
        return {"type": "search", "raw": s}
    if s.lower().startswith("/ctx"):
        return {"type": "ctx", "raw": s}
    if s.lower() in ["session done", "/done", "/end"]:
        return {"type": "session_done", "raw": s}
    return {"type": "dialog", "raw": s}
