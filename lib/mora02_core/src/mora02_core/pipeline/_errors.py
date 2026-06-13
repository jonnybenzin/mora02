"""Pipeline-specific exceptions."""


class PipelineError(Exception):
    """Raised when a pipeline run/resume cannot be carried out at the transport level.

    This is for *infrastructure* failures — the runner binary is unreachable, the
    docker exec fails, or the output is unparseable. A workflow that runs but ends
    in a runtime error is NOT this: that comes back as a ``PipelineResult`` with
    ``ok=False`` and an ``error`` payload, so callers can distinguish "could not
    talk to the runner" from "the workflow itself failed".
    """
