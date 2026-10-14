"""Embedding functions and provider resolver for ChromaDB vectorstore."""

import logging
import os
import time
from typing import List, Optional
import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from core.llm.local_only import assert_local_endpoint

logger = logging.getLogger(__name__)

class LocalSentenceTransformerEmbeddingFunction(EmbeddingFunction):
    """Local embedding function via sentence-transformers.

    Supports any HuggingFace model (e.g. BAAI/bge-m3, all-mpnet-base-v2) or a local
    weights directory path configured via EMBEDDING_MODEL. Requires modern CPU with AVX2 or GPU.
    """

    _models = {}

    def __init__(self, model_name: Optional[str] = None):
        from config.settings import EMBEDDING_MODEL_NAME
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        if self.model_name not in LocalSentenceTransformerEmbeddingFunction._models:
            os.environ.setdefault("OMP_NUM_THREADS", "2")
            os.environ.setdefault("MKL_NUM_THREADS", "2")

            from sentence_transformers import SentenceTransformer
            import torch

            torch.set_num_threads(2)
            logger.info("Loading local sentence-transformers model '%s'...", self.model_name)
            LocalSentenceTransformerEmbeddingFunction._models[self.model_name] = SentenceTransformer(
                self.model_name
            )

    def name(self) -> str:
        return f"{self.model_name}-local"

    def __call__(self, input: Documents) -> Embeddings:
        model = LocalSentenceTransformerEmbeddingFunction._models[self.model_name]
        return model.encode(list(input), normalize_embeddings=True).tolist()


class LocalServerEmbeddingFunction(EmbeddingFunction):
    """HTTP-based embedding client for local/remote OpenAI-compatible or Ollama servers.

    Zero local CPU vector computation: perfectly suited for non-AVX/AVX2 host machines
    while keeping embeddings 100% private and self-hosted.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "all-minilm:latest",
        api_key: str = "ollama",
        timeout: Optional[float] = None,
        max_retries: int = 3,
        batch_size: int = 16,
    ):
        assert_local_endpoint(base_url, "Embedding")
        clean_url = base_url.rstrip("/")
        if clean_url.endswith("/v1"):
            self.endpoint = f"{clean_url}/embeddings"
        elif "/v1" not in clean_url:
            self.endpoint = f"{clean_url}/v1/embeddings"
        else:
            self.endpoint = f"{clean_url}/embeddings"

        self.model = model
        self.api_key = api_key or "ollama"
        self.timeout = float(timeout if timeout is not None else os.environ.get("LOCAL_EMBEDDING_TIMEOUT", "30"))
        self.max_retries = max(1, int(max_retries))
        self.batch_size = max(1, int(batch_size))

    def name(self) -> str:
        return f"local-server-{self.model}"

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        payload = {"model": self.model, "input": texts}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                if attempt == self.max_retries:
                    logger.error(
                        "Embedding server unreachable after %d attempts (model=%s, endpoint=%s): %s",
                        self.max_retries, self.model, self.endpoint, exc,
                    )
                    raise
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "Embedding request failed (attempt %d/%d): %s -- retrying in %ds",
                    attempt, self.max_retries, exc, delay,
                )
                time.sleep(delay)
        resp.raise_for_status()
        data = resp.json()

        # Format 1: OpenAI standard {"data": [{"embedding": [...], "index": 0}, ...]}
        if "data" in data and isinstance(data["data"], list):
            sorted_items = sorted(data["data"], key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in sorted_items]

        # Format 2: Ollama native {"embeddings": [[...], ...]}
        if "embeddings" in data:
            return data["embeddings"]

        raise ValueError(f"Unexpected response format from embedding server: {list(data.keys())}")

    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        if not texts:
            return []

        embeddings: List[List[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            embeddings.extend(self._embed_batch(texts[offset:offset + self.batch_size]))
        return embeddings


def resolve_embedding_function(
    backend: Optional[str] = None,
    embedding_model: Optional[str] = None,
) -> Optional[EmbeddingFunction]:
    """Resolve and instantiate embedding function based on EMBEDDING_BACKEND.

    Supported options:
    - 'local_light' (default): Returns None for ChromaDB default ONNX all-MiniLM-L6-v2
      (384 dimensions, safe on non-AVX machines).
    - 'local_server' / 'ollama' / 'openai_compatible': Calls local HTTP embedding server.
    - 'local': Local sentence-transformers model (requires AVX2).
    """
    resolved_backend = (backend or os.environ.get("EMBEDDING_BACKEND", "local_light")).lower().strip()

    if resolved_backend == "local_light":
        logger.info(
            "EMBEDDING_BACKEND=local_light: using ChromaDB default ONNX all-MiniLM-L6-v2 "
            "(384 dims, fast on non-AVX machines)."
        )
        return None

    if resolved_backend in ("local_server", "ollama", "openai_compatible", "vllm", "tei"):
        from config.settings import (
            LOCAL_EMBEDDING_BASE_URL,
            LOCAL_EMBEDDING_MODEL,
            LOCAL_EMBEDDING_API_KEY,
        )
        return LocalServerEmbeddingFunction(
            base_url=LOCAL_EMBEDDING_BASE_URL,
            model=LOCAL_EMBEDDING_MODEL,
            api_key=LOCAL_EMBEDDING_API_KEY,
        )

    if resolved_backend == "local":
        try:
            from config.settings import EMBEDDING_MODEL_NAME
            target_model = embedding_model or os.getenv("EMBEDDING_MODEL") or EMBEDDING_MODEL_NAME
            return LocalSentenceTransformerEmbeddingFunction(model_name=target_model)
        except Exception as e:
            logger.error("Failed to load local embedding model: %s", e)
            raise RuntimeError(
                f"Cannot load local embedding model '{embedding_model or os.getenv('EMBEDDING_MODEL')}'. Stopping rather than silently falling back."
            ) from e

    raise ValueError(f"Unknown EMBEDDING_BACKEND: {resolved_backend!r}")
