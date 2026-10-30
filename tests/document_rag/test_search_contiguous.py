from types import SimpleNamespace

from document_rag.vectorstore.search_contiguous import expand_dominant_documents


def _chunk(source, index, score=None, total=4):
    chunk = {"id": f"{source}:{index}", "document": f"{source} part {index}",
             "metadata": {"source": source, "chunk_index": index, "total_chunks": total}}
    if score is not None:
        chunk["rrf_score"] = score
    return chunk


def _chroma(**chunks_by_source):
    """Collection stub answering collection.get(where={'source': ...}) like Chroma does."""
    def get(where):
        chunks = chunks_by_source.get(where["source"])
        if chunks is None:
            raise RuntimeError("collection unreadable")
        return {"ids": [c["id"] for c in chunks], "documents": [c["document"] for c in chunks],
                "metadatas": [c["metadata"] for c in chunks]}
    return SimpleNamespace(collection=SimpleNamespace(get=get))


def _indexes(results):
    return [(item["metadata"]["source"], item["metadata"]["chunk_index"]) for item in results]


def test_a_document_with_enough_chunks_in_the_results_is_returned_whole_in_document_order():
    manual = [_chunk("manual", index) for index in range(5)]
    results = [_chunk("manual", 3, 1.0), _chunk("manual", 0, 0.8), _chunk("manual", 1, 0.7)]
    expanded = expand_dominant_documents(results, _chroma(manual=manual), min_chunks=3, max_chunks=20)
    assert _indexes(expanded) == [("manual", 0), ("manual", 1), ("manual", 2), ("manual", 3), ("manual", 4)]


def test_the_chunks_of_minority_documents_are_dropped_when_a_document_dominates():
    manual = [_chunk("manual", index) for index in range(5)]
    results = [_chunk("manual", 3, 1.0), _chunk("faq", 0, 0.9), _chunk("manual", 0, 0.8), _chunk("manual", 1, 0.7)]
    expanded = expand_dominant_documents(results, _chroma(manual=manual, faq=[_chunk("faq", 0)]), min_chunks=3, max_chunks=20)
    assert {source for source, _ in _indexes(expanded)} == {"manual"}


def test_two_dominant_documents_are_both_kept():
    results = [_chunk("manual", 0, 1.0), _chunk("guide", 0, 0.9), _chunk("manual", 1, 0.8), _chunk("guide", 1, 0.7), _chunk("manual", 2, 0.6), _chunk("guide", 2, 0.5)]
    chroma = _chroma(manual=[_chunk("manual", index) for index in range(3)], guide=[_chunk("guide", index) for index in range(3)])
    expanded = expand_dominant_documents(results, chroma, min_chunks=3, max_chunks=20)
    assert {source for source, _ in _indexes(expanded)} == {"manual", "guide"}


def test_the_chunks_that_were_retrieved_keep_their_scores():
    manual = [_chunk("manual", index) for index in range(4)]
    results = [_chunk("manual", 2, 0.5), _chunk("manual", 0, 0.9), _chunk("manual", 1, 0.7)]
    expanded = expand_dominant_documents(results, _chroma(manual=manual), min_chunks=3, max_chunks=20)
    assert [item.get("rrf_score") for item in expanded] == [0.9, 0.7, 0.5, None]


def test_a_document_below_the_threshold_is_left_as_is():
    results = [_chunk("manual", 3, 1.0), _chunk("manual", 0, 0.8)]
    expanded = expand_dominant_documents(results, _chroma(manual=[_chunk("manual", index) for index in range(5)]), min_chunks=3, max_chunks=20)
    assert _indexes(expanded) == [("manual", 3), ("manual", 0)]


def test_a_document_larger_than_the_limit_is_left_as_is():
    results = [_chunk("book", 5, 1.0), _chunk("book", 9, 0.9), _chunk("book", 40, 0.8)]
    expanded = expand_dominant_documents(results, _chroma(book=[_chunk("book", index, total=50) for index in range(50)]), min_chunks=3, max_chunks=20)
    assert _indexes(expanded) == [("book", 5), ("book", 9), ("book", 40)]


def test_an_unreadable_document_is_left_as_is():
    results = [_chunk("manual", 3, 1.0), _chunk("manual", 0, 0.8), _chunk("manual", 1, 0.7)]
    expanded = expand_dominant_documents(results, _chroma(), min_chunks=3, max_chunks=20)
    assert _indexes(expanded) == [("manual", 3), ("manual", 0), ("manual", 1)]


def test_without_a_collection_the_results_are_returned_unchanged():
    results = [_chunk("manual", 3, 1.0)]
    assert expand_dominant_documents(results, None) == results
