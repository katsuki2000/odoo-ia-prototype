"""Non-authoritative discovery over the installed instance graph."""

import heapq
import json
import logging
from itertools import zip_longest

from langchain_core.tools import tool
from rapidfuzz import fuzz, utils

from code_intelligence.agent.node_labels import node_labels
from code_intelligence.agent.text_normalization import strip_accents
from code_intelligence.agent.tool_helpers import _require_graph

logger = logging.getLogger(__name__)


def _comparable(text: str) -> str:
    return utils.default_process(strip_accents(text))


def find_instance_candidates(graph, query: str, model: str = '', limit: int = 10) -> dict:
    limit = max(1, min(limit, 20))
    if not query.strip():
        return {'discovery_only': True, 'candidates': []}
    normalized = _comparable(query)
    def rankedNodes():
        for nodeId, data in graph.nodes(data=True):
            if data.get('node_type') not in {'Model', 'Method', 'Field', 'Button', 'Module', 'Menu'}:
                continue
            technicalName = str(data.get('name') or nodeId.split(':', 1)[-1])
            owner = technicalName if data.get('node_type') == 'Model' else data.get('model', '')
            if model and owner != model:
                continue
            labels = [technicalName, *node_labels(data)]
            score = max(fuzz.WRatio(normalized, _comparable(label)) for label in labels if label)
            if score >= 45:
                yield score, str(nodeId), owner, data
    ranked = heapq.nlargest(limit, rankedNodes(), key=lambda row: (row[0], row[1]))
    lexical = [dict(node_id=nodeId, node_type=data.get('node_type'), model=owner,
                    name=data.get('name', ''), labels=node_labels(data)[:3],
                    retrieval='lexical', score=round(score, 2))
               for score, nodeId, owner, data in ranked]
    semanticCandidates = []
    semanticStatus = 'not_requested'
    if not model:
        try:
            from code_intelligence.agent.semantic_retrieval import retrieve_semantic_model_candidates_scored
            semantic, status = retrieve_semantic_model_candidates_scored(query, graph, language=None, limit=limit)
            for name, score in semantic:
                nodeId = 'model:' + name
                if nodeId in graph:
                    semanticCandidates.append(dict(node_id=nodeId, node_type='Model', model=name,
                                                   name=name, retrieval='semantic', score=round(score, 4)))
            semanticStatus = status.value
        except Exception:
            logger.warning('Semantic discovery unavailable', exc_info=True)
            semanticStatus = 'unavailable'
    candidates, seen = [], set()
    # Rank round-robin keeps incomparable scores separate and semantic hits visible.
    for pair in zip_longest(semanticCandidates, lexical):
        for item in pair:
            if item is not None and item['node_id'] not in seen:
                candidates.append(item)
                seen.add(item['node_id'])
    return {'discovery_only': True, 'semantic_status': semanticStatus,
            'notice': 'Candidates are not behavior or authorization evidence. Inspect them with analysis tools.',
            'candidates': candidates[:limit * 2]}


@tool
def search_instance_objects(query: str, model: str = '', limit: int = 10) -> str:
    """Discover installed objects by labels; inspect candidates before drawing conclusions."""
    return json.dumps(find_instance_candidates(_require_graph(), query, model, limit), ensure_ascii=False)
