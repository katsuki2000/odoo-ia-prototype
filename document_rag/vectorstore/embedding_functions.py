"""Embedding functions and provider resolver for ChromaDB vectorstore."""

import time
from typing import Any, Dict, List, Optional
import requests
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space

from config import settings


class OllamaEmbeddingFunction(EmbeddingFunction):
    """HTTP embedding client for the configured Ollama server (OpenAI-compatible API)."""
    def __init__(self, base_url: str, model: str, api_key: str = 'ollama', timeout: Optional[float] = None, max_retries: int = 3, batch_size: int = 16):
        self.base_url = base_url
        clean_url = base_url.rstrip('/')
        self.endpoint = f'{clean_url}/embeddings' if '/v1' in clean_url else f'{clean_url}/v1/embeddings'
        self.model = model
        self.api_key = api_key or 'ollama'
        self.timeout = float(timeout if timeout is not None else settings.EMBEDDING_TIMEOUT)
        self.max_retries = max(1, int(max_retries))
        self.batch_size = max(1, int(batch_size))

    @staticmethod
    def name() -> str:
        return 'local-server'

    def default_space(self) -> Space:
        return 'cosine'

    def supported_spaces(self) -> List[Space]:
        return ['cosine', 'l2', 'ip']

    def get_config(self) -> Dict[str, Any]:
        return {'base_url': self.base_url, 'model': self.model, 'timeout': self.timeout}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> 'OllamaEmbeddingFunction':
        return OllamaEmbeddingFunction(base_url=config['base_url'], model=config['model'], timeout=config['timeout'])

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


def resolve_embedding_function(embedding_model: Optional[str] = None) -> EmbeddingFunction:
    """Embedding client for the configured Ollama server; an explicit model overrides the configured one."""
    from config.settings import EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY, require_inference_server
    return OllamaEmbeddingFunction(base_url=require_inference_server(EMBEDDING_BASE_URL),
                                   model=embedding_model or EMBEDDING_MODEL,
                                   api_key=EMBEDDING_API_KEY)
