from document_rag.generate_helpers import compute_rag_confidence


def test_confidence_is_the_top_chunk_score_clamped_to_one():
    assert compute_rag_confidence([{"score": 0.42}]) == 0.42
    assert compute_rag_confidence([{"score": 7.5}]) == 1.0


def test_zero_score_gives_zero_confidence():
    assert compute_rag_confidence([{"score": 0.0}, {"score": 0.0}, {"score": 0.0}]) == 0.0


def test_missing_score_falls_back_on_the_chunk_count():
    assert compute_rag_confidence([{}]) == 0.70
    assert compute_rag_confidence([{}, {}, {}]) == 0.90


def test_no_chunk_gives_zero_confidence():
    assert compute_rag_confidence([]) == 0.0
