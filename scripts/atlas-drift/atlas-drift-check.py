#!/usr/bin/env python3
"""Atlas-Drift-Check — zeigt welche Atlas-Artikel von Code-Aenderungen betroffen sein koennten.

Liest die Quellen-Sektion jedes Atlas-Artikels unter kompendium/atlas/,
extrahiert die referenzierten Pfade, vergleicht mit den von git diff
betroffenen Dateien.

Aufrufe:
    python3 atlas-drift-check.py                  # checkt HEAD (letzter Commit)
    python3 atlas-drift-check.py main..HEAD       # checkt Commit-Range
    python3 atlas-drift-check.py <commit-hash>    # checkt einen spezifischen Commit

Exit-Code:
    0 — kein Drift erkannt oder Hinweise ausgegeben (informativ, nicht blockierend)

Aufruf als post-commit-Hook (optional):
    ln -s /opt/mora02/scripts/atlas-drift/atlas-drift-check.py \\
          /opt/mora02/.git/hooks/post-commit
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/opt/mora02")
ATLAS_DIR = REPO_ROOT / "kompendium" / "atlas"
ATLAS_SKIP = {"README.md", "coverage.md"}


def parse_atlas_sources(md_path: Path) -> list[str]:
    """Parse the '## Quellen' bullet list, return repo-relative paths."""
    text = md_path.read_text(encoding="utf-8")

    # Find ## Quellen section (until next ## or EOF)
    m = re.search(
        r"^## Quellen\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not m:
        return []
    section = m.group(1)

    paths = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("-"):
            continue
        body = line[1:].strip()

        # The path is the leading token; chunked off at first " — " or " (" or " "
        # We want to preserve "apps/pilot/app.py" but cut "apps/pilot/app.py:42"
        first = re.split(r"\s+—|\s+\(|\s{2,}", body, maxsplit=1)[0]
        # Sometimes path and description are separated by single space — only the
        # first whitespace-delimited token is the path then. We accept either form.
        # Cut at first whitespace if not already split, but only if the result
        # still contains a path separator.
        if " " in first:
            candidate = first.split(" ", 1)[0]
            if "/" in candidate:
                first = candidate

        path = first.strip()
        # Strip line-number suffix like ":42" or ":42-58"
        path = re.sub(r":\d+(-\d+)?$", "", path)
        # Strip trailing slash for consistency
        path = path.rstrip("/")

        # Only keep things that look like in-repo paths
        if "/" in path and not path.startswith(("http://", "https://")):
            paths.append(path)

    return paths


def get_changed_files(rev: str) -> list[str]:
    """Return list of repo-relative paths changed in rev (or range)."""
    if ".." in rev:
        cmd = ["git", "diff", "--name-only", rev]
    else:
        cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", rev]

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )
    if result.returncode != 0:
        print(f"git failed: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def path_matches(source_path: str, changed_path: str) -> bool:
    """True if changed_path is the source_path itself or lives under it."""
    src_norm = source_path.lstrip("/").rstrip("/")
    if changed_path == src_norm:
        return True
    if changed_path.startswith(src_norm + "/"):
        return True
    return False


def main() -> int:
    rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    changed = get_changed_files(rev)

    if not changed:
        print(f"atlas-drift-check: no files changed in {rev}")
        return 0

    hits: dict[str, list[tuple[str, str]]] = {}
    for atlas in sorted(ATLAS_DIR.glob("*.md")):
        if atlas.name in ATLAS_SKIP:
            continue
        sources = parse_atlas_sources(atlas)
        for src in sources:
            for changed_path in changed:
                if path_matches(src, changed_path):
                    hits.setdefault(atlas.name, []).append((src, changed_path))

    if not hits:
        print(f"atlas-drift-check: no atlas drift detected for {rev}")
        return 0

    print(f"atlas-drift-check: possible drift detected for {rev}")
    print("=" * 60)
    for atlas_name in sorted(hits):
        # Group hits by source-anchor: anchor -> list of changed paths
        by_anchor: dict[str, list[str]] = {}
        for src, changed_path in hits[atlas_name]:
            by_anchor.setdefault(src, [])
            if changed_path not in by_anchor[src]:
                by_anchor[src].append(changed_path)

        print(f"\n{atlas_name}")
        for src in sorted(by_anchor):
            paths = by_anchor[src]
            if len(paths) == 1:
                print(f"  {src}  <-  {paths[0]}")
            else:
                # Show count + first two examples
                example = ", ".join(Path(p).name for p in paths[:2])
                if len(paths) > 2:
                    example += f" + {len(paths) - 2} more"
                print(f"  {src}  <-  {len(paths)} files ({example})")
    print()
    print("Pruefe ob die betroffenen Atlas-Artikel aktualisiert werden muessen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
