#!/usr/bin/env python3
"""Report which third-party images in docker-compose.yml have newer versions.

For every ``image:`` line the script prints the pinned reference, what is
actually running locally (image id date, via ``docker image inspect`` when
docker is available), and the newest matching version on the registry.
Floating tags (``latest``, ``server-cuda``) are resolved to the concrete tag
that currently carries the same digest, so drift becomes visible.

Only the standard library is used, so it runs on the host python.

Usage:
    scripts/docker/image-check.py [--compose docker/docker-compose.yml] [--no-docker]

Rules per image live in RULES below: a regex that selects comparable tags
(same major, same flavour) so the report never suggests jumping a major
version silently. Images without a rule fall back to "newest semver tag".
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

# Which tags count as "an update" for a given repository. The regex is
# matched against tag names; the first capture groups are compared numerically.
# Keep majors that require a migration (postgres, redis, baserow) on the
# major we run - a major jump is a decision, not an update.
RULES = {
    "postgres": r"^15\.(\d+)-alpine$",
    "redis": r"^7\.(\d+)\.(\d+)-alpine$",
    "nginx": r"^1\.(\d+)\.(\d+)-alpine$",
    "baserow/baserow": r"^(\d+)\.(\d+)\.(\d+)$",
    "penpotapp/backend": r"^(\d+)\.(\d+)\.(\d+)$",
    "penpotapp/frontend": r"^(\d+)\.(\d+)\.(\d+)$",
    "penpotapp/exporter": r"^(\d+)\.(\d+)\.(\d+)$",
    "bbernhard/signal-cli-rest-api": r"^(\d+)\.(\d+)$",
    "searxng/searxng": r"^(\d{4})\.(\d+)\.(\d+)-[0-9a-f]+$",
    "ghcr.io/ggml-org/llama.cpp": r"^server-cuda-b(\d+)$",
    "ghcr.io/remsky/kokoro-fastapi-cpu": r"^v(\d+)\.(\d+)\.(\d+)$",
    "excalidraw/excalidraw": r"^(latest)$",
    "excalidraw/excalidraw-room": r"^(latest)$",
}
GENERIC = r"^v?(\d+)\.(\d+)\.(\d+)$"

MANIFEST_ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def http(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        if method == "HEAD":
            return dict(resp.headers)
        return json.load(resp)


class Registry:
    """Tags and digests for Docker Hub and ghcr.io, anonymous pull scope."""

    def __init__(self, repo):
        if repo.startswith("ghcr.io/"):
            self.host, self.path = "ghcr.io", repo[len("ghcr.io/"):]
        else:
            self.host = "registry-1.docker.io"
            self.path = repo if "/" in repo else "library/" + repo
        self._token = None

    def _headers(self):
        if self._token is None:
            if self.host == "ghcr.io":
                url = f"https://ghcr.io/token?scope=repository:{self.path}:pull"
            else:
                url = ("https://auth.docker.io/token?service=registry.docker.io"
                       f"&scope=repository:{self.path}:pull")
            self._token = http(url)["token"]
        return {"Authorization": "Bearer " + self._token, "Accept": MANIFEST_ACCEPT}

    def tags(self):
        out, last = [], ""
        while True:
            url = f"https://{self.host}/v2/{self.path}/tags/list?n=1000"
            if last:
                url += "&last=" + last
            batch = http(url, self._headers()).get("tags") or []
            out += batch
            if len(batch) < 1000:
                return out
            last = batch[-1]

    def digest(self, tag):
        url = f"https://{self.host}/v2/{self.path}/manifests/{tag}"
        try:
            headers = http(url, self._headers(), "HEAD")
        except urllib.error.HTTPError:
            return None
        # header names come back in whatever case the registry uses
        return {k.lower(): v for k, v in headers.items()}.get("docker-content-digest")


def parse_compose(path):
    """Yield (service, image) for every third-party image: line."""
    service = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if m:
            service = m.group(1)
        m = re.match(r"^\s+image:\s*([^\s#]+)", line)
        if m:
            yield service, m.group(1)


def split_ref(image):
    """'repo:tag' / 'repo@sha256:..' -> (repo, tag, digest)."""
    if "@" in image:
        repo, digest = image.split("@", 1)
        return repo, None, digest
    if ":" in image.rsplit("/", 1)[-1]:
        repo, tag = image.rsplit(":", 1)
        return repo, tag, None
    return image, "latest", None


def version_key(name, pattern):
    m = re.match(pattern, name)
    if not m:
        return None
    return tuple(int(g) if g.isdigit() else 0 for g in m.groups())


def newest(tags, pattern):
    scored = [(version_key(t, pattern), t) for t in tags]
    scored = [s for s in scored if s[0] is not None]
    return max(scored)[1] if scored else None


def local_info(image):
    """(short id, created date) of the image docker has locally, or None."""
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", image, "--format",
             '{{.Id}} {{.Created}} {{with .Config.Labels}}{{index . "org.opencontainers.image.version"}}{{end}}'
             '|{{range .RepoDigests}}{{.}} {{end}}'],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    head, _, tail = out.stdout.partition("|")
    parts = head.split()
    digests = [p.split("@")[1] for p in tail.split() if "@" in p]
    return {"id": parts[0][7:19], "created": parts[1][:10],
            "version": parts[2] if len(parts) > 2 else None,
            "digest": digests[0] if digests else None}


def is_local_build(repo):
    return "/" not in repo and "." not in repo or repo.endswith(".local")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose", default="docker/docker-compose.yml")
    ap.add_argument("--no-docker", action="store_true", help="registry only")
    args = ap.parse_args()

    rows, seen = [], set()
    for service, image in parse_compose(args.compose):
        repo, tag, digest = split_ref(image)
        if image in seen:
            continue
        seen.add(image)
        if is_local_build(repo) and repo not in ("postgres", "redis", "nginx"):
            continue
        reg = Registry(repo)
        pattern = RULES.get(repo, GENERIC)
        try:
            tags = reg.tags()
        except Exception as exc:  # network / auth trouble: report, keep going
            rows.append((service, image, "?", "?", f"registry error: {exc}"))
            continue
        best = newest(tags, pattern)
        note = ""
        if tag and version_key(tag, pattern) is None:
            # floating tag: which concrete tag carries the same digest right now?
            cur = reg.digest(tag)
            if cur is None:
                rows.append((service, image, "-", best or "-", "floating, digest unavailable"))
                continue
            # only the newest few concrete tags can be the twin; one HEAD each
            candidates = sorted((t for t in tags if version_key(t, pattern) is not None),
                                key=lambda t: version_key(t, pattern), reverse=True)[:8]
            twins = [t for t in candidates if reg.digest(t) == cur]
            note = f"floating -> {twins[0]}" if twins else "floating, no concrete twin"
            if twins:
                best = twins[0] if best is None or version_key(twins[0], pattern) >= version_key(best, pattern) else best
        elif digest:
            cur = reg.digest(best) if best else None
            if cur is None:
                note = "digest pin, registry digest unavailable"
            else:
                note = "digest pin, registry moved on" if cur != digest else "digest pin, current"
        local = None if args.no_docker else local_info(image)
        local_s = f"{local['created']} ({local['id']})" if local else "-"
        if local and tag and local.get("digest") and version_key(tag, pattern) is None:
            if local["digest"] != cur:
                # name what is running so it can be pinned as-is: the OCI
                # version label when the image has one, else a short walk
                # newest-first (one HEAD per candidate, capped)
                # the label is only trusted when a real tag carries it (a base
                # image may leave its own version label behind, e.g. "24.04")
                label = local.get("version")
                running = next((t for t in tags if label and version_key(t, pattern) is not None
                                and (t == label or t.endswith(label))), None)
                if not running:
                    for t in sorted((t for t in tags if version_key(t, pattern) is not None),
                                    key=lambda t: version_key(t, pattern), reverse=True)[:40]:
                        if reg.digest(t) == local["digest"]:
                            running = t
                            break
                note += f"; LOCAL BEHIND, running {running or 'unknown build'}"
        rows.append((service, image, local_s, best or "-", note))

    w = [max(len(str(r[i])) for r in rows + [("service", "image", "local", "newest", "note")]) for i in range(5)]
    fmt = "  ".join("{:<%d}" % x for x in w)
    print(fmt.format("service", "image", "local", "newest", "note"))
    print(fmt.format(*["-" * x for x in w]))
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
