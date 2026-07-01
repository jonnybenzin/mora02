"""mora02_core.publish.linkedin — publish an image/text post to LinkedIn (UGC API).

The three-call LinkedIn v2 dance, reused from the ActivePieces SM_publish_linkedIn
flow but as a clean library function: register an upload slot, PUT the image bytes,
then create the ugcPost. Pure over its inputs (token/author/text/bytes) so it stays
testable and the pipeline op is a thin wrapper. Credentials are the caller's concern
(the op reads MORA02_LINKEDIN_TOKEN / MORA02_LINKEDIN_AUTHOR from the environment).

Note vs. the AP flow: that flow sent a doubled ``Authorization: Bearer Bearer <t>``
on the binary PUT (a bug that happened to work because the upload URL is pre-signed);
this sends a correct single ``Bearer <t>``.
"""

from __future__ import annotations

from typing import Optional

import httpx

from mora02_core._common import get_logger

_log = get_logger("mora02_core.publish.linkedin")

_API = "https://api.linkedin.com/v2"
_RESTLI = {"X-Restli-Protocol-Version": "2.0.0"}


class LinkedInError(Exception):
    """A LinkedIn publish call failed (non-2xx or unexpected response)."""


async def post_to_linkedin(
    *,
    token: str,
    author: str,
    text: str,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/png",
    visibility: str = "PUBLIC",
    timeout: float = 60.0,
) -> dict:
    """Publish a post to LinkedIn. With ``image_bytes`` → an image share, else text-only.

    Returns ``{"post_id": "<urn>", "post_url": ".../feed/update/<urn>"}``. Raises
    :class:`LinkedInError` on any failed call (HTTP 401 usually = expired token).
    """
    if not token:
        raise LinkedInError("no LinkedIn token (set MORA02_LINKEDIN_TOKEN)")
    if not author:
        raise LinkedInError("no LinkedIn author URN (set MORA02_LINKEDIN_AUTHOR)")
    auth = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        asset_urn = None
        if image_bytes:
            # 1) register an upload slot for a feed-share image
            reg = await client.post(
                f"{_API}/assets?action=registerUpload",
                headers={**auth, "Content-Type": "application/json", **_RESTLI},
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": author,
                        "serviceRelationships": [
                            {"relationshipType": "OWNER",
                             "identifier": "urn:li:userGeneratedContent"}
                        ],
                    }
                },
            )
            if reg.status_code // 100 != 2:
                raise LinkedInError(
                    f"registerUpload HTTP {reg.status_code}: {reg.text[:300]}"
                )
            value = reg.json()["value"]
            upload_url = value["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset_urn = value["asset"]

            # 2) PUT the image bytes to the pre-authorized upload URL (single Bearer)
            up = await client.put(
                upload_url,
                headers={**auth, "Content-Type": image_mime},
                content=image_bytes,
            )
            if up.status_code // 100 != 2:
                raise LinkedInError(
                    f"image upload HTTP {up.status_code}: {up.text[:300]}"
                )

        # 3) create the post
        share: dict = {
            "shareCommentary": {"text": text or ""},
            "shareMediaCategory": "IMAGE" if asset_urn else "NONE",
        }
        if asset_urn:
            share["media"] = [{"status": "READY", "media": asset_urn}]
        post = await client.post(
            f"{_API}/ugcPosts",
            headers={**auth, "Content-Type": "application/json", **_RESTLI},
            json={
                "author": author,
                "lifecycleState": "PUBLISHED",
                "specificContent": {"com.linkedin.ugc.ShareContent": share},
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
            },
        )
        if post.status_code // 100 != 2:
            raise LinkedInError(f"ugcPosts HTTP {post.status_code}: {post.text[:300]}")
        # ugcPosts returns the URN in the body ``id`` (what the AP flow used); fall
        # back to the x-restli-id header if the body carries none.
        post_id = None
        try:
            post_id = post.json().get("id")
        except ValueError:
            pass
        post_id = post_id or post.headers.get("x-restli-id")
        if not post_id:
            raise LinkedInError(f"ugcPosts returned no post id: {post.text[:300]}")
        _log.info("linkedin post created: %s", post_id)
        return {
            "post_id": post_id,
            "post_url": f"https://www.linkedin.com/feed/update/{post_id}",
        }
