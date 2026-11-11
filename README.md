# MIRO AI - Odoo 17 Assistant PoC

MIRO AI is a proof of concept for a private assistant connected to an Odoo 17 instance. It has two response modes:

- **Documentation**: retrieve internal procedures and documents with the existing RAG pipeline (ChromaDB).
- **Odoo system**: answer questions about current business data with one agent that queries Odoo through typed, read-only ORM tools, under the identity of the requesting user.

The LLM helps select tools and explain the observations. The objective is to reduce unsupported answers, make the basis of responses inspectable, and state uncertainty when the available evidence is insufficient. The Code Intelligence agent (source-code analysis through an Odoo knowledge graph) is not part of this branch: it is kept on `main`.

Inference uses a privately controlled Ollama- or vLLM-compatible endpoint. The endpoint is configured in `.env`; there is no implicit cloud-provider fallback.

---

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| **Python** | 3.11+ | Tested on Python 3.11.2 (Debian / Linux) |
| **PostgreSQL** | 14+ | Database server for Odoo |
| **Odoo 17 Community** | 17.0 | Source install at `~/odoo-17.0` |
| **Git** | any | Version control |
| **OS** | Linux | Debian/Ubuntu recommended |

### LLM and Embedding Providers

Inference uses private OpenAI-compatible endpoints configured in `.env` (Ollama or vLLM on the AWS instance or reachable from it; the Kaggle endpoint is optional). There is no cloud-provider fallback.


## Complete Setup Guide (New Machine)

### Step 0 : Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev \
    postgresql postgresql-client libpq-dev \
    git build-essential libxml2-dev libxslt1-dev \
    libjpeg-dev libfreetype6-dev zlib1g-dev \
    libsasl2-dev libldap2-dev libssl-dev \
    node-less npm
```

### Step 1 : Clone this repository

```bash
cd ~
git clone https://github.com/katsuki2000/odoo-ia-prototype.git
cd odoo-ia-prototype
```

### Step 2 : Create the Python virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3 : Configure the `.env` file

Copy the example configuration or create your `.env`:

```bash
cp .env.example .env
```

The `.env` holds **secrets, service addresses, and paths that vary by machine or deployment** (for example, the Odoo installation and addon locations). Application behavior, model choices, thresholds, and limits remain constants in `config/settings.py`.

**Inference server (Ollama / vLLM)**: there is no implicit server; set the address of the target in `.env` (an unset address makes the application refuse to start the LLM client):
```dotenv
OLLAMA_HOST=http://<aws-instance-address>:11434
```
To use the temporary Kaggle host instead, set `LLM_TARGET=kaggle` and `KAGGLE_OLLAMA_HOST=https://<ngrok-tunnel>`.

### Step 4 : Install Odoo 17 (if not already present)

```bash
cd ~
# Clone Odoo 17 Community
git clone https://github.com/odoo/odoo.git --branch 17.0 --depth 1 odoo-17.0

# Install Odoo Python dependencies
cd odoo-17.0
pip install -r requirements.txt
```

### Step 5 : Configure PostgreSQL for Odoo

```bash
# Create the PostgreSQL user
sudo -u postgres createuser -s odoo
sudo -u postgres psql -c "ALTER USER odoo WITH PASSWORD 'odoo';"

# Create the database
sudo -u postgres createdb -O odoo odoo-dev
```

### Step 6 : Configure Odoo (`odoo.conf`)

Create or update `~/odoo-17.0/odoo.conf`. Ensure the `odoo_addons` folder from this repository is included in your `addons_path`:

```ini
[options]
db_host = localhost
db_port = 5432
db_user = odoo
db_password = odoo
addons_path = addons,<path-to-this-repository>/odoo_addons
```

*(Replace `<path-to-this-repository>` with the absolute path where you cloned this repository.)*

### Step 7 : Verify the custom Odoo modules

