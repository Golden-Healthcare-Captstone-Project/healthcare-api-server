import logging
import time

import requests

logger = logging.getLogger(__name__)

GRAPH_API_TIMEOUT = 6  # seconds
RATE_LIMIT_CODES = {4, 17, 32, 613}
MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 1


class MetaRateLimitedError(Exception):
    """Raised when Meta signals throttling and the retry is exhausted."""


class MetaGraphAPIError(Exception):
    """Raised for non-rate-limit Graph API errors (bad token, permissions, network failure, etc.)."""

    def __init__(self, message, status_code=None, meta_error_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.meta_error_code = meta_error_code


def _is_rate_limited(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return error.get("code") in RATE_LIMIT_CODES or error.get("is_transient") is True


def _meta_error_code(response: requests.Response):
    try:
        return response.json().get("error", {}).get("code")
    except ValueError:
        return None


def graph_get(url: str, params: dict) -> dict:
    """
    Wraps a Graph API GET call: adds a timeout, retries once on a
    rate-limit/transient signal, and raises normalized exceptions
    (MetaRateLimitedError / MetaGraphAPIError) on failure.
    Never logs token values.
    """
    attempt = 0
    while True:
        try:
            response = requests.get(url, params=params, timeout=GRAPH_API_TIMEOUT)
        except requests.RequestException as e:
            logger.error("Graph API request failed for %s: %s", url, type(e).__name__)
            raise MetaGraphAPIError(f"Network error calling Meta: {type(e).__name__}") from e

        if response.ok:
            return response.json()

        if _is_rate_limited(response):
            error_code = _meta_error_code(response)
            logger.warning(
                "Meta rate limit hit for %s: status=%s error_code=%s attempt=%s",
                url, response.status_code, error_code, attempt,
            )
            if attempt < MAX_RETRIES:
                attempt += 1
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise MetaRateLimitedError("Meta Graph API rate limit exceeded")

        error_code = _meta_error_code(response)
        logger.error(
            "Graph API error for %s: status=%s error_code=%s",
            url, response.status_code, error_code,
        )
        raise MetaGraphAPIError(
            f"Meta Graph API error (status {response.status_code})",
            status_code=response.status_code,
            meta_error_code=error_code,
        )
