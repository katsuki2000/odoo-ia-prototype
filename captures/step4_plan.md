# Step 4 — LangGraph RAG Pipeline (4 days)

> **Goal**: Build the conversational engine using LangGraph and Groq (`llama-3.1-8b-instant`) to process the context retrieved in Step 3 and output structured, accurately sourced answers with conversation memory.

> **Done when**: RAG pipeline answers doc/code questions with verifiable source citations. Memory handles follow-up questions. ≥ 90% correctly sourced answers on the benchmark.

---

## Prerequisites & Environment

| Item | Status | Action if missing |
|------|--------|-------------------|
| `GROQ_API_KEY` | ✅ Set in `miro-rag/env` | — |
| `langchain-groq` | ❌ Not installed | `pip install langchain-groq` |
| `langgraph` | ❌ Not installed | `pip install langgraph` |
| `langchain` | ❌ Not installed | `pip install langchain` |
| `pydantic` | ✅ Installed (2.13.4) | — |
| `langchain-core` | ✅ Installed (1.4.9) | — |
| `sentence-transformers` | ✅ Installed (Step 3) | — |
| `vectorstore/search.py` | ✅ `retrieve()` pipeline ready | — |
| `config/settings.py` | ✅ `GROQ_MODEL = "llama-3.1-8b-instant"` | — |

**First action on Day 1**: Install missing deps, add them to root `requirements.txt`.

---

## Existing Code Inventory

| File | Content | Reuse decision |
|------|---------|----------------|
| `rag/pipeline.py` | Legacy RAG pipeline using raw `groq` SDK, no LangGraph, no Pydantic output, no memory | **Replace** with LangGraph-based `rag/graph.py`. Keep `SYSTEM_PROMPT` text as starting point. |
| `config/settings.py` | `GROQ_API_KEY`, `GROQ_MODEL`, `CHROMA_PATH` | **Reuse** — import from here |
| `vectorstore/search.py` | `retrieve()`, `get_retriever()`, `quick_retrieve()` | **Reuse** — wire into Retrieve node |
| `vectorstore/chroma_manager.py` | `ChromaManager` class | **Reuse** — via `search.py` |

---

## Coding Rules (from `captures/rules.md`)

All code in this step MUST follow:

- **Règle 3** — Validate relationnels: always check `if chunk.get("metadata")` before accessing sub-keys
- **Règle 4** — `.get()` for all dict access, never `dict["key"]`
- **Règle 5** — Exhaustive if/elif/else for route classification
- **Règle 6** — `try...except` around all Groq API calls with `_logger.error()`
- **No `print()`** — use `logging.getLogger(__name__)` exclusively
- **French system prompt** — all user-facing text in French

---

## Day-by-Day Plan

### Day 1: Graph Skeleton, Schemas & Groq Wiring

| Day | Task | Deliverable |
|-----|------|-------------|
| Day 1 | **1a.** Install `langchain-groq`, `langgraph`, `langchain` into the venv. Add them to root `requirements.txt`. Verify Groq connectivity with a 1-line test: `ChatGroq(model="llama-3.1-8b-instant").invoke("ping")`. | Dependencies installed; Groq API responds. |
| | **1b.** Create `rag/schemas.py` with Pydantic v2 models: `SourceReference(source: str, doc_type: str, title: str, snippet: str, page: Optional[int])` and `AssistantResponse(answer: str, sources: list[SourceReference], confidence: float, ocr_warning: bool = False)`. Add `model_config = ConfigDict(strict=True)`. | `rag/schemas.py` created; models importable and validatable. |
| | **1c.** Create `rag/graph.py` with a LangGraph `StateGraph` defining nodes: `retrieve` → `generate` → `format_output`. The state type (`RAGState`) holds `question: str`, `chat_history: list`, `retrieved_chunks: list[dict]`, `raw_answer: str`, `response: AssistantResponse | None`. Wire `ChatGroq(model="llama-3.1-8b-instant", temperature=0.3, max_tokens=1024)` into the `generate` node. | `rag/graph.py` created; graph compiles without errors. |
| | **1d.** Test end-to-end with a single hardcoded question ("Comment créer une facture client dans Odoo 17 ?") using the existing `retrieve()` from `vectorstore/search.py`. Verify the output matches the `AssistantResponse` schema. | Graph runs on 1 test question; structured output returned with `answer`, `sources`, and `confidence`. |

---

### Day 2: Memory, System Prompt & Fallback Logic

| Day | Task | Deliverable |
|-----|------|-------------|
| Day 2 | **2a.** Add conversation memory via LangGraph's `MessagesState` pattern: inject the last 5 exchanges (user + assistant) into the prompt context. Store `chat_history` in graph state as `list[BaseMessage]`. | Memory state flows through the graph. |
| | **2b.** Write the production system prompt in French in `rag/prompts.py`. Base it on the existing `SYSTEM_PROMPT` in `rag/pipeline.py` but enhance with: (1) explicit source-citing instruction ("Cite chaque source entre crochets [Source: nom_fichier]"), (2) confidence scoring instruction ("Évalue ta confiance de 0.0 à 1.0"), (3) structured output format instruction for the LLM. | `rag/prompts.py` with `SYSTEM_PROMPT` and `build_user_prompt(question, context, chat_history)` function. |
| | **2c.** Add fallback logic in the `generate` node: if `retrieved_chunks` is empty or all chunks have RRF scores below 0.3 → return `AssistantResponse(answer="Je n'ai pas de source fiable pour répondre à cette question.", sources=[], confidence=0.0)`. | Fallback tested: query with no relevant context returns the explicit "no source" message. |
| | **2d.** Add out-of-scope handling: if the question is clearly unrelated to Odoo/MIRO (hors périmètre) → polite refusal in French: "Cette question ne fait pas partie de mon périmètre. Je suis spécialisé dans l'assistance Odoo et les procédures internes de MIRO KE." This is handled via prompt engineering (instruction in system prompt), not a separate classifier. | Out-of-scope questions ("Quelle est la recette du gâteau au chocolat ?") get polite refusal; no hallucinated answer. |
| | **2e.** Test memory with a 3-turn conversation scenario: (1) "Comment créer une facture ?" → answer, (2) "Et comment l'envoyer par email ?" → answer referencing the previous context, (3) "Quels sont les niveaux de relance ?" → new topic, memory doesn't interfere. | 3-turn conversation test passes; follow-up questions are contextually aware. |

