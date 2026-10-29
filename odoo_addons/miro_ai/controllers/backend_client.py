# -*- coding: utf-8 -*-
"""HTTP calls to the single MIRO AI backend URL configured in Odoo."""
import logging

import requests

_logger = logging.getLogger(__name__)


class BackendError(Exception):
    pass


class BackendUnreachable(BackendError):
    pass


class BackendTimeout(BackendError):
    pass


class BackendInvalidResponse(BackendError):
    pass


def response_json_object(response):
    try:
        body = response.json()
    except ValueError as error:
        raise BackendInvalidResponse("Backend returned invalid JSON") from error
    if not isinstance(body, dict):
        raise BackendInvalidResponse("Backend response must be a JSON object")
    return body


def job_response_object(response):
    job = response_json_object(response)
    if (
        not isinstance(job.get("question"), str)
        or type(job.get("elapsed_ms")) is not int
        or job.get("elapsed_ms") < 0
        or job.get("status") not in {"pending", "done", "error"}
    ):
        raise BackendInvalidResponse("Backend returned an invalid job response")
    if job.get("status") == "done":
        result = job.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
            raise BackendInvalidResponse("Backend returned an invalid completed job")
        if not isinstance(result.get("sources", []), list):
            raise BackendInvalidResponse("Backend returned invalid answer sources")
    return job


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
