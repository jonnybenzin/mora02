"""mora02_core.web — searching and reading the open web.

Two callers, one implementation. The pipeline op ``web.search`` reached SearXNG
from inside script-runner's main module; the agent layer needs the same reach
from its MCP surface, and that module is imported BY main, so it cannot import
back. Rather than a second copy or an HTTP call a service makes to itself, the
work moves here — which is where ADR-011 says it belongs anyway: logic once,
front ends interchangeable.

Search is deliberately LOCAL. The query goes to the SearXNG instance in this
stack, so it never leaves the house, needs no API key, and returns results that
carry their URL — which means a source citation is a property of the data rather
than something a model has to remember to add. OpenClaw's own web_search tool
would have meant an external provider plus a key for both of those.

Fetching, unavoidably, is not local: reading a page means asking its server.

Config (env):
  SEARXNG_URL   the local metasearch engine, default ``http://searxng:8080``
"""

from mora02_core.web.client import WebError, fetch, search, search_many

__all__ = ["WebError", "fetch", "search", "search_many"]
