def starts_with_any(text: str, prefixes: list[str]) -> bool:
    t = text.strip().lower()
    return any(t.startswith(p) for p in prefixes)


def classify_input(user_input: str) -> dict:
    s = user_input.strip()
    if starts_with_any(s, ["/new", "/show", "/list", "/find", "/edit",
                           "/draft", "/write", "/proofread", "/review",
                           "/apply", "/status", "/delete", "/publish"]):
        return {"type": "social", "raw": s}
    if s.lower().startswith("/rd"):
        return {"type": "roadmap", "raw": s}
    if starts_with_any(s, ["/gif", "/typer", "/clip", "/stock"]):
        return {"type": "script", "raw": s}
    if starts_with_any(s, ["/img", "/vid"]):
        return {"type": "comfyui", "raw": s}
    if s.lower().startswith("/search"):
        return {"type": "search", "raw": s}
    if s.lower().startswith("/ctx"):
        return {"type": "ctx", "raw": s}
    if s.lower() in ["session done", "/done", "/end"]:
        return {"type": "session_done", "raw": s}
    return {"type": "dialog", "raw": s}