The custom module `miro_ai` is bundled inside this repository in `odoo_addons/`. Because you added that folder to `addons_path` in Step 6, Odoo detects it automatically.

### Step 8 : Initialize Odoo and install modules

```bash
cd ~/odoo-17.0

# Initialize database with base module
python3 odoo-bin -c odoo.conf -d odoo-dev -i base --stop-after-init

# Install miro_ai module
python3 odoo-bin -c odoo.conf -d odoo-dev -i miro_ai --stop-after-init

# Install the native maintenance module (used by the benchmark questions)
python3 odoo-bin -c odoo.conf -d odoo-dev -i maintenance --stop-after-init
```


### Step 9 : Synchronize the documents into the vector store (ChromaDB)

The documents live in the approved Google Drive folders (subfolders included; PDF, markdown, text and docx files, Google Docs are exported to docx). The API synchronizes them into the vector store at startup, then every 5 minutes (`sync_interval` in `config/google_drive.py`): new and changed files are added, and the chunks of files that left the approved folders are removed. It needs `GOOGLE_DRIVE_FOLDER_IDS`, `GOOGLE_DRIVE_APPROVED_FOR_RAG=true` and the read-only credentials (`GOOGLE_APPLICATION_CREDENTIALS`) in `.env`; without them the documentation mode has no source.

Each cycle updates `last_ingestion_time` in `GET /api/v1/ingestion/status`; `ingestion.log` only receives a `drive_sync` event when something changed or failed.

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# One synchronization, with the API stopped (--watch repeats it every 5 minutes)
python3 -m document_rag.ingestion.google_drive_cli
```

The API process must be the only one writing the index while it runs. A `google_drive_cli` run in another terminal leaves the running API with a stale index: it keeps returning deleted chunks, which breaks questions, and does not see the new ones. Use it with the API stopped, or restart the API afterwards.

---

## Running the Project

### Terminal 1 : Start Odoo 17

```bash
cd ~/odoo-17.0
python3 odoo-bin -c odoo.conf
```

Odoo is available at **http://localhost:8069** 

### Terminal 2 : Start the FastAPI backend (MIRO AI)

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is available at:
* **http://localhost:8000** (API root & health check)
* **http://localhost:8000/docs** (Swagger interactive documentation)

### Using the Odoo Interface

Once both services are running:
1. Open **http://localhost:8069** in your browser.
2. Click the **MIRO AI** button (purple badge) in the top-right navbar (Systray).
3. The AI assistant drawer opens, automatically contextualized to the current model and record.
4. Ask your questions in natural language.

---

## Running Tests

To run tests without risking AVX2 freezes on CPU, use targeted pytest invocations:

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Run targeted test suites
pytest tests/core/test_local_llm_provider.py -v
pytest tests/erp_data -v

# Run non-integration unit tests safely
pytest tests/ -m "not integration"
```

> [!NOTE]
> Never run an unconstrained `pytest tests/ -v` on resource-limited machines without AVX2, as full graph traversals take over 30 minutes. Always target specific test modules or use `-m "not integration"`.

---

## Repository Structure

