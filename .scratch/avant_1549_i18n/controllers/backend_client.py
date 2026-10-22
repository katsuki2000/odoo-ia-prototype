# -*- coding: utf-8 -*-
"""HTTP call from the Odoo controller to the MIRO AI backend.

The next candidate URL is tried only when the server cannot be reached. Once a
server accepted the request, it is never sent again: a read timeout means the
backend is still working, and a second call would run the same question twice.
"""
import logging

import requests

from odoo.addons.miro_ai.models.miro_ai_settings import DEFAULT_API_URL

_logger = logging.getLogger(__name__)

_FALLBACK_URLS = {"http://miro_rag:8000": DEFAULT_API_URL, DEFAULT_API_URL: "http://localhost:8000"}


class BackendError(Exception):
    pass


class BackendUnreachable(BackendError):
    pass


class BackendTimeout(BackendError):
    pass


def candidate_urls_for(api_url):
    """The configured URL, then the fallback for the usual docker and local setups."""
    fallback = _FALLBACK_URLS.get(api_url)
    return [api_url, fallback] if fallback else [api_url]


def post_with_failover(candidate_urls, path, headers, payload, timeout):
    """Return (response, url_used) from the first candidate that accepts the request."""
    last_error = None
    for url in candidate_urls:
        try:
            _logger.info("MIRO AI -> %s%s", url, path)
            return requests.post(f"{url}{path}", headers=headers, json=payload, timeout=timeout), url
        except requests.exceptions.ConnectionError as error:
            _logger.warning("MIRO AI: %s unreachable: %s", url, error)
            last_error = error
        except requests.exceptions.Timeout as error:
            raise BackendTimeout(f"{url} did not answer within {timeout} s") from error
    raise BackendUnreachable("Backend unreachable") from last_error
