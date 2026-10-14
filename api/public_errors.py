"""Classify unexpected API failures without exposing their private details."""

import errno
from xmlrpc.client import ProtocolError


_NETWORK_ERRNOS = frozenset({
    errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT,
    errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EPIPE,
})


def public_error_details(error: BaseException) -> tuple[int, str]:
    """Recognize typed transport failures through an exception's causal chain."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionError, TimeoutError)):
            return 503, "Service temporarily unavailable."
        if isinstance(current, OSError) and current.errno in _NETWORK_ERRNOS:
            return 503, "Service temporarily unavailable."
        if isinstance(current, ProtocolError) and (current.errcode == 429 or current.errcode >= 500):
            return 503, "Service temporarily unavailable."
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return 500, "Internal server error."
