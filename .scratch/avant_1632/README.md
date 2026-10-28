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
AWS_OLLAMA_HOST=http://<aws-instance-address>:11434
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


### Step 9 : Seed ERP data and configure the instance

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Consolidated setup script : this is a test purpose script (Company Alpha, sales journal, users, products, demo data), the projects should work on your own data
python3 scripts/full_setup.py
```

### Step 10 : Ingest documents into the vector store (ChromaDB)

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

# Run non-integration unit tests safely
pytest tests/ -m "not integration"
```

> [!NOTE]
> Never run an unconstrained `pytest tests/ -v` on resource-limited machines without AVX2, as full graph traversals take over 30 minutes. Always target specific test modules or use `-m "not integration"`.

---

## Repository Structure

```text
odoo-ia-prototype/
├── api/                        # FastAPI endpoints, authentication and long-running ask jobs
├── config/                     # Deployment settings and constants
├── core/
│   ├── graph/                  # Main LangGraph pipeline, routing and final verification
│   └── evidence/                # Observations collected from tools
├── document_rag/               # Internal-document ingestion, retrieval and generation
├── erp_data/runtime/           # Typed, read-only Odoo ORM tools
├── odoo_addons/miro_ai/        # Odoo 17 chat interface and authenticated backend client
├── scripts/                    # Setup and evaluation utilities
├── tests/                      # Unit, integration and PoC evaluation tests
├── captures/                   # Evaluation traces and replay results
├── todo/
│   ├── architecture.md         # Agreed PoC scope and target architecture
│   ├── rules.md                # Development rules
│   └── contexte.txt            # Work log
├── .env.example                # Template for deployment-specific values
└── requirements.txt            # Python dependencies
```

The system mode runs one agent loop over the typed, read-only ORM tools (`fields_get`, `search`, `read`, `search_read`, `search_count`, `read_group`, `name_search`); it refuses out-of-scope, prompt-injection and mass-extraction requests before any tool call. The documentary path remains a separate RAG route.

---

## Configuration Reference

### Settings (`config/settings.py`)

`config/` reads from the environment (`.env` or the shell) only what varies per machine or deployment: secrets, addresses of the LLM server, the Odoo instance and the API, and locations of the Odoo installation (each with a portable default), listed below. Application behavior, model choices, thresholds, limits, and other stable settings are constants in `config/settings.py` or `config/google_drive.py`; paths to external installations may be configured per machine.

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_TARGET` | No | `aws` | Inference host: `aws` (production) or `kaggle` (temporary dev host) |
| `<TARGET>_OLLAMA_HOST` | Yes | none | Ollama server address, read with the prefix of the target (`AWS_` or `KAGGLE_`) |
| `<TARGET>_LLM_BASE_URL` / `<TARGET>_LLM_API_KEY` | No | `<host>/v1` / `ollama` | Optional overrides of the chat endpoint and its key |
| `<TARGET>_EMBEDDING_BASE_URL` | No | `<host>/v1` | Embedding server URL |
| `CORE_ADDONS_PATH` | No | `../odoo-17.0/addons` | Path to core Odoo addons |
| `CUSTOM_ADDONS_PATH` | No | `./odoo_addons` | Path to custom addons |
| `ODOO_URL` | No | `http://localhost:<http_port of odoo.conf>`, else `http://localhost:8069` | Odoo XML-RPC server URL (overrides odoo.conf) |
| `ODOO_DB` | No | `db_name` of odoo.conf when it names a single database, else `odoo-dev` | Odoo database name (overrides odoo.conf) |
| `ODOO_USERNAME` | No | `admin` | XML-RPC service username |
| `ODOO_ADMIN_PASSWORD` | Yes | none | Password of the Odoo service account (metadata, health, live validation). No default; keep it in the backend `.env`, never in the Odoo interface |

---

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `ConnectionRefusedError` on ask | Configured inference server is not running or reachable | Start the Ollama server or check `<TARGET>_OLLAMA_HOST` |
| `InvalidDimensionException` in ChromaDB | Switched embedding model without re-indexing | Run `rm -rf document_rag/vectorstore/chroma_db` then `python3 -m document_rag.ingestion.ingest_all` |
| MIRO AI button not visible in Odoo | Module not loaded or browser cache | Run `python3 odoo-bin -c odoo.conf -d odoo-dev -u miro_ai --stop-after-init` and refresh with Ctrl+F5 |
| `OdooConnectorError`: Authentication failed | Odoo is down or credentials do not match | Verify PostgreSQL is running and check `ODOO_URL` / `ODOO_PASSWORD` in `.env` |
