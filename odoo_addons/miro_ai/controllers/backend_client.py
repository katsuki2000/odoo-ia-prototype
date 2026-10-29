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


def _send(verb, api_url, path, headers, payload, timeout):
    send = getattr(requests, verb)
    try:
        _logger.info("MIRO AI -> %s%s", api_url, path)
        return send(f"{api_url}{path}", headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout as error:
        raise BackendTimeout(f"{api_url} did not answer within {timeout} s") from error
    except requests.exceptions.ConnectionError as error:
        _logger.warning("MIRO AI: %s unreachable: %s", api_url, error)
        raise BackendUnreachable("Backend unreachable") from error


def post_to_backend(api_url, path, headers, payload, timeout):
    return _send("post", api_url, path, headers, payload, timeout)


def get_from_backend(api_url, path, headers, timeout):
    return _send("get", api_url, path, headers, None, timeout)
