# -*- coding: utf-8 -*-
"""
router.py
=========
Agentic router — the brain of the AI ERP Core.

Given a user question, the router:
  1. Sends the question to the LLM with ALL available tools in the schema
     (doc_rag, code_rag, get_sales_total, ...) plus a system instruction
     to pick the right pipeline(s).
  2. If the LLM calls an ORM tool  → executes it via tools.call_tool()
  3. If the LLM signals doc/code RAG → runs retrieval + builds context
  4. Sends a final generation call with the retrieved context injected
  5. Returns a structured AnswerResult with content + citations + pipeline label

Architecture note: for the POC, this is a two-step agentic loop (one routing
call + one generation call). In a future iteration this can be replaced with
LangGraph for more complex multi-step reasoning.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# ── Pseudo-tool definitions for RAG routing ─────────────────────────────────
# The LLM can call these "virtual" tools to signal which RAG pipeline to use.
# They are not real Python functions — the router intercepts them.

_RAG_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'search_documents',
            'description': (
                'Recherche dans les documents indexés (PDFs, articles Knowledge, '
                'tickets Helpdesk). Utilise cet outil pour les questions sur '
                'les politiques, procédures, manuels ou contenus documentaires.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Question de recherche sémantique'},
                },
                'required': ['query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_code',
            'description': (
                'Recherche dans le code source des modules Odoo (Python, XML). '
                'Utilise cet outil pour les questions sur l\'implémentation, '
                'la logique métier dans le code ou la localisation de fonctions.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Question de recherche dans le code'},
                },
                'required': ['query'],
            },
        },
    },
]

_ROUTER_SYSTEM_PROMPT = """Tu es un assistant IA interne pour un ERP Odoo 17.
Tu as accès à plusieurs outils :
- search_documents : pour rechercher dans les documents (PDFs, wikis, tickets)
- search_code : pour rechercher dans le code source des modules Odoo
- Des outils ORM : pour interroger les données en temps réel (ventes, stock, etc.)

INSTRUCTIONS :
1. Analyse la question et choisis le ou les outils les plus adaptés.
2. Appelle TOUJOURS au moins un outil — ne réponds jamais directement sans chercher.
3. Si la question porte sur des données chiffrées (montants, quantités, statuts),
   utilise les outils ORM appropriés.
4. Si la question porte sur des procédures, politiques ou documentation,
   utilise search_documents.
5. Si la question porte sur le code source ou l'implémentation technique,
   utilise search_code.
