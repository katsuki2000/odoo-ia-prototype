"""Embedding functions and provider resolver for ChromaDB vectorstore."""

import os
import time
from typing import List, Optional
import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

SERVER_EMBEDDING_BACKENDS = frozenset({'local_server', 'ollama', 'openai_compatible', 'vllm'})


class LocalServerEmbeddingFunction(EmbeddingFunction):
    """HTTP embedding client for configured OpenAI-compatible servers."""
    def __init__(self, base_url: str, model: str, api_key: str = 'ollama', timeout: Optional[float] = None, max_retries: int = 3, batch_size: int = 16):
        cleanUrl = base_url.rstrip('/')
        self.endpoint = f'{cleanUrl}/embeddings' if '/v1' in cleanUrl else f'{cleanUrl}/v1/embeddings'
        self.model = model
        self.api_key = api_key or 'ollama'
        self.timeout = float(timeout if timeout is not None else os.environ.get('EMBEDDING_TIMEOUT', '30'))
        self.max_retries = max(1, int(max_retries))
        self.batch_size = max(1, int(batch_size))

    def name(self) -> str:
        return f'local-server-{self.model}'

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        payload = {'model': self.model, 'input': texts}
        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'}
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
        if isinstance(data.get('data'), list):
            return [item['embedding'] for item in sorted(data['data'], key=lambda item: item.get('index', 0))]
        if 'embeddings' in data:
            return data['embeddings']
        raise ValueError('Unexpected response format from embedding server.')

    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        embeddings = []
        for offset in range(0, len(texts), self.batch_size):
            embeddings.extend(self._embed_batch(texts[offset:offset + self.batch_size]))
        return embeddings


def resolve_embedding_function(backend: Optional[str] = None, embedding_model: Optional[str] = None) -> EmbeddingFunction:
    """Resolve a provider; explicit model overrides its configured backend default."""
    from config.settings import DEFAULT_EMBEDDING_BACKEND
    backend = (backend or os.environ.get('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND)).lower().strip()
    if backend in SERVER_EMBEDDING_BACKENDS:
        from config.settings import EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY, require_inference_server
        return LocalServerEmbeddingFunction(base_url=require_inference_server(EMBEDDING_BASE_URL),
                                            model=embedding_model or EMBEDDING_MODEL,
                                            api_key=EMBEDDING_API_KEY)
    raise ValueError(f'Unknown EMBEDDING_BACKEND: {backend!r}')