```text
odoo-ia-prototype/
├── api/                            # FastAPI backend
│   ├── main.py                     #   App, CORS, startup hooks
│   ├── auth.py                     #   JWT authentication
│   ├── routes/                     #   FastAPI routers
│   │   ├── ask.py                  #     Question endpoint (async jobs)
│   │   ├── ingestion.py            #     Document ingestion status
│   │   └── system.py               #     Health check, system status
│   ├── ask_jobs.py                 #   Background job management
│   ├── schemas.py                  #   Pydantic request/response models
│   ├── language.py                 #   Language detection
│   └── public_errors.py            #   Error response formatting
├── config/                         # Deployment settings and constants
│   ├── settings.py                 #   Central configuration
│   ├── google_drive.py             #   Drive corpus settings
│   └── odoo_credentials.py         #   Odoo connection helpers
├── core/
│   ├── graph/                      #   Main LangGraph pipeline, routing, verification
│   │   ├── graph.py                #     Graph definition and entry point
│   │   ├── graph_nodes.py          #     Node implementations
│   │   └── verify_node.py          #     Answer verification node
│   ├── verification/               #   Claim extraction, checking, sentence analysis
│   │   ├── extractors.py           #     Number, XML ID, method call extractors
│   │   ├── checkers.py             #     Claim verifiers
│   │   ├── verifier.py             #     Verification orchestrator
│   │   ├── base_methods.py         #     Known ORM method registry
│   │   ├── context.py              #     Verification context
│   │   └── sentence_bounds.py      #     Sentence boundary detection
│   ├── session/                    #   Session persistence, reasoning traces
│   ├── evidence.py                 #   Observation evidence collection
│   ├── llm.py                      #   LLM client factory
│   ├── schemas.py                  #   Core data schemas
│   └── state.py                    #   Graph state definition
├── document_rag/                   # Documentary RAG pipeline
│   ├── ingestion/                  #   Document loading and chunking
│   │   ├── pdf_loader.py           #     PDF loading with OCR fallback
│   │   ├── document_loader.py      #     Multi-format loader dispatcher
│   │   ├── docx_reader.py          #     DOCX to markdown
│   │   ├── wiki_loader.py          #     Wiki/markdown loading
│   │   ├── file_formats.py         #     Format detection
│   │   ├── scan_root.py            #     Source path computation
│   │   ├── google_drive.py         #     Drive API client
│   │   ├── google_drive_sync.py    #     Full Drive sync logic
│   │   ├── google_drive_cli.py     #     CLI for Drive sync
│   │   ├── scheduler.py            #     Periodic sync scheduling
│   │   ├── periodic.py             #     Periodic run wrapper
│   │   └── logging_utils.py        #     Ingestion logging
│   ├── vectorstore/                #   Vector store management
│   │   ├── chroma_manager.py       #     ChromaDB collection management
│   │   ├── chroma_helpers.py       #     Chroma utility functions
│   │   └── embedding_functions.py  #     Ollama embedding wrapper
│   ├── retrieval/                  #   Search and ranking
│   │   ├── search.py               #     Main search orchestration
│   │   ├── search_hybrid.py        #     Hybrid vector + BM25 search
│   │   ├── search_contiguous.py    #     Contiguous chunk expansion
│   │   ├── search_ranking.py       #     Result ranking (RRF)
│   │   ├── bm25_index.py           #     BM25 lexical index
│   │   └── drive_guard.py          #     Drive availability guard
│   └── generation/                 #   LLM answer generation
│       ├── generate_node.py        #     LangGraph documentary node
│       ├── generate_helpers.py     #     Source aliasing, confidence, verification
│       └── prompts.py              #     RAG system prompts
├── erp_data/                       # Odoo ERP data querying
│   ├── connector/                  #   Odoo connection layer
│   │   ├── odoo_connector.py       #     XML-RPC Odoo connection
│   │   └── odoo_context.py         #     User identity and company context
│   ├── runtime/                    #   Security boundary & execution sandbox
│   │   ├── discovery.py            #     Model/field schema discovery
│   │   ├── identity.py             #     User identity enforcement
│   │   ├── validation.py           #     Input validation
│   │   ├── errors.py               #     Runtime error types
│   │   └── types.py                #     Type definitions
│   ├── tools/                      #   Typed read-only ORM tools
│   │   ├── read_tools.py           #     ORM read operations
│   │   └── langchain_tools.py      #     LangChain tool wrappers
│   └── agent/                      #   ERP agent
│       ├── orm_agent_node.py       #     LangGraph ORM agent node
│       ├── orm_agent_helpers.py    #     Agent utilities (plan, synthesis)
│       └── prompts.py              #     ERP system prompts
├── evaluation/                     # Model comparison and benchmarking
│   └── data/                       #   Question banks (JSON)
├── odoo_addons/miro_ai/            # Odoo 17 module
│   ├── __manifest__.py             #   Module manifest (v17.0.1.0.2)
│   ├── controllers/                #   HTTP controllers (ask flow, backend client)
│   ├── models/                     #   Odoo models (log, settings)
│   ├── views/                      #   XML views and menus
│   ├── security/                   #   Access rules (CSV + record rules)
│   ├── static/src/                 #   Frontend (JS, CSS, XML templates)
│   └── i18n/                       #   Translations (fr.po)
├── scripts/                        # Evaluation and utility scripts
├── tests/                          # Unit, integration and evaluation tests
│   ├── api/                        #   FastAPI routes, auth, jobs
│   ├── core/                       #   Graph, verification, LLM, sessions
│   ├── config/                     #   Settings
│   ├── document_rag/               #   Documentary RAG
│   ├── erp_data/                   #   ERP agent, connector, runtime
│   ├── evaluation/                 #   Benchmark and evaluation tooling
│   ├── miro_ai/                    #   Odoo addon
│   └── architecture/               #   Import layer rules
├── todo/                           # Project documentation
│   ├── architecture.md             #   Target architecture
│   ├── rules.md                    #   Development rules
│   └── contexte.txt                #   Work log
├── .github/workflows/ci.yml        # CI pipeline
├── .env.example                    # Template for deployment-specific values
├── requirements.txt                # Production dependencies
└── requirements-dev.txt            # Dev, test and evaluation dependencies
```

