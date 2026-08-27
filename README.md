# MIRO RAG - Odoo AI Assistant Prototype

MIRO RAG is an intelligent AI assistant connected in real time to an Odoo 17 ERP database via XML-RPC. It features a hybrid multi-agent routing system (LangGraph) capable of handling documentary knowledge questions (RAG vector search), real-time live ERP database queries, and deep Code Intelligence analysis (governance, security, workflow inspection).

---

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| **Python** | 3.11+ | Tested on Python 3.11.2 (Debian) |
| **PostgreSQL** | 14+ | For Odoo database |
| **Odoo 17 Community** | 17.0 | Source install at `~/odoo-17.0` |
| **Git** | any | |
| **OS** | Linux (Debian/Ubuntu recommended) | |

### External API Keys Required

| Variable | Provider | Purpose |
|---|---|---|
| `GROQ_API_KEY` | [Groq](https://console.groq.com/) | Main LLM provider (free tier available) |
| `NOMIC_API_KEY` | [Nomic](https://atlas.nomic.ai/) | Embedding model for ChromaDB vectorization |
| `HF_TOKEN` | [Hugging Face](https://huggingface.co/settings/tokens) | Tokenizer downloads (optional, for reranker) |

---

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

### Step 3 : Create the `.env` file

Create `~/odoo-ia-prototype/.env` with your own API keys:

```bash
cat > .env << 'EOF'
GROQ_API_KEY=gsk_YOUR_GROQ_API_KEY_HERE
LLM_PROVIDER=groq
NOMIC_API_KEY=nk-YOUR_NOMIC_API_KEY_HERE
HF_TOKEN=hf_YOUR_HF_TOKEN_HERE
EOF
```

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

Create or copy `~/odoo-17.0/odoo.conf`. Make sure to include the `odoo_addons` folder from this repository in your `addons_path`:

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

All custom modules (`miro_ai` and the 14 `custom_*` business modules) are already bundled inside this repository in the `odoo_addons/` directory. 
Because you added them to your `addons_path` in Step 6, Odoo will automatically detect them without needing any symlinks or copying.

**Custom modules included**:
`miro_ai`, `custom_asset_loan`, `custom_automation_traps`, `custom_credit_note_approval`, `custom_credit_note_approval_regional`, `custom_credit_note_approval_vip`, `custom_credit_note_visibility_rules`, `custom_deep_inheritance_security`, `custom_expense_reimbursement_indirect`, `custom_expense_risk_alert`, `custom_expense_risk_base`, `custom_expense_risk_score`, `custom_hr_leave_workflow`, `custom_modern_theme`, `custom_purchase_request`

### Step 8 : Initialize Odoo and install modules

```bash
cd ~/odoo-17.0

# First run: initialize the database with base module
python3 odoo-bin -c odoo.conf -d odoo-dev -i base --stop-after-init

# Install miro_ai module
python3 odoo-bin -c odoo.conf -d odoo-dev -i miro_ai --stop-after-init

# Install all custom modules (one command)
python3 odoo-bin -c odoo.conf -d odoo-dev \
  -i custom_asset_loan,custom_automation_traps,custom_credit_note_approval,custom_credit_note_approval_regional,custom_credit_note_approval_vip,custom_credit_note_visibility_rules,custom_deep_inheritance_security,custom_expense_reimbursement_indirect,custom_expense_risk_alert,custom_expense_risk_base,custom_expense_risk_score,custom_hr_leave_workflow,custom_purchase_request \
  --stop-after-init
```

### Step 9 : Seed ERP data and configure the environment

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Run the consolidated setup script (creates Company Alpha, sales journal,
# manager account, seed data for sales/tickets)
python3 tools/full_setup.py
```

### Step 10 : Rebuild the Code Intelligence Knowledge Graph

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

python3 scripts/rebuild_graph.py
```

This will scan all Odoo addons and generate `code_intelligence/active_graph.json` (~7.7 MB, ~11,000 nodes). This file **is** versioned in git, but should be rebuilt on a new machine if the custom modules have changed.

### Step 11 : Ingest documents into the vector store (ChromaDB)

The ChromaDB vector store (`document_rag/vectorstore/chroma_db/`) is in `.gitignore` and must be rebuilt locally:

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# The vectorstore is automatically built on first API startup,
# or you can trigger it manually:
python3 -c "from document_rag.vectorstore.search import get_retriever; get_retriever()"
```

---

## Running the Project

### Terminal 1 : Start Odoo 17

```bash
cd ~/odoo-17.0
python3 odoo-bin -c odoo.conf
```

Odoo will be available at **http://localhost:8069** (login: `admin` / password: `admin`).

### Terminal 2 : Start the FastAPI backend (MIRO RAG)

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at:
- **http://localhost:8000** (API root)
- **http://localhost:8000/docs** (Swagger interactive documentation)

### Using the Odoo interface

Once both servers are running:
1. Open **http://localhost:8069** in your browser
2. Look for the **MIRO AI** button (purple badge) in the top-right navbar (Systray)
3. Click it to open the floating AI assistant drawer
4. Ask questions in French about your Odoo instance

The MIRO AI Systray button automatically detects the current Odoo context (active model, record ID) and includes it in queries.

---

## Running Tests

```bash
cd ~/odoo-ia-prototype
source .venv/bin/activate

# Run the unit test suite (SAFE -- no external calls)
pytest tests/ -v -m "not integration"

# NEVER run `pytest tests/ -v` (full suite) -- it calls external LLM/Odoo
# services and can crash the machine. Always use -m "not integration".
```

Expected: **332 passed, 0 failed, 3 deselected**.

---

## Repository Structure

```
odoo-ia-prototype/
├── api/                        # FastAPI endpoints (main.py, auth.py)
├── captures/                   # Test captures and benchmark reports
├── code_intelligence/          # Code Intelligence engine
│   ├── active_graph.json       # Knowledge Graph (rebuilt via scripts/rebuild_graph.py)
│   ├── business_resolver.py    # Concept resolution (user terms -> Odoo models)
│   ├── ci_agent_node.py        # LangGraph CI agent node
│   ├── ci_graph_loader.py      # Graph builder from Odoo source files
│   ├── investigation_plan.py   # Bloc P1: Investigation Planner & Intent Classifier
│   ├── semantic_tags.py        # Couche 3: BehavioralTag / TechnicalTag ontology
│   └── tests/                  # CI-specific unit tests
├── config/                     # Settings and environment handling
│   └── settings.py             # All config (LLM, ChromaDB, latency budgets)
├── core/                       # Core pipeline
│   ├── graph.py                # LangGraph RAG pipeline (build_graph, query_graph)
│   ├── routing.py              # Query classification & keyword routing
│   ├── schemas.py              # AssistantResponse, QueryRoute, SourceReference
│   └── llm_client.py           # LLM client with rate limiting
├── document_rag/               # Vector store and RAG ingestion
│   ├── fake_data/              # JSON seed datasets (sales.json, tickets.json)
│   └── vectorstore/            # Hybrid ChromaDB + BM25 vector index
├── erp_data/                   # Odoo XML-RPC tools
│   ├── odoo_connector.py       # XML-RPC connection manager
│   ├── odoo_tools.py           # LangChain tool definitions
│   └── orm_agent_node.py       # ReAct agent loop for ERP queries
├── scripts/                    # Maintenance scripts
│   ├── rebuild_graph.py        # Rebuild active_graph.json from Odoo source
│   └── diagnose_h4_04c_05c_gap.py  # Diagnostic script for routing gaps
├── tests/                      # Pytest suite (332 unit tests)
├── todo/                       # Project documentation
│   ├── plan.md                 # Roadmap (DO NOT MODIFY without explicit mandate)
│   ├── rules.md                # Development rules
│   ├── contexte.txt            # Change log (append-only)
│   └── pratiques_odoo.md       # Odoo 17 coding guidelines
├── tools/                      # Setup utilities
│   ├── full_setup.py           # One-click Odoo environment setup
│   └── clean_demo_data.py      # Demo data cleanup
├── .env                        # API keys (NOT versioned, see .gitignore)
├── .gitignore
├── pytest.ini
├── requirements.txt            # 147 Python dependencies (pinned versions)
└── README.md
```

---

## Architecture Overview

```
User Query (Odoo Systray / API /api/v1/ask)
    │
    ▼
[retrieve] ──► ChromaDB + BM25 hybrid search
    │
    ▼
[route] ──► Keyword classification + business_resolver + Investigation Planner
    │
    ├── DONNEES_ERP      ──► ReAct Agent Loop (Odoo XML-RPC Tools) ──► Verified ERP Data
    ├── DOCUMENTAIRE     ──► LLM Generation with RAG context       ──► Procedure Answer
    ├── HYBRIDE          ──► Combined RAG + ReAct Agent Loop       ──► Synthesized Response
    └── CODE_INTELLIGENCE ──► CI Agent (Graph + Source Analysis)   ──► Governance Answer
                                                                          │
                                                                          ▼
                                                                [format_output]
                                                        (Sources, Evidence, Plan)
```

---

## Configuration Reference

### Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | - | Groq API key for LLM calls |
| `LLM_PROVIDER` | No | `groq` | LLM provider (`groq`, `openrouter`, `ollama`) |
| `NOMIC_API_KEY` | Yes | - | Nomic API key for embeddings |
| `HF_TOKEN` | No | - | Hugging Face token (for reranker model) |
| `OPENROUTER_API_KEY` | No | - | OpenRouter API key (alternative LLM) |
| `ODOO_URL` | No | `http://localhost:8069` | Odoo XML-RPC URL |
| `ODOO_DB` | No | `odoo-dev` | Odoo database name |
| `ODOO_PASSWORD` | No | `admin` | Odoo admin password |
| `JWT_SECRET` | No | `default_insecure_secret_for_dev` | JWT signing secret for API auth |
| `USE_RERANKER` | No | `false` | Enable cross-encoder reranking (CPU-intensive) |

### Odoo MIRO AI Settings

After installing the `miro_ai` module in Odoo, go to **Settings > MIRO AI** to configure:
- **API URL** : `http://127.0.0.1:8000` (default, points to the local FastAPI backend)
- **API Token** : JWT secret shared between Odoo and FastAPI

---

## Key Development Rules (from `todo/rules.md`)

- `todo/plan.md` is the roadmap. Changes should be rare and require explicit mandate.
- No surgical fixes -- always find the root cause.
- Minimal comments in code. Code in English.
- All packages must be in `requirements.txt`.
- Log every change in `todo/contexte.txt`.
- **NEVER run `pytest tests/ -v`** (full suite). Always use `pytest tests/ -v -m "not integration"`.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `ConnectionError` when asking MIRO AI in Odoo | Make sure the FastAPI backend is running (`uvicorn api.main:app --port 8000`) |
| MIRO AI icon not visible in Odoo navbar | Run `python3 odoo-bin -c odoo.conf -u miro_ai --stop-after-init` then Ctrl+F5 in browser |
| `ModuleNotFoundError` when running tests | Make sure you're in the venv: `source .venv/bin/activate` |
| ChromaDB empty / no retrieval results | Rebuild the vectorstore (see Step 11 above) |
| `active_graph.json` not found | Run `python3 scripts/rebuild_graph.py` |
| Odoo database connection refused | Check PostgreSQL is running: `sudo systemctl start postgresql` |
