import pytest

from document_rag.vectorstore import search
from document_rag.vectorstore.bm25_index import BM25Index


class FakeCollection:
    def __init__(self, rows):
        self.rows = dict(rows)

    def get(self, include=None):
        ids = list(self.rows)
        if include == []:
            return {'ids': ids}
        return {'ids': ids, 'documents': [self.rows[i] for i in ids], 'metadatas': [{} for _ in ids]}


class FakeManager:
    def __init__(self, rows):
        self.collection = FakeCollection(rows)


def test_matches_tracks_chunk_ids():
    manager = FakeManager({'a': 'facture client', 'b': 'stock entrepot'})
    index = BM25Index()
    index.build_from_chroma(manager)
    assert index.matches(manager)
    manager.collection.rows['c'] = 'vente commande'
    assert not index.matches(manager)
    index.build_from_chroma(manager)
    del manager.collection.rows['a']
    assert not index.matches(manager)


def test_matches_covers_every_collection():
    first, second = FakeManager({'a': 'facture'}), FakeManager({'b': 'stock'})
    index = BM25Index()
    index.build_from_chroma([first, second])
    assert index.matches([first, second])
    assert not index.matches(first)


def test_emptied_collection_clears_the_index():
    manager = FakeManager({'a': 'facture client'})
    index = BM25Index()
    index.build_from_chroma(manager)
    manager.collection.rows.clear()
    assert index.build_from_chroma(manager) == 0
    assert index.size == 0 and not index.is_built and index.search('facture') == []


def test_get_retriever_rebuilds_when_chroma_changes(monkeypatch):
    manager = FakeManager({'a': 'facture client'})
    monkeypatch.setattr(search, '_shared_chroma', manager)
    monkeypatch.setattr(search, '_shared_bm25', None)
    _, first = search.get_retriever()
    assert search.get_retriever()[1] is first
    manager.collection.rows['b'] = 'stock entrepot'
    _, rebuilt = search.get_retriever()
    assert rebuilt is not first and rebuilt.size == 2