---

### Day 3: Pipeline Integration & OCR Warnings

| Day | Task | Deliverable |
|-----|------|-------------|
| Day 3 | **3a.** Wire the full `retrieve()` function from `vectorstore/search.py` into the `retrieve` node of the graph. Use `get_retriever()` to get shared `ChromaManager` + `BM25Index` instances (avoid re-building the BM25 index on every query). Pass `top_k=5`, `use_reranker=True`. | Retrieve node calls the real hybrid search pipeline; results flow into generate node. |
| | **3b.** Implement OCR warning detection in the `format_output` node: scan each chunk's metadata for `ocr_quality == "low"`. If any source has low OCR quality, set `response.ocr_warning = True` and append to the answer: "\n\n⚠️ *Cette information provient d'un document numérisé dont la qualité de lecture est limitée.*" | OCR warning appears when sourcing from low-quality scanned PDFs; does not appear for clean documents. |
| | **3c.** Create the public API wrapper `query_graph(question: str, chat_history: list[dict] | None = None) -> AssistantResponse` in `rag/graph.py` that handles graph compilation, invocation, and error handling with `try...except`. This is the single entry point for Step 6 (API) and Step 7 (Odoo module). | `query_graph()` callable; returns `AssistantResponse` or raises a clean exception. |
| | **3d.** Write unit tests in `tests/test_graph.py`: (1) test schema validation, (2) test fallback with empty context, (3) test OCR warning injection, (4) test that `query_graph` returns valid `AssistantResponse`. Use mocks for the Groq API to avoid burning tokens in CI. | `tests/test_graph.py` with ≥ 6 test cases; all pass with `pytest`. |

---

### Day 4: Benchmark, Tuning & Documentation

| Day | Task | Deliverable |
|-----|------|-------------|
| Day 4 | **4a.** Create `tests/eval_rag.py` — run the full RAG pipeline (not just retrieval) on doc + code questions from `tests/benchmark_questions.json`. For each question, check: (1) does the answer contain the expected keywords from `expected_answer_contains`? (2) does `sources` reference the correct `source_reference`? Score = % of questions with both criteria met. Target: ≥ 90%. | `tests/eval_rag.py` created; benchmark runner produces a scored report. |
| | **4b.** Test conversation memory with 5 multi-turn scenarios covering: (1) follow-up clarification, (2) topic switch, (3) reference to earlier answer, (4) correction request, (5) mixed doc+code conversation. | 5 multi-turn test scenarios pass; memory doesn't leak across unrelated topics. |
| | **4c.** Prompt tuning: if benchmark < 90%, adjust temperature, `max_tokens`, system prompt phrasing, and `top_k` until target is met. Document each tuning attempt and its effect on score. | Tuning log captured; final score ≥ 90%. |
| | **4d.** Generate final evaluation report in `captures/rag_eval_v1.md` with: configuration table, overall score, per-category breakdown (doc/code/hors_périmètre), latency stats, example good/bad answers, and memory test results. Archive the legacy `rag/pipeline.py` (rename to `rag/pipeline_legacy.py`). | `captures/rag_eval_v1.md` committed; legacy pipeline archived; Step 4 complete. |

---

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `rag/schemas.py` | **Create** | `AssistantResponse`, `SourceReference` Pydantic models |
| `rag/graph.py` | **Create** | LangGraph `StateGraph` with retrieve/generate/format nodes + `query_graph()` wrapper |
| `rag/prompts.py` | **Create** | System prompt (French), user prompt builder |
| `rag/pipeline.py` → `rag/pipeline_legacy.py` | **Rename** | Archive old pipeline |
| `tests/test_graph.py` | **Create** | Unit tests for graph, schemas, fallback, OCR |
| `tests/eval_rag.py` | **Create** | Full RAG benchmark runner |
| `captures/rag_eval_v1.md` | **Create** | Evaluation report |
| `requirements.txt` | **Modify** | Add `langchain-groq`, `langgraph`, `langchain` |

---

## Success Criteria

- [ ] `query_graph("Comment créer une facture ?")` returns a valid `AssistantResponse` with sources
- [ ] Fallback message when no relevant context is found
- [ ] OCR warning appended when sourcing from low-quality scans
- [ ] 3-turn conversation memory works
- [ ] ≥ 90% correctly sourced answers on `benchmark_questions.json`
- [ ] All tests in `tests/test_graph.py` pass
- [ ] Report saved to `captures/rag_eval_v1.md`
