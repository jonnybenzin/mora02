"""mora02_core.publish — outbound publishing to external channels (LinkedIn, …)."""

from mora02_core.publish.linkedin import LinkedInError, post_to_linkedin

__all__ = ["post_to_linkedin", "LinkedInError"]
