"""Disk cache of document embeddings, addressed by text content."""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np


logger = logging.getLogger(__name__)


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SemanticIndexStore:
    """One file per embedding model; every failure degrades to an empty cache."""

    def __init__(self, directory: str, embedding_name: str):
        digest = hashlib.sha256(embedding_name.encode("utf-8")).hexdigest()[:16]
        self._path = Path(directory) / f"{digest}.npz"

    def load(self) -> Dict[str, List[float]]:
        if not self._path.is_file():
            return {}
        try:
            with np.load(self._path, allow_pickle=False) as archive:
                return dict(zip(archive["keys"].tolist(), archive["vectors"].tolist()))
        except (OSError, ValueError, KeyError):
            logger.warning("Ignoring unreadable semantic index cache %s", self._path, exc_info=True)
            return {}

    def save(self, vectors: Dict[str, Sequence[float]]) -> None:
        if not vectors:
            return
        temporary_path = None
        try:
            keys = list(vectors)
            matrix = np.asarray([vectors[key] for key in keys], dtype=np.float32)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._path.parent, suffix=".tmp", delete=False) as handle:
                temporary_path = Path(handle.name)
                np.savez(handle, keys=np.array(keys), vectors=matrix)
            os.replace(temporary_path, self._path)
        except (OSError, ValueError):
            logger.warning("Could not write semantic index cache %s", self._path, exc_info=True)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
