# MIRO RAG - Odoo AI Assistant Prototype

MIRO RAG is an intelligent AI assistant connected in real time to an Odoo ERP database via XML-RPC. It features a hybrid multi-agent routing system capable of handling both documentary knowledge questions (RAG vector search) and real-time live ERP database queries (Sales, Accounting, Inventory, Support Tickets).

---

## Key Features

- **Hybrid Routing Graph**: Automatically classifies incoming queries into three execution branches:
  - **Documentary RAG**: Vector search (ChromaDB + BM25 hybrid search) over company procedures and guidelines.
  - **ERP Live Data (ReAct Loop)**: Real-time function calling over Odoo XML-RPC endpoints using self-describing English tool schemas.
  - **Hybrid RAG**: Combines documentation RAG context and live ERP data in a unified response.
- **Accent-Insensitive Partner Search**: Normalizes French accents (`é`, `è`, `ê`, `à`, `ç`, etc.) into SQL wildcards (`_`) in `ilike` filters, matching `Société Dupont` and `Societe Dupont` interchangeably.
- **Transparent ERP Sales Status Classification**: Distinguishes between pending proposals (`Devis en cours` / `draft`) and firm sales (`Ventes confirmées` / `sale` / `done`), providing transparent breakdown totals.
- **Universal Data Source Citation**: Every response systematically appends verifiable data source footers (e.g. `[Source: Odoo ERP - Module Ventes (sale.order)]` or `[Source: Documentation Odoo - Procédures]`).
- **Defensive Tool Fallback**: Automatically falls back to query active sales orders if confirmed sales return zero records, preventing missing data in complex queries.

---

## Repository Structure

```
miro-rag/
├── rag/
│   ├── graph.py               # LangGraph multi-agent routing workflow
│   └── vectorstore/           # Hybrid ChromaDB + BM25 vector index
├── tools/
│   ├── odoo_connector.py      # Odoo XML-RPC connection wrapper
│   ├── odoo_tools.py          # English self-describing tool definitions
│   ├── full_setup.py          # One-click Odoo database setup script
│   └── ingest_fake_data.py    # Seed data loader for sales, stock, and tickets
├── tests/
│   ├── benchmark_questions.json # 15 standard ERP evaluation questions
│   └── test_erp_accuracy.py    # Benchmark test runner
├── captures/
│   └── erp_accuracy_report.md  # Benchmark accuracy report output
├── fake_data/                  # JSON seed datasets (sales, stock, tickets)
├── texte_fr/                   # Documentation markdown files for vector RAG
└── contexte.txt                # System modification log tracking all changes
```

---

## One-Click Setup & Benchmark Execution

### 1. Initialize Odoo Environment & Seed Data
Execute the consolidated setup script to reset the single-company environment (`Company Alpha`), configure the Sales journal (`SJA`), create the manager account (`manager@miro.com`), configure income accounts, and import seed data:

```bash
cd ~/odoo-ia-prototype/miro-rag
python3 tools/full_setup.py
```

### 2. Run Benchmark Evaluation
Run the automated accuracy evaluation suite against all 15 benchmark questions:

```bash
python3 tests/test_erp_accuracy.py
```

The resulting evaluation report will be generated at `captures/erp_accuracy_report.md`.

---

## Architecture Overview

```
User Query
    │
    ▼
[Route Classification]
    ├── DONNEES_ERP    ──► ReAct Agent Loop (Odoo XML-RPC Tools) ──► Verified ERP Data
    ├── DOCUMENTAIRE   ──► Hybrid RAG Search (ChromaDB + BM25)   ──► Procedure Context
    └── HYBRIDE        ──► Combined RAG + ReAct Agent Loop       ──► Synthesized Response
                                                                          │
                                                                          ▼
                                                                [format_output]
                                                        (Appends Source Citations)
```