The system mode runs one agent loop over the typed, read-only ORM tools (`fields_get`, `search`, `read`, `search_read`, `search_count`, `read_group`, `name_search`); reads run under the requester's identity, so an instruction injected in a question cannot widen access, and out-of-scope questions get the fixed refusal from the prompt. The documentary path remains a separate RAG route.

---

## Configuration Reference

### Settings (`config/settings.py`)

`config/` reads from the environment (`.env` or the shell) only what varies per machine or deployment: secrets, addresses of the LLM server, the Odoo instance and the API, and locations of the Odoo installation (each with a portable default), listed below. Application behavior, model choices, thresholds, limits, and other stable settings are constants in `config/settings.py` or `config/google_drive.py`; paths to external installations may be configured per machine.

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_TARGET` | No | `aws` | Inference host: `aws` (production) or `kaggle` (temporary dev host) |
| `OLLAMA_HOST` | Yes | none | Ollama server address (`KAGGLE_OLLAMA_HOST` when `LLM_TARGET=kaggle`; every inference variable takes the `KAGGLE_` prefix on that target) |
| `LLM_BASE_URL` / `LLM_API_KEY` | No | `<host>/v1` / `ollama` | Optional overrides of the chat endpoint and its key |
| `EMBEDDING_BASE_URL` | No | `<host>/v1` | Embedding server URL |
| `ODOO_SOURCE_PATH` | No | `../odoo-17.0` | Odoo source checkout; the answer verifier reads the native ORM method names from `odoo/models.py` |
| `ODOO_URL` | No | `http://localhost:8069` | Odoo XML-RPC server URL |
| `ODOO_DB` | For the health check and scripts | none | Odoo database for calls made outside a user request; a request only uses the database signed into its JWT by the Odoo addon, never this value |
| `ODOO_ADMIN_LOGIN` | No | `admin` | XML-RPC service username |
| `JWT_SECRET` | Yes | none | Signing secret shared with the Odoo addon (at least 32 bytes) |
| `ODOO_ADMIN_PASSWORD` | Yes | none | Password of the Odoo service account (metadata, health, live validation). No default; keep it in the backend `.env`, never in the Odoo interface |
| `ODOO_BENCH_PASSWORD` | Benchmarks and manual checks only | none | Password of the Odoo user the model benchmark and `scripts/manual_check_odoo_assistant.py` sign in as |
| `GOOGLE_DRIVE_FOLDER_IDS` | For the Drive corpus | none | Comma-separated IDs of the approved Drive folders; empty: the Drive synchronization does nothing |
| `GOOGLE_DRIVE_APPROVED_FOR_RAG` | For the Drive corpus | `false` | Must be `true`: confirms that every RAG reader may see the selected folders |
| `GOOGLE_APPLICATION_CREDENTIALS` | For the Drive corpus | none | Path to the read-only Google credentials file used by the Drive synchronization |

