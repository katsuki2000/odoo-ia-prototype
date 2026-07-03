# odoo-ia-prototype

Prototype d'intégration d'une IA privée dans Odoo 17.

## Modules

| Module | Description |
|--------|-------------|
| `estate` | Module d'exemple immobilier (ne pas modifier) |
| `idea_ai` | Prototype initial d'idées IA (ne pas modifier) |
| `ai_erp_core` | **Assistant IA privé — RAG + ORM + Ollama** |

---

## `ai_erp_core` — Architecture

```
┌─────────────────────────────────────────────────┐
│                  Utilisateur Odoo                │
│            (Chat Widget OWL dans ERP)            │
└─────────────────┬───────────────────────────────┘
                  │ /ai_erp/chat (JSON-RPC)
                  ▼
┌─────────────────────────────────────────────────┐
│              RouterService (router.py)           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Doc RAG  │  │ Code RAG │  │  ORM Tools   │  │
│  │ (PDFs,   │  │ (Python, │  │ (Ventes,     │  │
│  │  wikis,  │  │  XML)    │  │  Stock,      │  │
│  │  tickets)│  │          │  │  Factures…)  │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
└───────┼─────────────┼───────────────┼───────────┘
        │             │               │
        ▼             ▼               ▼
┌──────────────┐  ┌───────────┐  ┌──────────────┐
│   ChromaDB   │  │  ChromaDB │  │  Odoo ORM    │
│  (Documents) │  │   (Code)  │  │  (Direct)    │
└──────────────┘  └───────────┘  └──────────────┘
        │                ▲
        └────────────────┘
                 │ Embeddings
                 ▼
┌─────────────────────────────────────────────────┐
│              Ollama (local / GPU)                │
│   • hermes3:8b  (chat + tool-use + routing)     │
│   • mistral:7b  (French fluency fallback)        │
│   • nomic-embed-text  (embeddings)              │
└─────────────────────────────────────────────────┘
```

## Démarrage rapide

### 1. Prérequis
- Docker + Docker Compose
- Ollama installé sur la machine hôte (ou sur le serveur MIRO KE)
- Modèles Ollama tirés :
  ```bash
  ollama pull hermes3:8b
  ollama pull nomic-embed-text
  ```

### 2. Lancer l'environnement

```bash
cd odoo17-dev
docker compose up -d
```

Accès :
- Odoo : http://localhost:8069
- ChromaDB : http://localhost:8000

### 3. Installer le module

Dans Odoo :
1. Activer le mode développeur
2. Apps > Mettre à jour la liste des applications
3. Rechercher « AI ERP Core » > Installer

### 4. Configurer

**IA ERP > Configuration > Paramètres IA**

- URL Ollama : `http://host.docker.internal:11434` (si Ollama tourne sur l'hôte)
- Modèle chat : `hermes3:8b`
- Modèle embedding : `nomic-embed-text`
- Hôte ChromaDB : `chromadb`
- Port ChromaDB : `8000`

Cliquer **Tester la connexion**.

### 5. Indexer des documents

**IA ERP > Documents indexés > Nouveau**

- Type PDF : joindre un PDF et cliquer « Indexer dans ChromaDB »
- Type Code : renseigner le chemin `/mnt/extra-addons/mon_module/models/mon_model.py`

### 6. Démarrer une conversation

**IA ERP > Assistant IA > Nouveau**

---

## Dépendances Python (à installer dans le conteneur Odoo)

```bash
docker exec -it <odoo_container> pip install \
    requests \
    chromadb \
    pymupdf
```

Ou ajouter un `Dockerfile` personnalisé basé sur `odoo:17.0`.

---

## Roadmap POC

- [x] Architecture multi-pipeline (doc RAG + code RAG + ORM tools)
- [x] Client Ollama natif (pas de LangChain requis)
- [x] ChromaDB vector store
- [x] Pipeline d'ingestion PDF / Wiki / Ticket / Code
- [x] Router agentique avec tool-calling
- [x] Chat widget OWL dans Odoo 17
- [x] Citations obligatoires sur chaque réponse
- [ ] RBAC — filtrer les documents selon les droits Odoo de l'utilisateur
- [ ] Ingestion automatique via webhook (nouveau ticket → auto-index)
- [ ] Passage à LangGraph pour routing multi-étapes complexe
- [ ] Interface d'administration de l'index (re-indexation globale)
