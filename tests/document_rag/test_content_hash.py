from document_rag.hashing import content_hash


def test_content_hash_is_short_deterministic_and_content_sensitive():
    assert len(content_hash("This is test content")) == 12
    assert content_hash("This is test content") == content_hash("This is test content")
    assert content_hash("This is test content") != content_hash("This is different content")
