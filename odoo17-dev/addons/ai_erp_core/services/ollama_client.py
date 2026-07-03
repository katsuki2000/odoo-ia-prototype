# -*- coding: utf-8 -*-
"""
ollama_client.py
================
Thin HTTP client wrapping the Ollama REST API.

Supported endpoints:
  POST /api/chat          — tool-use / chat completions (streaming or not)
  POST /api/embeddings    — text embedding
  GET  /api/tags          — list available models
  GET  /                  — health check

Designed to work without any third-party Ollama Python library so that the
Odoo container does not need extra system packages (pure stdlib + requests).
"""
import json
import logging
import time
from typing import Generator

_logger = logging.getLogger(__name__)

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False
    _logger.warning('ai_erp_core: `requests` not installed — Ollama client disabled.')


class OllamaClientError(Exception):
    """Raised when Ollama returns an error response."""


class OllamaClient:
    """
    Synchronous HTTP client for the Ollama REST API.

    Parameters
    ----------
    config : ai.config recordset
        The active AI configuration record providing connection details.
    """

    def __init__(self, config):
        self.base_url = (config.ollama_base_url or 'http://localhost:11434').rstrip('/')
        self.model_chat = config.model_chat or 'hermes3:8b'
        self.model_embed = config.model_embed or 'nomic-embed-text'
        self.timeout = config.timeout_seconds or 120
        self.temperature = float(config.temperature or 0.2)
        self.max_tokens = int(config.max_tokens or 1024)
        self.system_prompt = config.system_prompt or ''

    # ── Public API ──────────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        Ping the Ollama server.

        Returns
        -------
        (True, success_msg) | (False, error_msg)
        """
        if not _REQUESTS_AVAILABLE:
            return False, '`requests` library is not installed in this Odoo container.'
        try:
            resp = requests.get(f'{self.base_url}/', timeout=10)
            if resp.status_code == 200:
                return True, f'Connexion OK — {self.base_url}'
            return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
        except Exception as exc:
            return False, f'Erreur de connexion : {exc}'

    def list_models(self) -> list[str]:
        """Return names of models available on the Ollama instance."""
        if not _REQUESTS_AVAILABLE:
            return []
        try:
            resp = requests.get(f'{self.base_url}/api/tags', timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return [m['name'] for m in data.get('models', [])]
        except Exception as exc:
            _logger.warning('OllamaClient.list_models failed: %s', exc)
            return []

    def embed(self, text: str) -> list[float]:
        """
        Generate an embedding vector for *text* using the configured embed model.

        Parameters
        ----------
        text : str
            The text to embed.

        Returns
        -------
        list[float]
            The embedding vector.
        """
        if not _REQUESTS_AVAILABLE:
            raise OllamaClientError('`requests` not available')
        payload = {'model': self.model_embed, 'prompt': text}
        resp = requests.post(
            f'{self.base_url}/api/embeddings',
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()['embedding']

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        """
        Send a chat completion request to Ollama.

        Parameters
        ----------
        messages : list[dict]
            OpenAI-style message list [{"role": ..., "content": ...}, ...]
        tools : list[dict], optional
            Tool definitions in OpenAI/Ollama format for tool-calling.
        stream : bool
            Whether to stream the response (generator mode not yet used by router).

        Returns
        -------
        dict with keys:
          - 'content'      : str  — the assistant text reply
          - 'tool_calls'   : list — tool call objects (if any)
          - 'tokens_prompt': int
          - 'tokens_completion': int
          - 'duration_ms'  : int
        """
        if not _REQUESTS_AVAILABLE:
            raise OllamaClientError('`requests` not available')

        # Prepend system message if not already present
        if self.system_prompt and (not messages or messages[0].get('role') != 'system'):
            messages = [{'role': 'system', 'content': self.system_prompt}] + messages

        payload: dict = {
            'model': self.model_chat,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': self.temperature,
                'num_predict': self.max_tokens,
            },
        }
        if tools:
            payload['tools'] = tools

        t0 = time.monotonic()
        try:
            resp = requests.post(
                f'{self.base_url}/api/chat',
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise OllamaClientError(
                f'Ollama n\'a pas répondu dans {self.timeout}s. '
                'Vérifiez que le modèle est chargé.'
            )
        except requests.exceptions.ConnectionError as exc:
            raise OllamaClientError(f'Impossible de joindre Ollama : {exc}') from exc

        duration_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()

        # Parse response
        message = data.get('message', {})
        content = message.get('content', '')
        tool_calls_raw = message.get('tool_calls', [])

        # Normalise tool_calls list
        tool_calls = []
        for tc in tool_calls_raw:
            func = tc.get('function', tc)  # some models wrap in 'function'
            tool_calls.append({
                'name': func.get('name', ''),
                'arguments': func.get('arguments', {}),
            })

        # Token usage
        tokens_prompt = data.get('prompt_eval_count', 0)
        tokens_completion = data.get('eval_count', 0)

        return {
            'content': content,
            'tool_calls': tool_calls,
            'tokens_prompt': tokens_prompt,
            'tokens_completion': tokens_completion,
            'duration_ms': duration_ms,
        }
