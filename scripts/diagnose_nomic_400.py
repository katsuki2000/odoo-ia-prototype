"""
scripts/diagnose_nomic_400.py

Diagnostic ponctuel pour la regression du 2026-08-17 (pytest miro-rag/ -v :
15 echecs, tous requests.exceptions.HTTPError: 400 Client Error sur
https://api-atlas.nomic.ai/v1/embedding/text, plus un scalability test qui
passe de 157s a 959s sans lever d'exception).

But : reproduire l'appel exact fait par CustomNomicEmbeddingFunction.__call__
(vectorstore/chroma_manager.py) mais SANS response.raise_for_status(), pour
lire le corps JSON reel de la reponse 400 -- actuellement avale par
raise_for_status(), qui ne montre que "400 Client Error: Bad Request",
jamais le message de validation de l'API elle-meme.

Root cause pas encore posee : ne pas modifier chroma_manager.py avant d'avoir
lu ce corps de reponse (regle du projet -- pas de fix chirurgical, voir la
root cause).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent / "miro-rag"
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import requests

NOMIC_API_KEY = os.environ.get("NOMIC_API_KEY")
ENDPOINT = "https://api-atlas.nomic.ai/v1/embedding/text"


def main() -> int:
    if not NOMIC_API_KEY:
        print("NOMIC_API_KEY absent de l'environnement/.env -- rien a diagnostiquer.")
        return 1

    print(f"Cle presente, {len(NOMIC_API_KEY)} caracteres, prefixe: {NOMIC_API_KEY[:6]}...")

    payload = {
        "texts": ["texte de test pour diagnostic"],
        "model": "nomic-embed-text-v1.5",
        "task_type": "search_document",
    }

    print(f"\nPOST {ENDPOINT}")
    print(f"Payload envoye : {json.dumps(payload, ensure_ascii=False)}")

    start = time.perf_counter()
    try:
        response = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {NOMIC_API_KEY}"},
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        print(f"\nEchec de la requete elle-meme (avant reponse HTTP) apres {time.perf_counter() - start:.2f}s : {exc!r}")
        return 1
    elapsed = time.perf_counter() - start

    print(f"\nStatut HTTP : {response.status_code} (en {elapsed:.2f}s)")
    print(f"Headers de reponse : {dict(response.headers)}")
    print("\nCorps de reponse brut (jamais affiche par raise_for_status()) :")
    print(response.text)

    try:
        body = response.json()
        print("\nCorps de reponse pretty-JSON :")
        print(json.dumps(body, indent=2, ensure_ascii=False))
    except Exception:
        print("\n(corps non-JSON)")

    # Second essai avec un batch de plusieurs textes, pour verifier si le
    # probleme est specifique a la taille du batch plutot qu'au format de
    # la requete elle-meme (piste pour le ralentissement scalability, si un
    # gros batch echoue differemment d'un petit).
    print("\n" + "=" * 70)
    print("Second essai : batch de 3 textes (mime le shape d'un vrai add_chunks)")
    payload_batch = {
        "texts": [
            "Comment creer une facture dans Odoo",
            "Gestion des stocks et inventaire",
            "class SaleOrder(models.Model): _name = 'sale.order'",
        ],
        "model": "nomic-embed-text-v1.5",
        "task_type": "search_document",
    }
    start2 = time.perf_counter()
    try:
        response2 = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {NOMIC_API_KEY}"},
            json=payload_batch,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        print(f"Echec de la requete batch apres {time.perf_counter() - start2:.2f}s : {exc!r}")
        return 1
    elapsed2 = time.perf_counter() - start2
    print(f"Statut HTTP (batch) : {response2.status_code} (en {elapsed2:.2f}s)")
    print(response2.text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
