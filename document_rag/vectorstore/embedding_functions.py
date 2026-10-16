"""Embedding functions and provider resolver for ChromaDB vectorstore."""

import logging
import os
import time
from typing import List, Optional
import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from core.llm.local_only import assert_local_endpoint

logger = logging.getLogger(__name__)
SERVER_EMBEDDING_BACKENDS = frozenset({'local_server', 'ollama', 'openai_compatible', 'vllm', 'tei'})


class LocalSentenceTransformerEmbeddingFunction(EmbeddingFunction):
    """Local embedding function via sentence-transformers."""
    _models = {}

    def __init__(self, model_name: Optional[str] = None):
        from config.settings import EMBEDDING_MODEL_NAME
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        if self.model_name not in self._models:
            os.environ.setdefault('OMP_NUM_THREADS', '2')
            os.environ.setdefault('MKL_NUM_THREADS', '2')
            from sentence_transformers import SentenceTransformer
            import torch
            torch.set_num_threads(2)
            self._models[self.model_name] = SentenceTransformer(self.model_name)

    def name(self) -> str:
        return f'{self.model_name}-local'

    def __call__(self, input: Documents) -> Embeddings:
        return self._models[self.model_name].encode(list(input), normalize_embeddings=True).tolist()


class LocalServerEmbeddingFunction(EmbeddingFunction):
    """HTTP embedding client for configured OpenAI-compatible servers."""
    def __init__(self, base_url: str = 'http://localhost:11434/v1', model: str = 'all-minilm:latest',
                 api_key: str = 'ollama', timeout: Optional[float] = None, max_retries: int = 3, batch_size: int = 16):
        assert_local_endpoint(base_url, 'Embedding')
        cleanUrl = base_url.rstrip('/')
        self.endpoint = f'{cleanUrl}/embeddings' if '/v1' in cleanUrl else f'{cleanUrl}/v1/embeddings'
        self.model = model
        self.api_key = api_key or 'ollama'
        self.timeout = float(timeout if timeout is not None else os.environ.get('LOCAL_EMBEDDING_TIMEOUT', '30'))
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


def resolve_embedding_function(backend: Optional[str] = None, embedding_model: Optional[str] = None) -> Optional[EmbeddingFunction]:
    """Resolve a provider; explicit model overrides its configured backend default."""
    from config.settings import DEFAULT_EMBEDDING_BACKEND
    backend = (backend or os.environ.get('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND)).lower().strip()
    if backend == 'local_light':
        return None
    if backend in SERVER_EMBEDDING_BACKENDS:
        from config.settings import LOCAL_EMBEDDING_BASE_URL, LOCAL_EMBEDDING_MODEL, LOCAL_EMBEDDING_API_KEY
        return LocalServerEmbeddingFunction(base_url=LOCAL_EMBEDDING_BASE_URL,
                                            model=embedding_model or LOCAL_EMBEDDING_MODEL,
                                            api_key=LOCAL_EMBEDDING_API_KEY)
    if backend == 'local':
        from config.settings import EMBEDDING_MODEL_NAME
        model = embedding_model or os.getenv('EMBEDDING_MODEL') or EMBEDDING_MODEL_NAME
        try:
            return LocalSentenceTransformerEmbeddingFunction(model_name=model)
        except Exception as error:
            raise RuntimeError('Cannot load configured local embedding model.') from error
    raise ValueError(f'Unknown EMBEDDING_BACKEND: {backend!r}')
