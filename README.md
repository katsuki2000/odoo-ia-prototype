# MIRO RAG - Odoo AI Assistant Prototype

This repository contains the MIRO RAG AI Assistant prototype, connected in real time to an Odoo ERP database via XML-RPC. It uses a LangGraph multi-agent routing workflow to process both documentary questions (hybrid RAG over procedures) and live database queries (Sales, Accounting, Inventory, Support Tickets).

---

## Quick Start

### 1. One-Click Database Setup & Ingestion
```bash
cd ~/odoo-ia-prototype/miro-rag
python3 tools/full_setup.py
```

### 2. Run Accuracy Evaluation Benchmark
```bash
python3 tests/test_erp_accuracy.py
```
The report will be generated at `miro-rag/captures/erp_accuracy_report.md`.

---

## Sub-Projects

- **[miro-rag/](file:///home/user/odoo-ia-prototype/miro-rag/README.md)**: Main RAG application, agent graph, Odoo tools, setup scripts, and benchmark suite.
- **[contexte.txt](file:///home/user/odoo-ia-prototype/miro-rag/contexte.txt)**: Full changelog tracking all architectural updates and code refactoring.