"""Media-specific exceptions."""


class MediaError(Exception):
    """Raised when a media operation (gif/text-frame/clip) fails.

    Carries a human-readable message that the script-runner HTTP wrapper
    forwards as ``{"success": false, "error": str(e)}``.
    """
