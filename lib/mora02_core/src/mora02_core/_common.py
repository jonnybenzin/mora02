"""Shared utilities: structured logger + HTTP client with retry."""

import asyncio
import logging
import os
import sys
from typing import Any

import httpx


def get_logger(name: str) -> logging.Logger:
    """Get a logger configured for stdout. Idempotent (won't re-add handlers)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("MORA02_LOG_LEVEL", "INFO").upper())
    return logger


HTTP_TIMEOUT = float(os.environ.get("MORA02_HTTP_TIMEOUT", "30.0"))


def http_client(timeout: float = HTTP_TIMEOUT) -> httpx.AsyncClient:
    """Return a pre-configured httpx.AsyncClient. Caller closes."""
    return httpx.AsyncClient(timeout=timeout)


async def request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP request with exponential-backoff retry on 5xx and transport errors.

    4xx responses are returned as-is (not retried).
    """
    log = get_logger("mora02_core._common")
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    async with http_client() as client:
        for attempt in range(retries):
            try:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code < 500:
                    return resp
                log.warning(
                    "%s %s returned %d, attempt %d/%d",
                    method, url, resp.status_code, attempt + 1, retries,
                )
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                log.warning(
                    "%s %s transport error: %r, attempt %d/%d",
                    method, url, e, attempt + 1, retries,
                )
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (2 ** attempt))
        if last_exc:
            raise last_exc
        assert resp is not None
        return resp
