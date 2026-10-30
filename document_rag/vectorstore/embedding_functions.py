"""Embedding client and resolver for the documentary vector store."""

from __future__ import annotations

import time
from typing import Optional

import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from config import settings


class OllamaEmbeddingFunction(EmbeddingFunction):
    """HTTP embedding client for an OpenAI-compatible inference endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "ollama",
        timeout: Optional[float] = None,
        max_retries: int = 3,
        batch_size: int = 16,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or "ollama"
        self.timeout = float(timeout if timeout is not None else settings.EMBEDDING_TIMEOUT)
        self.max_retries = max(1, int(max_retries))
        self.batch_size = max(1, int(batch_size))

    @property
    def endpoint(self) -> str:
        base_url = settings.require_inference_server(self.base_url).rstrip("/")
        return f"{base_url}/embeddings" if base_url.endswith("/v1") else f"{base_url}/v1/embeddings"

    def name(self) -> str:
        return f"local-server-{self.model}"

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == self.max_retries:
                    raise
                time.sleep(2 ** (attempt - 1))
        response.raise_for_status()
        data = response.json()
        if isinstance(data.get("data"), list):
            return [item["embedding"] for item in sorted(data["data"], key=lambda item: item.get("index", 0))]
        if "embeddings" in data:
            return data["embeddings"]
        raise ValueError("Unexpected response format from embedding server.")

    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        embeddings = []
        for offset in range(0, len(texts), self.batch_size):
            embeddings.extend(self._embed_batch(texts[offset:offset + self.batch_size]))
        return embeddings


def resolve_embedding_function(embedding_model: Optional[str] = None) -> EmbeddingFunction:
    """Create the configured embedding client without connecting to the inference server."""
    return OllamaEmbeddingFunction(
        base_url=settings.EMBEDDING_BASE_URL,
        model=embedding_model or settings.EMBEDDING_MODEL,
        api_key=settings.EMBEDDING_API_KEY,
    )