6. Tu peux appeler plusieurs outils si nécessaire.
"""


@dataclass
class AnswerResult:
    """Structured result returned by the router."""
    content: str = ''
    pipeline_used: str = 'fallback'
    tool_called: str = ''
    citations: list[dict] = field(default_factory=list)
    tokens_prompt: int = 0
    tokens_completion: int = 0
    duration_ms: int = 0
    error: str = ''


class RouterService:
    """
    Agentic router that decides which pipeline answers a question.

    Parameters
    ----------
    env    : Odoo environment
    config : ai.config recordset
    """

    def __init__(self, env, config):
        self.env = env
        self.config = config
        self._ollama = None
        self._retriever = None

    def _get_ollama(self):
        if not self._ollama:
            from .ollama_client import OllamaClient
            self._ollama = OllamaClient(self.config)
        return self._ollama

    def _get_retriever(self):
        if not self._retriever:
            from .retriever import RetrieverService
            self._retriever = RetrieverService(self.config)
        return self._retriever

    # ── Public entry point ──────────────────────────────────────────────────────

    def answer(self, question: str, history: list[dict] | None = None) -> AnswerResult:
        """
        Route a question through the correct pipeline and return an answer.

        Parameters
        ----------
        question : str
            The user's question (in any language).
        history  : list[dict], optional
            Previous conversation turns as [{"role": ..., "content": ...}].

        Returns
        -------
        AnswerResult
        """
        result = AnswerResult()

        try:
            # ── Step 1: Build the tool schema (RAG + ORM tools) ────────────────
            orm_tools_schema = self.env['ai.tool'].get_tools_schema_for_llm()
            all_tools = _RAG_TOOLS + orm_tools_schema

            # ── Step 2: Build the routing messages ─────────────────────────────
            messages = [{'role': 'system', 'content': _ROUTER_SYSTEM_PROMPT}]
            if history:
                messages.extend(history[-6:])  # last 3 turns for context
            messages.append({'role': 'user', 'content': question})

            # ── Step 3: First LLM call — routing decision ──────────────────────
            ollama = self._get_ollama()
            # Override system prompt for routing call (don't use config's prompt)
            original_system = ollama.system_prompt
            ollama.system_prompt = ''  # Already in messages

            routing_response = ollama.chat(messages, tools=all_tools)
            result.tokens_prompt += routing_response['tokens_prompt']
            result.tokens_completion += routing_response['tokens_completion']
            result.duration_ms += routing_response['duration_ms']

            ollama.system_prompt = original_system  # Restore

            tool_calls = routing_response.get('tool_calls', [])

            if not tool_calls:
                # LLM answered directly without tool use — fallback
                result.content = routing_response['content']
                result.pipeline_used = 'fallback'
                return result

            # ── Step 4: Execute tool calls ──────────────────────────────────────
            context_blocks: list[str] = []
            all_citations: list[dict] = []
            pipelines_used: set[str] = set()
            orm_tool_name = ''

            for tc in tool_calls:
                fn_name = tc.get('name', '')
                fn_args = tc.get('arguments', {})

                if fn_name == 'search_documents':
                    hits = self._run_doc_rag(fn_args.get('query', question))
                    if hits:
                        from .retriever import RetrieverService
                        ctx = RetrieverService.hits_to_context_block(hits, 'Documents')
                        context_blocks.append(ctx)
                        all_citations.extend(RetrieverService.hits_to_citations(hits))
                    pipelines_used.add('doc_rag')

                elif fn_name == 'search_code':
                    hits = self._run_code_rag(fn_args.get('query', question))
                    if hits:
                        from .retriever import RetrieverService
                        ctx = RetrieverService.hits_to_context_block(hits, 'Code source')
                        context_blocks.append(ctx)
                        all_citations.extend(RetrieverService.hits_to_citations(hits))
                    pipelines_used.add('code_rag')

                else:
                    # ORM tool call
                    from .tools import call_tool
                    tool_result = call_tool(self.env, fn_name, fn_args)
                    source = tool_result.pop('source', f'Odoo ORM — {fn_name}')
                    ctx = (
                        f'=== Données ERP ({fn_name}) ===\n'
                        + json.dumps(tool_result, ensure_ascii=False, indent=2)
                    )
                    context_blocks.append(ctx)
                    all_citations.append({'source': source, 'score': 1.0})
                    orm_tool_name = fn_name
                    pipelines_used.add('orm_tool')

            # ── Step 5: Second LLM call — final answer generation ───────────────
            if context_blocks:
                context_str = '\n\n'.join(context_blocks)
                generation_prompt = (
                    f'{question}\n\n'
                    f'Voici les informations trouvées pour répondre à cette question :\n\n'
                    f'{context_str}\n\n'
                    'En te basant UNIQUEMENT sur les informations ci-dessus, '
                    'réponds à la question. '
                    'Cite les sources dans ta réponse en utilisant les numéros [1], [2], etc.'
                )
                gen_messages = [{'role': 'user', 'content': generation_prompt}]
                gen_response = ollama.chat(gen_messages)
                result.content = gen_response['content']
                result.tokens_prompt += gen_response['tokens_prompt']
                result.tokens_completion += gen_response['tokens_completion']
                result.duration_ms += gen_response['duration_ms']
            else:
                # No context retrieved — use what the routing call returned
                result.content = (
                    routing_response['content']
                    or 'Aucune information trouvée dans les sources disponibles.'
                )

            # ── Step 6: Build result metadata ───────────────────────────────────
            result.citations = all_citations
            if len(pipelines_used) > 1:
                result.pipeline_used = 'combined'
            elif pipelines_used:
                result.pipeline_used = pipelines_used.pop()
            result.tool_called = orm_tool_name

        except Exception as exc:
            _logger.exception('Router error for question: %s', question)
            result.content = (
                'Une erreur interne s\'est produite lors du traitement de votre question. '
                f'Détail : {exc}'
            )
            result.error = str(exc)
            result.pipeline_used = 'fallback'

        return result

    # ── Internal RAG calls ──────────────────────────────────────────────────────

    def _run_doc_rag(self, query: str) -> list[dict]:
        try:
            return self._get_retriever().retrieve_documents(query)
        except Exception as exc:
            _logger.warning('Doc RAG retrieval failed: %s', exc)
            return []

    def _run_code_rag(self, query: str) -> list[dict]:
        try:
            return self._get_retriever().retrieve_code(query)
        except Exception as exc:
            _logger.warning('Code RAG retrieval failed: %s', exc)
            return []
