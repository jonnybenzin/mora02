"""Notify-specific exceptions."""


class NotifyError(Exception):
    """Raised when an outbound notification fails to deliver.

    Carries a human-readable message. Callers (Pilot, Skills, scripts)
    that go through ``mora02_core.notify`` catch this rather than a transport-
    specific error, which keeps the delivery backend swappable.
    """
