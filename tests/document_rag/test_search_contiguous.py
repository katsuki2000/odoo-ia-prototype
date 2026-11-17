from types import SimpleNamespace
from unittest.mock import patch

from document_rag.retrieval.search_contiguous import expand_contiguous_chunks, expand_dominant_documents


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


def _part(index, kind="table", section="Debouches", source="guide", total=10):
    document = {"table": f"| Row{index} | Value{index} |", "list": f"- item {index}", "prose": f"Paragraph {index}."}[kind]
    metadata = {"source": source, "chunk_index": index, "total_chunks": total, "section": section, "has_table": kind == "table"}
    return {"id": f"{source}:{index}", "document": document, "metadata": metadata}


def _expand(retrieved_indexes, parts):
    results = [parts[index] for index in retrieved_indexes]
    return [item["metadata"]["chunk_index"] for item in expand_contiguous_chunks(results, _chroma(guide=parts))]


def test_a_table_found_by_one_chunk_is_returned_whole():
    parts = [_part(index) for index in range(6)]
    assert _expand([2], parts) == [0, 1, 2, 3, 4, 5]


def test_a_table_is_not_followed_into_another_section():
    parts = [_part(0, section="A"), _part(1, section="A"), _part(2, section="B"), _part(3, section="B"), _part(4, section="B")]
    assert _expand([2], parts) == [1, 2, 3, 4]


def test_a_table_is_not_followed_past_a_chunk_without_rows():
    parts = [_part(0), _part(1), _part(2), _part(3, kind="prose"), _part(4)]
    assert _expand([0], parts) == [0, 1, 2, 3]


def test_a_list_only_brings_its_two_neighbours():
    parts = [_part(index, kind="list") for index in range(5)]
    assert _expand([2], parts) == [1, 2, 3]


def test_a_chunk_without_list_or_table_is_not_expanded():
    parts = [_part(index, kind="prose") for index in range(4)]
    assert _expand([1], parts) == [1]


def test_a_table_is_followed_for_at_most_the_expansion_limit_in_each_direction():
    parts = [_part(index) for index in range(10)]
    with patch("document_rag.retrieval.search_contiguous.RAG_DOCUMENT_EXPANSION_MAX_CHUNKS", 2):
        assert _expand([5], parts) == [3, 4, 5, 6, 7]


def test_only_the_added_chunks_are_marked_as_expansions():
    parts = [_part(index) for index in range(3)]
    expanded = expand_contiguous_chunks([parts[1]], _chroma(guide=parts))
    assert [item.get("is_contiguous_expansion", False) for item in expanded] == [True, False, True]


def test_chunks_of_other_sources_are_left_in_place():
    parts = [_part(index) for index in range(3)]
    other = _part(0, kind="prose", source="faq")
    expanded = expand_contiguous_chunks([other, parts[1]], _chroma(guide=parts, faq=[other]))
    assert _indexes(expanded) == [("faq", 0), ("guide", 0), ("guide", 1), ("guide", 2)]
