# 🔍 Project Review — MIRO KE Odoo AI Assistant

## Overall Verdict

**The architecture vision is strong.** The hybrid agent approach (router → RAG docs / RAG code / ORM tools) is genuinely the right call for this use case — not a naive RAG-and-pray setup. The ORM-over-SQL decision is wise. The fake data is well crafted. The dev/prod Groq↔Ollama switch is pragmatic.

That said, there are **critical gaps in the plan** that will bite you during implementation if not addressed now. Below are my concerns, ranked by impact.

---

## 🔴 Critical Issues

### 1. No Embedding Model Strategy

This is your **single biggest blind spot**. You've specified LLMs extensively (Hermes 3, Mistral, etc.) but never mentioned which embedding model you'll use. For RAG, the embedding model matters **more** than the LLM — a bad retriever feeding a great LLM still produces garbage.

Your specific challenges:
- Your content is **primarily in French** (wikis, tickets, invoicing docs)
- You also need to embed **Python/XML code**, which has very different semantics
- You need it to run **locally** on an RTX 3060

**Recommendations:**
| Model | Dims | Size | Why |
|-------|------|------|-----|
| `intfloat/multilingual-e5-base` | 768 | ~1 GB | Best balance for French + general text |
| `OrdalieTech/Solon-embeddings-large-0.1` | 1024 | ~1.3 GB | Specifically tuned for French |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | ~550 MB | Good multilingual + code support |

> [!IMPORTANT]
> Don't use the same embedding strategy for code and documents. Code benefits from **larger chunks with function-level boundaries**, while documents need **smaller, overlapping chunks**. Consider using **two separate ChromaDB collections** with potentially different embedding models.

---

### 2. No Evaluation Framework

You're building this for a **Master's thesis** (M2 stage). Your jury will ask: *"How do you know it works? What's the accuracy?"* You have no evaluation plan.

**What you need:**
- **A test dataset**: 30-50 question/expected-answer pairs covering all 4 question types from your spec
- **Metrics**: At minimum, track **retrieval relevance** (are the right chunks retrieved?) and **answer correctness** (is the final answer right?)
- **Tools**: Look into [Ragas](https://docs.ragas.io/) — it's designed exactly for RAG evaluation and integrates with LangChain

> [!TIP]
> Start building your test dataset **now**, before you write any pipeline code. It forces you to think clearly about what "correct" looks like, and you can use it to iterate faster later.

---

### 3. Missing User Identity / RBAC Passthrough

Your instruction says:
> *L'ORM Odoo respecte nativement le RBAC (droits d'accès utilisateur)*

This is true — but **only if you pass the right user context**. Who is asking the question? Your architecture doesn't show how user identity flows from the chat interface → FastAPI → ORM tool calls.

If you call Odoo XML-RPC with a single admin account, **you bypass all RBAC**. Every user sees everything. That defeats the purpose.

**Solution:** Each API request must carry the Odoo user's `uid` + session, and your ORM tools must use **that user's credentials** for XML-RPC calls.

---

## 🟡 Important Design Considerations

### 4. Code Chunking Needs Special Treatment

Naive `RecursiveCharacterTextSplitter` on Python code will cut functions in half, split class definitions mid-method, and lose all structural context. For your "Où est implémentée cette logique dans le code ?" use case, this will fail.

**Recommendation:**
- Use `langchain.text_splitter.Language.PYTHON` for Python files — it's AST-aware
- For XML (Odoo views/data), parse with `lxml` and chunk by `<record>` or `<template>` blocks
- Store **full function signatures** in metadata, not just line numbers

```python
# Good metadata for code chunks
metadata = {
    "source": "account/models/account_move.py",
    "type": "code_python",
    "module": "account",
    "odoo_version": "17",
    "lines": "45-89",
    "class": "AccountMove",           # ← add this
    "function": "_post",              # ← add this
    "docstring": "Validate and post..." # ← and this
}
```

### 5. Use LangGraph, Not Plain LangChain, for the Router

You have both installed. Your architecture **is** a LangGraph problem — it's a stateful graph with conditional routing:

```
Question → Router Node → [RAG-docs | RAG-code | ORM-tool] → Citation Node → Response
```

