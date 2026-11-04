"""Resolve the request language from an explicit tag or the Accept-Language header."""

import re

LANGUAGE_TAG = re.compile(r'[A-Za-z]{2,8}(?:_[A-Za-z0-9]{1,8})*')


def _normalize_language_tag(value: str | None) -> str | None:
    normalized = (value or '').strip().replace('-', '_')
    return normalized if LANGUAGE_TAG.fullmatch(normalized) else None


def _quality(parameters: list[str]) -> float:
    for parameter in parameters:
        if parameter.startswith('q='):
            try:
                return float(parameter[2:])
            except ValueError:
                return 0.0
    return 1.0


def request_language(explicit: str | None, accept_language: str | None) -> str | None:
    """The explicit tag, else the best-weighted Accept-Language tag (first listed wins ties)."""
    language = _normalize_language_tag(explicit)
    if language:
        return language
    candidates = []
    for position, item in enumerate((accept_language or '').split(',')):
        tag, *parameters = (part.strip() for part in item.split(';'))
        language, quality = _normalize_language_tag(tag), _quality(parameters)
        if language and quality > 0:
            candidates.append((-quality, position, language))
    return min(candidates)[2] if candidates else None
