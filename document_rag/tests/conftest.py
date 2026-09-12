"""Isolation reseau pour les tests unitaires document_rag.

Force EMBEDDING_BACKEND=local_light (embedding ONNX par defaut de ChromaDB,
100% offline) pour tout test de ce package, quel que soit le contenu du
.env du projet. Empeche les tests unitaires (ChromaManager, IngestionOrchestrator,
reindexation incrementale) de taper reellement sur un endpoint distant
(ex. tunnel ngrok) configure pour l'usage applicatif reel.

Les tests qui testent explicitement resolve_embedding_function() avec un
backend precis (test_embedding_functions.py) passent ce backend en parametre
direct de la fonction, pas via l'env -- non affectes par cette fixture.
"""

import pytest


@pytest.fixture(autouse=True)
def _force_offline_embedding_backend(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_light")
