"""
ChromaDB Manager for vector storage and retrieval.

Handles initialization, CRUD operations, and querying against ChromaDB
with nomic-embed-text-v1.5 embeddings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import chromadb

# Add parent directory to path for config imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import CHROMA_PATH

logger = logging.getLogger(__name__)

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class CustomNomicEmbeddingFunction(EmbeddingFunction):
    """
    Fonction d'embedding maison pour Nomic, appelant directement l'API REST
    Atlas via `requests` — contourne le wrapper chromadb.utils.embedding_functions
    .NomicEmbeddingFunction, fragile face aux changements de version du SDK nomic.
    """

    def __init__(self, model: str = "nomic-embed-text-v1.5", api_key: str = None, task_type: str = "search_document"):
        self.model = model
        self.api_key = api_key
        self.task_type = task_type
        self.endpoint = "https://api-atlas.nomic.ai/v1/embedding/text"

    def name(self) -> str:
        return self.model

    def __call__(self, input: Documents) -> Embeddings:
        import requests

        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "texts": list(input),
                "model": self.model,
                "task_type": self.task_type,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"]


class LocalNomicEmbeddingFunction(EmbeddingFunction):
    """
    Fonction d'embedding locale nomic-embed-text-v1.5, via sentence-transformers
    (trust_remote_code=True) -- inference 100% locale, sans appel a l'API Atlas.

    Ajoutee le 17/08 suite au 400 de l'API Atlas (quota gratuit de 10M tokens
    depasse, cf. diagnose_nomic_400.py) : eviter une dependance a un service
    cloud payant est de toute facon coherent avec l'objectif du projet (IA
    livrable chez chaque client sans compte/facturation externe a provisionner).

    Le modele (~550 Mo) est charge une seule fois et partage entre instances.
    """

    _model = None

    def __init__(self, task_type: str = "search_document"):
        self.task_type = task_type
        if LocalNomicEmbeddingFunction._model is None:
            # Limit PyTorch threads to avoid CPU starvation
            os.environ.setdefault("OMP_NUM_THREADS", "2")
            os.environ.setdefault("MKL_NUM_THREADS", "2")

            from sentence_transformers import SentenceTransformer
            import torch

            torch.set_num_threads(2)

            logger.info("Chargement du modele d'embedding local nomic-embed-text-v1.5 (premier appel, peut prendre un moment)...")
            LocalNomicEmbeddingFunction._model = SentenceTransformer(
                "nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True
            )

    def name(self) -> str:
        return "nomic-embed-text-v1.5-local"

    def __call__(self, input: Documents) -> Embeddings:
        prefix = "search_query: " if self.task_type == "search_query" else "search_document: "
        prefixed = [f"{prefix}{text}" for text in input]
        embeddings = LocalNomicEmbeddingFunction._model.encode(
            prefixed, normalize_embeddings=True
        )
        return embeddings.tolist()


class ChromaManager:
    """Manages ChromaDB vector store for document chunks."""

    def __init__(
        self,
        db_path: str | Path = None,
        embedding_model: str = "nomic-embed-text-v1.5",
        collection_name: str = "odoo_documents",
    ):
        """
        Initialize ChromaDB with persistent storage.

        Args:
            db_path: Path to ChromaDB directory (defaults to vectorstore/chroma_db)
            embedding_model: Name of the embedding model to use
            collection_name: Name of the collection
        """
        if db_path is None:
            # BUGFIX (todo/contexte.txt): utilisait un calcul os.path.dirname
            # en dur, divergent du CHROMA_PATH de config.settings (deja
            # importe ci-dessus mais jamais consomme jusqu'ici) -- deux
            # sources de verite pour le meme chemin, cause du store
            # fantome document_rag/vectorstore/chroma_db vs vectorstore/
            # chroma_db (racine) peuple par erreur par ingest_all.py.
            db_path = CHROMA_PATH

        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.collection_name = collection_name

        # Initialize ChromaDB client with persistent storage
        self.client = chromadb.PersistentClient(path=str(self.db_path))

        embedding_function = self._resolve_embedding_function()

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={
                "embedding_model": embedding_model,
                "hnsw:space": "cosine",
                "description": "Odoo documents and code chunks",
            },
        )

        logger.info(
            f"ChromaDB initialized at {self.db_path} with collection '{collection_name}'"
        )

    def _resolve_embedding_function(self):
            """Résout la fonction d'embedding à utiliser.

            Local par défaut (nomic-embed-text-v1.5 via sentence-transformers) --
            plus de dépendance à un quota/paiement API externe. L'API Atlas reste
            disponible en repli explicite (EMBEDDING_BACKEND=nomic_api + clé) si un
            besoin de vitesse le justifie plus tard, une fois le budget débloqué.
            """
            backend = os.environ.get("EMBEDDING_BACKEND", "local_light")

            if backend == "nomic_api":
                nomic_api_key = os.environ.get("NOMIC_API_KEY")
                if nomic_api_key:
                    return CustomNomicEmbeddingFunction(
                        model=self.embedding_model,
                        api_key=nomic_api_key,
                    )
                logger.warning("EMBEDDING_BACKEND=nomic_api mais NOMIC_API_KEY absente. Repli sur le modèle local.")

            if backend == "local_light":
                logger.warning(
                    "EMBEDDING_BACKEND=local_light : utilisation du modele par defaut "
                    "de ChromaDB (all-MiniLM-L6-v2, 384 dimensions, onnxruntime) au "
                    "lieu de nomic-embed-text-v1.5 -- palliatif TEMPORAIRE, cette "
                    "machine n'a pas AVX2 et nomic-embed-text-v1.5 en local (PyTorch) "
                    "y est trop lent pour le vrai corpus (~3s/chunk mesure). A "
                    "repasser sur EMBEDDING_BACKEND=local (ou retirer la variable) "
                    "des que le materiel prevu arrive, sauf meilleur modele trouve "
                    "d'ici la. Toute collection ChromaDB deja peuplee avec un autre "
                    "modele doit etre reingeree en entier (dimensions incompatibles)."
                )
                return None

            try:
                return LocalNomicEmbeddingFunction()
            except Exception as e:
                # Ne PAS avaler l'erreur et retourner None ici : un embedding_function=None
                # fait retomber ChromaDB sur son propre modele par defaut (all-MiniLM-L6-v2,
                # 384 dimensions) EN SILENCE, incompatible avec nomic-embed-text-v1.5
                # (768 dimensions). C'est exactement ce qui s'est passe le 17/08 : dependance
                # manquante (einops), catch silencieux, ~1h20 d'ingestion faite avec le
                # mauvais modele sans qu'aucune erreur ne remonte a l'utilisateur. Mieux vaut
                # un crash net ici qu'un espace vectoriel incoherent qui semble marcher.
                logger.error(f"Échec du chargement du modèle d'embedding local: {e}")
                raise RuntimeError(
                    "Impossible de charger l'embedding local nomic-embed-text-v1.5 "
                    f"(voir cause ci-dessus). Ingestion arrêtée plutôt que de retomber "
                    "silencieusement sur le modèle par défaut de ChromaDB (dimensions "
                    "incompatibles)."
                ) from e

    def add_chunks(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """
        Add chunks to the vector store.

        Args:
            texts: List of text chunks
            metadatas: List of metadata dictionaries for each chunk
            ids: Optional list of IDs; generated if not provided

        Returns:
            List of chunk IDs
        """
        if not texts or not metadatas:
            logger.warning("Empty texts or metadatas provided to add_chunks")
            return []

        if len(texts) != len(metadatas):
            raise ValueError("texts and metadatas must have the same length")

        # Generate IDs if not provided
        if ids is None:
            ids = []
            for i, text in enumerate(texts):
                # Create ID from content hash
                content_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
                source = metadatas[i].get("source", "unknown")
                chunk_id = f"{source}_{i}_{content_hash}"
                ids.append(chunk_id)

        # Validate and clean metadata
        cleaned_metadatas = []
        for metadata in metadatas:
            cleaned = self._clean_metadata(metadata)
            cleaned_metadatas.append(cleaned)

        try:
            self.collection.add(
                ids=ids,
                documents=texts,
                metadatas=cleaned_metadatas,
            )
            logger.info(f"Added {len(texts)} chunks to ChromaDB")
            return ids
        except Exception as e:
            logger.error(f"Error adding chunks to ChromaDB: {e}")
            raise

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Query the vector store.

        Args:
            query_text: Query text
            top_k: Number of results to return
            where: Optional ChromaDB where filter

        Returns:
            Query results with documents, metadatas, distances, and IDs
        """
        try:
            kwargs = {
                "query_texts": [query_text],
                "n_results": top_k,
            }
            if where:
                kwargs["where"] = where

            results = self.collection.query(**kwargs)
            return self._format_query_results(results)
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {e}")
            raise

    def get_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        """
        Get a chunk by its ID.

        Args:
            chunk_id: The chunk ID

        Returns:
            Chunk data or None if not found
        """
        try:
            results = self.collection.get(ids=[chunk_id])
            if results and results["ids"]:
                return {
                    "id": results["ids"][0],
                    "document": results["documents"][0],
                    "metadata": results["metadatas"][0],
                }
            return None
        except Exception as e:
            logger.error(f"Error retrieving chunk {chunk_id}: {e}")
            return None

    def delete_by_source(self, source_path: str) -> int:
        """
        Delete all chunks from a specific source.

        Args:
            source_path: Path to the source file

        Returns:
            Number of chunks deleted
        """
        try:
            # Query for chunks with this source
            results = self.collection.get(
                where={"source": {"$eq": source_path}},
                include=[],  # Don't need to retrieve documents
            )

            if results and results["ids"]:
                chunk_ids = results["ids"]
                self.collection.delete(ids=chunk_ids)
                logger.info(f"Deleted {len(chunk_ids)} chunks from source {source_path}")
                return len(chunk_ids)

            return 0
        except Exception as e:
            logger.error(f"Error deleting chunks from source {source_path}: {e}")
            raise

    def delete_by_ids(self, ids: list[str]) -> int:
        """
        Delete specific chunks by ID.

        Args:
            ids: List of chunk IDs to delete

        Returns:
            Number of chunks deleted
        """
        if not ids:
            return 0

        try:
            self.collection.delete(ids=ids)
            logger.info(f"Deleted {len(ids)} chunks")
            return len(ids)
        except Exception as e:
            logger.error(f"Error deleting chunks: {e}")
            raise

    def get_stats(self) -> dict[str, Any]:
        """
        Get collection statistics.

        Returns:
            Dictionary with collection stats
        """
        try:
            # Count total documents
            all_docs = self.collection.get(include=[])
            total_chunks = len(all_docs.get("ids", []))

            # Count by type
            type_stats = {}
            for doc_type in ["code_python", "code_xml", "code_js", "code_csv", "doc_pdf", "doc_wiki"]:
                try:
                    results = self.collection.get(
                        where={"type": {"$eq": doc_type}},
                        include=[],
                    )
                    count = len(results.get("ids", []))
                    type_stats[doc_type] = count
                except Exception:
                    type_stats[doc_type] = 0

            # Count by module. `module` is an Odoo-code-only concept (see
            # code_loader.py::_extract_module_name()) -- document chunks
            # (PDF/wiki) never carry this key and structurally never will.
            # Chunks without it are excluded rather than bucketed under a
            # fabricated "unknown" (todo/contexte.txt section 353/354):
            # for a docs-only collection that produced a misleading
            # {'unknown': N} for every single chunk, N being 100% of the
            # collection, with zero real information content.
            module_stats = {}
            try:
                results = self.collection.get(include=["metadatas"])
                for metadata in results.get("metadatas", []):
                    module = metadata.get("module")
                    if module:
                        module_stats[module] = module_stats.get(module, 0) + 1
            except Exception:
                pass

            return {
                "total_chunks": total_chunks,
                "by_type": type_stats,
                "by_module": module_stats,
                "collection_name": self.collection_name,
                "embedding_model": self.embedding_model,
            }
        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {
                "error": str(e),
                "total_chunks": 0,
                "by_type": {},
                "by_module": {},
            }

    def delete_collection(self) -> None:
        """Delete the entire collection."""
        try:
            self.client.delete_collection(name=self.collection_name)
            logger.info(f"Deleted collection {self.collection_name}")

            # Recreate empty collection with the SAME embedding function as __init__
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._resolve_embedding_function(),
                metadata={
                    "embedding_model": self.embedding_model,
                    "hnsw:space": "cosine",
                    "description": "Odoo documents and code chunks",
                },
            )
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            raise

    # Helper methods

    @staticmethod
    def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Clean and validate metadata for storage in ChromaDB.

        ChromaDB has constraints on metadata values:
        - Must be JSON serializable
        - No nested dicts/lists
        - Values must be string, int, float, bool, or None
        """
        cleaned = {}

        for key, value in metadata.items():
            # Skip None values
            if value is None:
                continue

            # Convert to appropriate types
            if isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            elif isinstance(value, (dict, list)):
                # Flatten complex types to JSON string
                cleaned[key] = json.dumps(value)
            else:
                # Convert other types to string
                cleaned[key] = str(value)

        return cleaned

    @staticmethod
    def _format_query_results(raw_results: dict[str, Any]) -> dict[str, Any]:
        """
        Format raw ChromaDB query results into a cleaner structure.

        Args:
            raw_results: Raw results from ChromaDB

        Returns:
            Formatted results
        """
        formatted = {
            "results": [],
            "count": 0,
        }

        if not raw_results or not raw_results.get("ids"):
            return formatted

        ids = raw_results["ids"][0] if raw_results["ids"] else []
        documents = raw_results["documents"][0] if raw_results["documents"] else []
        distances = raw_results["distances"][0] if raw_results["distances"] else []
        metadatas = raw_results["metadatas"][0] if raw_results["metadatas"] else []

        for i in range(len(ids)):
            result = {
                "id": ids[i],
                "document": documents[i] if i < len(documents) else "",
                "distance": float(distances[i]) if i < len(distances) else 0.0,
                "similarity": 1 - float(distances[i]) if i < len(distances) else 0.0,
                "metadata": metadatas[i] if i < len(metadatas) else {},
            }
            formatted["results"].append(result)

        formatted["count"] = len(ids)
        return formatted


# Legacy function wrappers for backward compatibility

def get_chroma_client():
    """Get a persistent ChromaDB client."""
    # BUGFIX (todo/contexte.txt): meme divergence que ChromaManager.__init__
    # ci-dessus, corrigee de la meme facon (CHROMA_PATH, seule source de
    # verite desormais).
    db_path = CHROMA_PATH
    os.makedirs(db_path, exist_ok=True)
    client = chromadb.PersistentClient(path=db_path)
    return client


def get_or_create_collection(client, name="miro_knowledge_base"):
    """Get or create a ChromaDB collection using cosine similarity."""
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def add_documents(collection, documents, metadatas, ids):
    """
    Add documents to a ChromaDB collection.

    Args:
        collection: ChromaDB collection object
        documents: List of text chunks
        metadatas: List of metadata dictionaries (source, type, client, etc.)
        ids: List of unique string IDs
    """
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )
    print(f"Added {len(documents)} documents to collection '{collection.name}'")


def query_collection(collection, query_text, n_results=5, where_filter=None):
    """
    Query the collection for relevant documents.

    Args:
        collection: ChromaDB collection object
        query_text: The query string
        n_results: Number of results to return
        where_filter: Optional metadata filter dictionary

    Returns:
        Dictionary containing 'documents', 'metadatas', 'distances', and 'ids'
    """
    kwargs = {
        "query_texts": [query_text],
        "n_results": n_results,
    }
    if where_filter:
        kwargs["where"] = where_filter

    return collection.query(**kwargs)


def reset_collection(client, name="miro_knowledge_base"):
    """Delete and recreate a collection for clean re-ingestion."""
    try:
        client.delete_collection(name)
        print(f"Deleted collection '{name}'")
    except Exception:
        pass
    return get_or_create_collection(client, name)


def get_collection_stats(collection):
    """Retrieve basic statistics about a collection."""
    count = collection.count()
    return {"name": collection.name, "document_count": count}


if __name__ == "__main__":
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    stats = get_collection_stats(collection)
    print(f"Collection '{stats['name']}': {stats['document_count']} documents")