---

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `ConnectionRefusedError` on ask | Configured inference server is not running or reachable | Start the Ollama server or check `OLLAMA_HOST` |
| `InvalidDimensionException` in ChromaDB | Switched embedding model without re-indexing | Run `rm -rf document_rag/vectorstore/chroma_db` then restart the API: the Drive synchronization rebuilds the index |
| MIRO AI button not visible in Odoo | Module not loaded or browser cache | Run `python3 odoo-bin -c odoo.conf -d odoo-dev -u miro_ai --stop-after-init` and refresh with Ctrl+F5 |
| A document added to Google Drive is not found by the assistant | The next API synchronization (every 5 minutes) has not run yet, the Drive variables are not set, or the index was written by another process while the API was running | Wait for the next synchronization and check the API log; if `google_drive_cli` was run in another terminal, restart the API |
| `TypeError: expected string or bytes-like object, got 'NoneType'` while answering | The index was written by another process while the API was running, so the API still returns deleted chunks | Restart the API; run `google_drive_cli` with the API stopped |
| `OdooConnectorError`: Authentication failed | Odoo is down or credentials do not match | Verify PostgreSQL is running and check `ODOO_URL` / `ODOO_ADMIN_PASSWORD` in `.env` |

---

## Google Drive Corpus -- Operational Details

One approved shared Drive corpus per target RAG collection. No mapping between Google accounts and Odoo users is required: a technical identity reads the folders, and the selected documents must be approved for every reader of that RAG collection.

### Authentication

Enable Google Drive API in your Google Cloud project. Use Application Default Credentials (ADC), preferably a dedicated service account with reader access only to the approved folders. Share those folders with the service account. On AWS, use supported workload identity federation or a credential file provisioned outside the repository (or in the git-ignored `secrets/` folder at the repository root). Never commit credential JSON, index it as a document, or paste keys into chat.

```dotenv
GOOGLE_DRIVE_FOLDER_IDS=your_folder_id
GOOGLE_APPLICATION_CREDENTIALS=path_to_external_credentials.json
GOOGLE_DRIVE_APPROVED_FOR_RAG=true
```

Folder IDs can be comma-separated. Keep one Drive corpus per collection; use separate storage/collections for distinct audiences or tenants. The request timeout, the size and file-count limits and the sync interval are constants of `config/google_drive.py`.

### Synchronization Behavior

Each cycle uses a full paginated folder inventory, not Drive Changes or a persistent cursor. File revisions avoid unnecessary downloads. Inventory limits or incomplete listings abort before removal. Timeouts, generic 403/quota errors and other ambiguous failures do not imply deletion.

After a complete inventory, Drive chunks for files absent from the selected corpus, unsupported files or files explicitly marked non-downloadable are deactivated before physical deletion. Ingestion of current readable files reuses the original loaders and adds replacement chunks before deleting old ones.

The main retrieval pipeline checks current chunk IDs and the `drive_active` flag before and after contiguous expansion. Stale BM25 entries for removed/deactivated Drive chunks are excluded. The shared BM25 index compares its chunk ids with ChromaDB on each retrieval and rebuilds itself when they differ.

### CLI Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Complete or skipped |
| 1 | Per-file errors or blocked corpus |
| 2 | Configuration, authentication, inventory or storage failure |

Watch mode emits a result every cycle, retries failures at the configured interval, and stops on interruption.

### Supported Formats

