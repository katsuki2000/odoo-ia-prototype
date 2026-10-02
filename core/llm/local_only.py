"""Local-only guard: refuses cloud providers and non-allow-listed inference endpoints."""

from urllib.parse import urlparse

from config.settings import LOCAL_ALLOWED_HOSTS, LOCAL_ONLY

CLOUD_PROVIDERS = frozenset({"groq", "openrouter", "nomic_api"})


class ExternalEndpointError(ValueError):
    """Raised when LOCAL_ONLY forbids the requested provider or endpoint."""


def assert_local_provider(provider: str) -> None:
    if LOCAL_ONLY and provider in CLOUD_PROVIDERS:
        raise ExternalEndpointError(
            f"Provider {provider!r} is a cloud service and LOCAL_ONLY is enabled. "
            f"Use LLM_PROVIDER=local, or set LOCAL_ONLY=false in .env."
        )


def assert_local_endpoint(url: str, purpose: str) -> None:
    if not LOCAL_ONLY:
        return
    host = (urlparse(url).hostname or "").lower()
    if host not in LOCAL_ALLOWED_HOSTS:
        raise ExternalEndpointError(
            f"{purpose} endpoint {url!r} (host {host or 'unknown'!r}) is not local and LOCAL_ONLY is "
            f"enabled. Add the host to LOCAL_ALLOWED_HOSTS in .env to allow a trusted server."
        )


__all__ = [
    "CLOUD_PROVIDERS",
    "ExternalEndpointError",
    "assert_local_provider",
    "assert_local_endpoint",
]
