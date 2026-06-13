"""Runner registry + env-driven default selection.

``MORA02_PIPELINE_RUNNER`` picks the active runner (default ``lobster``).
``register_runner`` lets a future native mora02_core step runner (the Nordstern)
plug in without touching caller code.
"""

from __future__ import annotations

import os

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.base import PipelineRunner
from mora02_core.pipeline.lobster import LobsterRunner

_RUNNERS: dict[str, PipelineRunner] = {}


def register_runner(runner: PipelineRunner) -> None:
    """Register (or replace) a runner under its ``.name``."""
    _RUNNERS[runner.name] = runner


def get_runner(name: str | None = None) -> PipelineRunner:
    """Return the named runner, or the env default (``MORA02_PIPELINE_RUNNER``)."""
    key = name or os.environ.get("MORA02_PIPELINE_RUNNER", "lobster")
    try:
        return _RUNNERS[key]
    except KeyError:
        known = ", ".join(sorted(_RUNNERS)) or "(none)"
        raise PipelineError(
            f"unknown pipeline runner {key!r}; registered: {known}"
        ) from None


# Built-in runner. Constructs cheaply (config resolved lazily on call), so
# registering an instance at import time is safe even with no gateway running.
register_runner(LobsterRunner())