Plain LangChain chains can't do this cleanly. LangGraph gives you:
- Explicit state management
- Conditional edges (router logic)
- Easy retry/fallback patterns
- Built-in streaming

> [!NOTE]
> LangGraph also makes it trivial to add **conversation memory** later (see point 7), which your spec currently doesn't mention but users will expect.

### 6. The ORM Tools Need Careful Scoping

Your spec mentions `get_sales_total(client, period)` and `get_approval_rule(type)`. Good instinct — but think about:

- **How many tools?** If you define 50 tools, the LLM can't reliably choose. Keep it under 10-15 for 8B models.
- **Fallback behavior**: What if the question doesn't match any tool? The agent should gracefully fall back to RAG, not hallucinate a tool call.
- **Error handling**: What if the Odoo server is down? The tool must return a human-readable error, not crash.
- **Tool descriptions**: For small models (8B), the tool description quality is **everything**. Spend time writing crystal-clear descriptions in French.

### 7. No Conversation Memory

Users will naturally do multi-turn conversations:
> — "Combien de ventes a fait le client Rakoto cette année ?"  
> — *(answer)*  
> — "Et l'année dernière ?"

Your architecture doesn't show how you handle the `"l'année dernière"` — it requires knowing the previous question's context. LangGraph with a `MessagesState` handles this natively.

---

## 🟢 Nice-to-Haves / Polish

### 8. ChromaDB Is Fine for POC, But Plan the Exit

If the long-term vision is to sell this to multiple Odoo clients, each client needs **data isolation**. ChromaDB can do this with separate collections per tenant, but it doesn't scale well past ~1M vectors. Note this in your thesis as a known limitation with migration path to Qdrant or Weaviate.

### 9. Source Citation Enforcement

Your spec says *"source citée obligatoire"*. LLMs don't reliably do this without enforcement. Two approaches:

- **Structured output** (recommended): Use Pydantic models with LangChain to force the response into `{answer: str, sources: List[Source]}` format
- **Prompt engineering**: Add explicit instructions like *"Chaque affirmation doit être suivie de [Source: filename:L45-89]"* — but this is fragile with small models

### 10. Security: Your API Key Is Exposed

Your `.env` contains a real `GROQ_API_KEY`. Even though `.gitignore` excludes `.env`, if this repo was ever pushed with the file tracked, the key is compromised. **Rotate it.** Also make sure the `.env` was never committed in git history.

---

## 📋 Suggested Build Order

Given that ~85% of the core logic is unimplemented, here's the order I'd recommend:

```
Phase 1 — Prove RAG works (1-2 weeks)
  ├── vectorstore/chroma_manager.py  ← embeddings + collections
  ├── ingestion/pdf_loader.py        ← ingest fake_data into ChromaDB
  └── rag/pipeline.py                ← basic retrieve + generate
  └── Manual test: ask a question, get an answer with source

Phase 2 — Add the agent layer (1-2 weeks)
  ├── tools/odoo_tools.py            ← 3-5 ORM tools using fake_data
  ├── Upgrade pipeline.py to LangGraph router
  └── Manual test: route between RAG and tools correctly

Phase 3 — Expose as API (1 week)
  ├── api/main.py                    ← FastAPI endpoints
  └── Simple web UI or Streamlit demo

Phase 4 — Connect to real Odoo (1-2 weeks)
  ├── Replace fake_data with XML-RPC ingestion
  ├── odoo_module/                   ← Odoo chat widget addon
  └── Deploy on MIRO KE's server with Ollama

Phase 5 — Evaluate & document (ongoing)
  ├── Build test dataset
  ├── Run Ragas evaluation
  └── Write thesis chapter on results
```

---

## TL;DR — Top 5 Actions Right Now

1. **Pick your embedding model** (multilingual, runs on RTX 3060)
2. **Start building a test Q&A dataset** (30+ questions across all 4 types)
3. **Build Phase 1 first** — `chroma_manager.py` → `pdf_loader.py` → `pipeline.py`
4. **Plan for user identity** in your API design from day 1
5. **Use LangGraph** for the router, not plain LangChain chains
