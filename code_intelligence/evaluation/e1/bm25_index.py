"""BM25 index over E1 node cards (lexicon lives inside card text)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from rank_bm25 import BM25Okapi

from .cards import NodeCard, build_node_cards, tokenize


@dataclass(frozen=True)
class Bm25Hit:
    object_ref: str
    score: float
    node_type: str


@dataclass
class Bm25CardIndex:
    cards: tuple[NodeCard, ...]
    _bm25: BM25Okapi
    _language: Optional[str]

    @classmethod
    def build(cls, graph, *, language: Optional[str] = None, node_types: Sequence[str] | None = None) -> "Bm25CardIndex":
        cards = tuple(
            build_node_cards(
                graph,
                language=language,
                node_types=node_types or ("Model", "Menu", "Field", "Method", "Group", "Rule", "Button"),
            )
        )
        corpus = [tokenize(card.text) for card in cards]
        if not corpus:
            corpus = [[]]
            cards = tuple()
        return cls(cards=cards, _bm25=BM25Okapi(corpus), _language=language)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        node_types: Sequence[str] | None = None,
    ) -> list[Bm25Hit]:
        # Drop function words on the query only; card text keeps them so
        # rare phrases in labels are unchanged.
        tokens = tokenize(query, drop_stopwords=True)
        if not tokens or not self.cards:
            return []
        scores = self._bm25.get_scores(tokens)
        allowed = set(node_types) if node_types else None
        ranked: list[Bm25Hit] = []
        for card, score in zip(self.cards, scores):
            if allowed is not None and card.node_type not in allowed:
                continue
            if score <= 0:
                continue
            ranked.append(Bm25Hit(object_ref=card.object_ref, score=float(score), node_type=card.node_type))
        ranked.sort(key=lambda hit: (-hit.score, hit.object_ref))
        return ranked[:top_k]
