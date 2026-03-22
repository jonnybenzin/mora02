#!/usr/bin/env python3
"""
Mora02 — README Generator
Liest jedes Script, schickt es an Qwen, speichert README_draft.md
"""

import json, urllib.request, os, sys
from pathlib import Path

SCRIPTS_DIR = Path("/opt/mora02/scripts")
LLM_URL = "http://localhost:8080/v1/chat/completions"

# Scripts die ein README bekommen sollen: (ordner, hauptscript)
TARGETS = [
    ("gifer", "gifer.py"),
    ("pexels", "pexels.py"),
    ("pixabay", "pixabay.py"),
    ("clipper", "clipper.py"),
    ("typer", "typer.py"),
    ("xray", "mora02-xray.py"),
    ("backup", None),       # Shell-Scripts, alle einlesen
    ("docker", None),       # Shell-Scripts
    ("system", None),       # Shell-Scripts
    ("changelog", "build-changelog.py"),
]

SYSTEM_PROMPT = """You write documentation for Mora02, a self-hosted AI Creative Factory running on Ubuntu 24.04 with an RTX 5090 GPU. The reader is the developer himself, 6 months from now. He forgot the context and needs a README that reads like a concise technical article.

Style rules:
- English, technical, matter-of-fact
- NO flowery language ("powerful", "stunning", "mit der Kraft von")
- Each section starts with 1-2 sentences of CONTEXT before technical details
- Parameter tables are fine, but only AFTER a prose explanation
- Examples describe realistic scenarios
- Be specific about what the code actually does
- Do NOT invent features or flags that don't exist in the code
- All paths and defaults MUST come from the code

README structure:
# Tool-Name — one-liner
(2-3 sentences: What is this? Why does it exist? When do you use it?)

## Quick Start
(Minimal working example with brief explanation)

## What It Does
(Prose: features, capabilities, typical outputs)

## Parameters
(Prose intro, then table with params and defaults FROM THE CODE)

## Practical Examples
(3-4 scenarios with context on why you'd use that configuration)

## How It Works
(Prose: pipeline from input to output)

## Directory Structure
(Tree + short explanation of what goes where)

## Dependencies
(Python libs, system tools, what needs to be installed)

## Configuration
(Which variables to change, with line numbers if possible)

## Troubleshooting
(3-4 common problems with context on why they happen)

For shell script collections (backup/, docker/, system/): List each script with a one-liner description, then explain the overall purpose of the collection.

Write /no_think at the start. Output ONLY the README content."""


def read_scripts(folder, main_script=None):
    """Read script content from a folder"""
    folder_path = SCRIPTS_DIR / folder
    if not folder_path.exists():
        return None
    
    if main_script and (folder_path / main_script).exists():
        with open(folder_path / main_script, "r") as f:
            return f.read()
    
    # Shell script collection: read all .sh and .py files
    content = []
    for ext in ["*.py", "*.sh"]:
        for f in sorted(folder_path.glob(ext)):
            if f.name == "README.md" or f.name.startswith("README"):
                continue
            try:
                with open(f, "r") as fh:
                    text = fh.read()
                content.append(f"=== {f.name} ({len(text.splitlines())} lines) ===\n{text}")
            except:
                pass
    
    return "\n\n".join(content) if content else None


def generate_readme(folder, code):
    """Call Qwen to generate README"""
    payload = {
        "model": "qwen3-14b",
        "temperature": 0.3,
        "max_tokens": 5000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Create README.md for this code. The code is the single source of truth.\n\n{code}"}
        ]
    }
    
    req = urllib.request.Request(
        LLM_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        return content.replace("/no_think", "").strip()


def main():
    print("=" * 60)
    print("Mora02 README Generator")
    print("=" * 60)
    
    results = []
    
    for folder, main_script in TARGETS:
        print(f"\n[{folder}] Reading code...")
        code = read_scripts(folder, main_script)
        
        if not code:
            print(f"  ⚠ No scripts found in {folder}/")
            continue
        
        lines = code.count("\n")
        print(f"  {lines} lines of code")
        
        # Truncate if too long (Qwen context limit)
        if len(code) > 30000:
            print(f"  ⚠ Truncating to 30000 chars (was {len(code)})")
            code = code[:30000] + "\n\n# ... (truncated)"
        
        print(f"  Generating README...")
        try:
            readme = generate_readme(folder, code)
            
            draft_path = SCRIPTS_DIR / folder / "README_draft.md"
            with open(draft_path, "w") as f:
                f.write(readme)
            
            print(f"  ✓ {len(readme)} chars → {draft_path}")
            results.append((folder, "✓", len(readme)))
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append((folder, "✗", str(e)))
    
    print("\n" + "=" * 60)
    print("Summary:")
    for folder, status, info in results:
        print(f"  {status} {folder:20s} {info}")
    print("=" * 60)
    print(f"\nNext: Review drafts, then rename to README.md:")
    print(f"  for d in {' '.join(t[0] for t in TARGETS)}; do")
    print(f'    mv /opt/mora02/scripts/$d/README_draft.md /opt/mora02/scripts/$d/README.md')
    print(f"  done")


if __name__ == "__main__":
    main()
