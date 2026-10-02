# MIRO AI - Odoo AI Assistant

MIRO AI is an intelligent AI assistant connected in real time to an Odoo 17 ERP database via XML-RPC. It features a hybrid multi-agent routing system (LangGraph) capable of handling documentary knowledge questions (RAG vector search), real-time live ERP database queries, and deep Code Intelligence analysis (governance, security, workflow inspection).

The system can run **100% locally and offline** (via Ollama or vLLM) [I temporarely use cloud inference (Groq)].

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

* **100% Local Mode (Recommended)** : No external API keys required. Uses a local inference engine (such as [Ollama](https://ollama.com/) or [vLLM](https://github.com/vllm-project/vllm)) and ChromaDB's built-in ONNX embedding model (`all-MiniLM-L6-v2`) running locally on CPU.


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

**For 100% Local execution (Ollama / vLLM)**:
```dotenv
LLM_PROVIDER=local
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=gpt-oss:20b
LOCAL_LLM_API_KEY=ollama
EMBEDDING_BACKEND=local_light
```

**For Cloud execution (Groq)**:
```dotenv
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_API_KEY=gsk_YOUR_GROQ_API_KEY_HERE
EMBEDDING_BACKEND=local_light
```

*(You can switch between local and cloud at any time by changing `LLM_PROVIDER` in `.env`).*

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
addons_path = addons,/home/user/odoo-ia-prototype/odoo_addons
```

*(Adjust `/home/user/` to match your actual home directory path if different).*

### Step 7 : Verify the custom Odoo modules

All custom modules (`miro_ai` and the 14 `custom_*` business modules) are bundled inside this repository in `odoo_addons/`. Because you added them to `addons_path` in Step 6, Odoo detects them automatically.

### Step 8 : Initialize Odoo and install modules

```bash
cd ~/odoo-17.0

# Initialize database with base module
python3 odoo-bin -c odoo.conf -d odoo-dev -i base --stop-after-init

# Install miro_ai module
python3 odoo-bin -c odoo.conf -d odoo-dev -i miro_ai --stop-after-init

# Install all custom business modules


### Step 9 : Seed ERP data and configure the instance

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Consolidated setup script : this is a test purpose script (Company Alpha, sales journal, users, products, demo data), the projects should work on your own data
python3 scripts/full_setup.py
```

### Step 10 : Rebuild the Code Intelligence Knowledge Graph

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

python3 scripts/rebuild_graph.py
```

This scans all Odoo addons and generates `code_intelligence/active_graph.json` 

### Step 11 : Ingest documents into the vector store (ChromaDB)

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Index all internal documents (PDFs, markdown, text files) into ChromaDB
python3 -m document_rag.ingestion.ingest_all
```

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
pytest tests/test_local_llm_provider.py -v
pytest erp_data/tests/test_odoo_tools.py -v
pytest code_intelligence/tests/test_j46_j48_reasoning_trace.py -v

# Run non-integration unit tests safely
pytest tests/ -m "not integration"
```

> [!NOTE]
> Never run an unconstrained `pytest tests/ -v` on resource-limited machines without AVX2, as full graph traversals take over 30 minutes. Always target specific test modules or use `-m "not integration"`.

---

## Repository Structure

```text
odoo-ia-prototype/
├── api/                        # FastAPI REST exposition (main.py, auth.py, routes_*.py)
├── captures/                   # Test captures, verbatim responses, evaluation reports
├── code_intelligence/          # Code Intelligence bounded context
│   ├── active_graph.json       # Serialized Knowledge Graph (NetworkX)
│   ├── business_resolver/      # Business terms to technical models resolution
│   ├── ci_agent_node/          # LangGraph Code Intelligence agent & @tool wrappers
│   ├── deterministic/          # Deterministic evaluators (ACL, record rules, buttons)
│   ├── extractor/              # AST extractors (Python, XML views, actions, CSV)
│   ├── graph/                  # Knowledge graph loader, staleness, atomic swap
│   ├── investigation/          # Intent classifier and investigation planner
│   ├── overrides/              # Method override inheritance chains (_inherit)
│   ├── security/               # Security locks and Semgrep static analysis
│   └── server_actions/         # Server action static and LLM analysis
├── config/                     # Application configuration
│   └── settings.py             # Settings loader, defaults, latency budgets
├── core/                       # Shared system kernel
│   ├── llm_client.py           # Provider-agnostic LLM factory (Local / Groq / OpenRouter)
│   ├── reasoning_trace_logger.py # Cross-branch reasoning trace logger (JSONL)
│   ├── graph.py                # LangGraph StateGraph pipeline orchestrator
│   ├── routing.py              # Query router (documentary, ERP, CI, hybrid)
│   └── schemas.py              # Canonical Pydantic schemas (AssistantResponse, etc.)
├── document_rag/               # Documentary RAG bounded context
│   ├── documents/              # Source business documents and procedures (PDF, text)
│   ├── ingestion/              # Ingestion pipeline, PDF OCR, filesystem watcher
│   ├── prompts.py              # Documentary RAG system prompts and message builders
│   └── vectorstore/            # ChromaDB manager, BM25 hybrid search, embeddings
├── erp_data/                   # Runtime Odoo data bounded context
│   ├── date_utils.py           # French date expressions parser for domain filters
│   ├── odoo_connector.py       # XML-RPC client with user contextVar authentication
│   ├── odoo_tools.py           # Backward-compatible facade for ORM query tools
│   ├── orm_agent_node.py       # LangGraph ReAct agent loop for ERP queries
│   └── tools/                  # Domain query tools (sales, inventory, accounting, crm)
├── odoo_addons/                # Custom Odoo 17 modules (miro_ai + 14 business modules)
├── scripts/                    # Maintenance, seeding, and diagnostic CLI scripts
│   ├── full_setup.py           # Database initialization and demo seeding
│   ├── clean_demo_data.py      # Database cleanup script
│   ├── rebuild_graph.py        # Rebuild active_graph.json from source addons
│   └── run_scalability_test.py # Ingestion scalability benchmark runner
├── tests/                      # Automated test suite
│   ├── evaluation/             # Benchmark harnesses, datasets, and replay suites
│   ├── test_local_llm_provider.py # Provider switching and local mode unit tests
│   └── ...                     # Targeted unit and regression tests
├── todo/                       # Specifications, roadmap, rules, and change logs
│   ├── architecture.md         # Target system architecture
│   ├── contexte.txt            # Chronological change log
│   ├── plan.md                 # Project roadmap
│   └── rules.md                # Development rules and guidelines
├── .env                        # Local environment variables (gitignored)
├── .env_exemple                # Reference environment template
├── pytest.ini                  # Pytest runner configuration
└── requirements.txt            # Pinned Python package dependencies
```

---

## Configuration Reference

### Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | No | `local` | LLM backend: `local` (Ollama / vLLM) or `groq` / `openrouter` |
| `LOCAL_LLM_BASE_URL` | If local | `http://localhost:11434/v1` | Local OpenAI-compatible API base URL |
| `LOCAL_LLM_MODEL` | If local | `gpt-oss:20b` | Model name on the local engine (e.g. `llama3.1`, `qwen2.5:14b`) |
| `LOCAL_LLM_API_KEY` | If local | `ollama` | API key placeholder for local endpoint |
| `GROQ_API_KEY` | If Groq | - | Primary Groq API key |
| `GROQ_API_KEYS` | No | - | Comma-separated list of Groq keys for automatic rate-limit rotation |
| `GROQ_MODEL` | No | `openai/gpt-oss-20b` | Groq cloud model identifier |
| `EMBEDDING_BACKEND` | No | `local_light` | Embedding engine: `local_light` (Chroma ONNX), `ollama`, `local` |
| `LOCAL_EMBEDDING_BASE_URL` | If ollama embed | `http://localhost:11434/v1` | Local embedding server URL |
| `LOCAL_EMBEDDING_MODEL` | If ollama embed | `all-minilm:latest` | Local embedding model name (e.g. `nomic-embed-text`) |
| `RESOLVER_SEMANTIC_RETRIEVAL_ENABLED` | No | `true` | Adds instance-label semantic candidates to bounded LLM arbitration |
| `RESOLVER_SEMANTIC_EMBEDDING_BACKEND` | No | `EMBEDDING_BACKEND` | Optional embedding backend override for business-term retrieval |
| `RESOLVER_SEMANTIC_EMBEDDING_MODEL` | No | `EMBEDDING_MODEL` | Optional embedding model override for business-term retrieval |
| `CORE_ADDONS_PATH` | No | `../odoo-17.0/addons` | Path to core Odoo addons |
| `CUSTOM_ADDONS_PATH` | No | `./odoo_addons` | Path to custom addons |
| `RAG_DOCS_PATH` | No | `./document_rag/documents` | Path to source documents for RAG indexing |
| `ODOO_URL` | No | `http://localhost:8069` | Odoo XML-RPC server URL |
| `ODOO_DB` | No | `odoo-dev` | Odoo database name |
| `ODOO_USERNAME` | No | `admin` | XML-RPC service username |
| `ODOO_ADMIN_PASSWORD` | No | `admin` | Admin password for initial seeding and RPC fallback |

---

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `ConnectionRefusedError` on ask | Local LLM engine (Ollama/vLLM) is not running | Start your local engine (`ollama serve`) or switch `LLM_PROVIDER=groq` in `.env` |
| `InvalidDimensionException` in ChromaDB | Switched embedding model without re-indexing | Run `rm -rf document_rag/vectorstore/chroma_db` then `python3 -m document_rag.ingestion.ingest_all` |
| `active_graph.json` not found | Graph has not been built on this machine | Run `python3 scripts/rebuild_graph.py` |
| MIRO AI button not visible in Odoo | Module not loaded or browser cache | Run `python3 odoo-bin -c odoo.conf -d odoo-dev -u miro_ai --stop-after-init` and refresh with Ctrl+F5 |
| `OdooConnectorError`: Authentication failed | Odoo is down or credentials do not match | Verify PostgreSQL is running and check `ODOO_URL` / `ODOO_PASSWORD` in `.env` |
