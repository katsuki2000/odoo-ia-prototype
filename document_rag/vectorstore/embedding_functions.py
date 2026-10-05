"""Embedding functions and provider resolver for ChromaDB vectorstore."""

import logging
import os
from typing import Any, List, Optional
import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from core.llm.local_only import assert_local_endpoint

logger = logging.getLogger(__name__)


class CustomNomicEmbeddingFunction(EmbeddingFunction):
    """Cloud-based embedding function for Nomic Atlas REST API."""

    def __init__(
        self,
        model: str = "nomic-embed-text-v1.5",
        api_key: Optional[str] = None,
        task_type: str = "search_document",
    ):
        self.model = model
        self.api_key = api_key
        self.task_type = task_type
        self.endpoint = "https://api-atlas.nomic.ai/v1/embedding/text"

    def name(self) -> str:
        return self.model

    def __call__(self, input: Documents) -> Embeddings:
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "texts": list(input),
                "model": self.model,
                "task_type": self.task_type,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"]


class LocalSentenceTransformerEmbeddingFunction(EmbeddingFunction):
    """Local embedding function via sentence-transformers.

    Supports any HuggingFace model (e.g. nomic-ai/nomic-embed-text-v1.5, BAAI/bge-m3,
    all-mpnet-base-v2) or a local weights directory path configured via EMBEDDING_MODEL.
    Requires modern CPU with AVX2 or GPU.
    """

    _models = {}

    def __init__(self, model_name: Optional[str] = None, task_type: str = "search_document"):
        from config.settings import EMBEDDING_MODEL_NAME
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        self.task_type = task_type
        if self.model_name not in LocalSentenceTransformerEmbeddingFunction._models:
            os.environ.setdefault("OMP_NUM_THREADS", "2")
            os.environ.setdefault("MKL_NUM_THREADS", "2")

            from sentence_transformers import SentenceTransformer
            import torch

            torch.set_num_threads(2)
            logger.info("Loading local sentence-transformers model '%s'...", self.model_name)
            trust_remote = "nomic" in self.model_name.lower()
            LocalSentenceTransformerEmbeddingFunction._models[self.model_name] = SentenceTransformer(
                self.model_name, trust_remote_code=trust_remote
            )

    def name(self) -> str:
        return f"{self.model_name}-local"

    def __call__(self, input: Documents) -> Embeddings:
        model = LocalSentenceTransformerEmbeddingFunction._models[self.model_name]
        texts = list(input)
        if "nomic" in self.model_name.lower():
            prefix = "search_query: " if self.task_type == "search_query" else "search_document: "
            texts = [f"{prefix}{text}" for text in texts]
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()


LocalNomicEmbeddingFunction = LocalSentenceTransformerEmbeddingFunction


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
        timeout: float = 30.0,
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
        self.timeout = timeout

    def name(self) -> str:
        return f"local-server-{self.model}"

    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        if not texts:
            return []

        payload = {"model": self.model, "input": texts}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
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


def resolve_embedding_function(
    backend: Optional[str] = None,
    embedding_model: str = "nomic-embed-text-v1.5",
) -> Optional[EmbeddingFunction]:
    """Resolve and instantiate embedding function based on EMBEDDING_BACKEND.

    Supported options:
    - 'local_light' (default): Returns None for ChromaDB default ONNX all-MiniLM-L6-v2
      (384 dimensions, safe on non-AVX machines).
    - 'local_server' / 'ollama' / 'openai_compatible': Calls local HTTP embedding server.
    - 'nomic_api': Calls cloud Nomic Atlas REST API.
    - 'local': Local PyTorch nomic-embed-text-v1.5 (requires AVX2).
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

    if resolved_backend == "nomic_api":
        assert_local_provider("nomic_api")
        nomic_api_key = os.environ.get("NOMIC_API_KEY")
        if nomic_api_key:
            return CustomNomicEmbeddingFunction(
                model=embedding_model,
                api_key=nomic_api_key,
            )
        logger.warning("EMBEDDING_BACKEND=nomic_api but NOMIC_API_KEY is missing. Falling back to local_light.")
        return None

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
