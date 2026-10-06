"""Refuse to start a protocol run while a model backend does not answer."""

from __future__ import annotations

from typing import Callable, Mapping, Optional

PROBE_TEXT = "ping"
PROBE_MAX_TOKENS = 8


class BackendUnavailable(RuntimeError):
    pass


def probe_llm() -> None:
    from core.llm.llm_client import get_chat_llm

    get_chat_llm(max_tokens=PROBE_MAX_TOKENS).invoke(PROBE_TEXT)


def probe_embeddings() -> None:
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function

    embed = resolve_embedding_function()
    if embed is not None:
        embed([PROBE_TEXT])


DEFAULT_PROBES = {"llm": probe_llm, "embeddings": probe_embeddings}


def require_backends(probes: Optional[Mapping[str, Callable[[], None]]] = None) -> None:
    failures = []
    for name, probe in (DEFAULT_PROBES if probes is None else probes).items():
        try:
            probe()
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}: {error}")
    if failures:
        raise BackendUnavailable("; ".join(failures))