PDF, TXT, Markdown and DOCX reuse existing loaders. Google Docs export as DOCX. Other Google-native types and shortcuts are skipped. Subfolders and shared-drive listing flags are supported. Downloads are bounded and temporary. Redirects are refused to avoid forwarding bearer tokens. Sources retain stable Drive file URLs.

### Tests

```bash
python -m unittest discover -s tests -p 'test_google_drive*.py' -v
```

29 offline tests passed. Integration tests with live Drive credentials, production parsers and embeddings still need to be run in the project environment.

---

## Google Drive Corpus — Operational Details

This section covers operational details of the Google Drive synchronization. For initial setup and everyday usage, see [Step 9](#step-9--synchronize-the-documents-into-the-vector-store-chromadb).

### Authentication

Enable the Google Drive API in your Google Cloud project. Use Application Default Credentials (ADC), preferably a dedicated service account with **reader access only** to the approved folders. Share those folders with the service account. On AWS, use supported workload identity federation or a credential file provisioned outside the repository (or in the git-ignored `secrets/` folder at the repository root). Authorized-user ADC is also supported; there is no interactive OAuth setup.

Never commit credential JSON, index it as a document, or paste keys into chat.

### Synchronization behavior

Each cycle uses a **full paginated folder inventory**, not Drive Changes or a persistent cursor. File revisions avoid unnecessary downloads. Inventory limits or incomplete listings abort before removal. Timeouts, generic 403/quota errors and other ambiguous failures do not imply deletion.

After a complete inventory, Drive chunks for files absent from the selected corpus, unsupported files, or files explicitly marked non-downloadable are deactivated before physical deletion. Ingestion of current readable files reuses the original loaders and adds replacement chunks before deleting old ones.

If a configured root folder returns 404, the entire Drive corpus of that collection is deactivated and purged. Generic 403 errors pause synchronization without purging. A download error occurring after inventory does not revoke an existing indexed copy.

The retrieval pipeline checks current chunk IDs and the `drive_active` flag for vector/lexical candidates. Stale BM25 entries for removed/deactivated Drive chunks are excluded. The shared lexical (BM25) index compares its chunk IDs with ChromaDB on each retrieval and rebuilds itself when they differ, so another process can update the corpus without restarting the API.

This is periodic shared-corpus reconciliation, not instantaneous revocation or an end-user permission check. Already generated answers and requests in flight are not erased by chunk removal. Do not use a private/dynamically restricted corpus with this shared-reader model.

### Continuous worker

```bash
python -m document_rag.ingestion.google_drive_cli --watch
```

Run this worker under your deployment supervisor if it must survive logout/restart. A lock in the target Chroma directory excludes another instance. Distributed hosts need a shared locking/storage strategy or one designated writer.

### Supported formats

PDF, TXT, Markdown and DOCX reuse existing loaders. Google Docs export as DOCX. Other Google-native types and shortcuts are skipped. Subfolders and shared-drive listing flags are supported. Downloads are bounded and temporary. Redirects are refused to avoid forwarding bearer tokens. Sources retain stable Drive file URLs.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Complete or skipped (no folders configured) |
| 1 | Per-file errors or blocked corpus |
| 2 | Configuration, authentication, inventory, or storage failure |

Watch mode emits a result every cycle, retries failures at the configured interval, and stops on interruption; supervise its reports, not only its process exit code.

### Safety notes

- One approved shared Drive corpus per target RAG collection; no mapping between Google accounts and Odoo users is required.
- Keep one Drive corpus per collection; use separate storage/collections for distinct audiences or tenants. Changing the folder set authorizes reconciliation against the new set, including removal of old out-of-scope chunks.
- Request timeout, size limits, file-count limits and sync interval are constants of `config/google_drive.py`.

### Tests

```bash
python -m unittest discover -s tests -p 'test_google_drive*.py' -v
```

29 offline tests cover synchronization, availability and parsing with fixtures. The full retrieval pipeline, real Chroma metadata updates, inter-process locking, live Drive credentials/downloads, production parsers and embeddings still need integration tests in the project environment.
