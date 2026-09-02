"""mora02_core.agents — talking to OpenClaw agents from inside a container.

Kept import-light on purpose (see mora02_core.llm): nothing here should drag a
cloud SDK into a process that only wants to name a session.

  cli     one turn, the gateway's agent list, its model list
  store   the roster as files: read by looking, written by the builder
  deploy  render the roster into the gateway volume (check or apply)
"""

from mora02_core.agents.cli import AgentError, ask, listing, models, session_key

__all__ = ["AgentError", "ask", "listing", "models", "session_key"]
