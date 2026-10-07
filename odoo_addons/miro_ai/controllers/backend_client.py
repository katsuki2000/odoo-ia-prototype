# -*- coding: utf-8 -*-
"""HTTP call from the Odoo controller to the MIRO AI backend.

The next candidate URL is tried only when the server cannot be reached. Once a
server accepted the request, it is never sent again: a read timeout means the
backend is still working, and a second call would run the same question twice.
"""
import logging

import requests

_logger = logging.getLogger(__name__)


class BackendError(Exception):
    pass


class BackendUnreachable(BackendError):
    pass


class BackendTimeout(BackendError):
    pass


def post_with_failover(candidate_urls, path, headers, payload, timeout):
    """Return (response, url_used) from the first candidate that accepts the request."""
    last_error = None
    for url in candidate_urls:
        try:
            _logger.info("MIRO AI -> %s%s", url, path)
            return requests.post(f"{url}{path}", headers=headers, json=payload, timeout=timeout), url
        except requests.exceptions.ConnectionError as error:
            _logger.warning("MIRO AI: %s injoignable: %s", url, error)
            last_error = error
        except requests.exceptions.Timeout as error:
            raise BackendTimeout(f"{url} n'a pas répondu en {timeout} s") from error
    raise BackendUnreachable("Serveur RAG inaccessible") from last_error
