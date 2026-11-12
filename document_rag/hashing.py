"""Content hash stored in the metadata of every ingested chunk."""

import hashlib


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
