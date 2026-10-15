"""
core/graph_nodes.py

Pipeline nodes and conditional edge decisions for the LangGraph workflow:
out_of_scope_gate, retrieve, format_output.
"""

import logging
import sys

from config.settings import USE_RERANKER
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from core.evidence.evidence_sufficiency import EvidenceSufficiencyStatus
from core.schemas import (
    AssistantResponse,
    SourceReference,
    source_display_title,
)
from core.guardrails import OUT_OF_SCOPE_ANSWER, is_out_of_scope
from core.routing.routing import _fold_accents
from core.state import RAGState
from code_intelligence.agent.investigation_classifier import has_documentary_anchor

logger = logging.getLogger(__name__)


def out_of_scope_gate(state: RAGState) -> dict:
    """
    Deterministic pre-retrieval gate for questions matching OUT_OF_SCOPE_TERMS.
    Intercepts them before retrieve() runs.
    """
    question = state.get("question", "")
    if not is_out_of_scope(question):
        return {}

    logger.info("Node [out_of_scope_gate]: out-of-scope question detected -- skipping retrieve()/route()")
    response = AssistantResponse(
        answer=OUT_OF_SCOPE_ANSWER,
        sources=[],
        confidence=0.0,
    )
    return {"response": response, "route": "out_of_scope", "retrieved_chunks": [], "investigation_plan": None}


def out_of_scope_decision(state: RAGState) -> str:
    """Return the conditional-edge key out of out_of_scope_gate."""
    return "format_output" if state.get("response") is not None else "route"


def _has_explicit_doc_request(state: RAGState) -> bool:
    """Whether the question explicitly asks for documentation (wiki, guide
    utilisateur, procedure, politique interne...). Single gate shared by
    ci_evidence_decision() and format_output() to decide whether the RAG
    fallback (generate()) is allowed to run at all -- doc_rag is no longer
    an automatic fallback on insufficient CI evidence, only an explicit,
    user-requested branch."""
    question_folded = _fold_accents(state.get("question", "").lower())
    return has_documentary_anchor(question_folded)


def answered_by_documents(state: RAGState) -> bool:
    """Whether this turn was routed to the documentation corpus."""
    return state.get("route") == "documentaire" or state.get("source_mode") == "documentation"


def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)

    # Support test suites that dynamically mock core.graph.graph.get_retriever / search_retrieve
    graph_mod = sys.modules.get("core.graph.graph")
    _get_retriever = getattr(graph_mod, "get_retriever", get_retriever) if graph_mod else get_retriever
    _search_retrieve = getattr(graph_mod, "search_retrieve", search_retrieve) if graph_mod else search_retrieve

    try:
        chroma_manager, bm25_index = _get_retriever()
        chunks = _search_retrieve(
            query=question,
            top_k=10,
            chroma_manager=chroma_manager,
            bm25_index=bm25_index,
            use_reranker=USE_RERANKER,
        )
    except Exception as e:
        logger.error("Error during retrieval: %s", e)
        chunks = []

    return {"retrieved_chunks": chunks}


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (OCR warnings, sources fallback)."""
    logger.info("Node [format_output]: Formatting final response")

    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    route = state.get("route")
    ci_sufficiency = state.get("ci_evidence_sufficiency")

    # todo/contexte.txt section 744: an explicit documentary request wins over ANY CI evidence status.
    documentation_route = answered_by_documents(state)

    if response:
        response.route = route
        response.resolved_concept = state.get("resolved_concept")
        response.evidence_status = state.get("evidence_status")
        response.loop_resolved_concept = state.get("loop_resolved_concept")
        response.investigation_plan = state.get("investigation_plan")
        response.ci_evidence_sufficiency = ci_sufficiency
        response.rag_fallback = False

    if response and chunks and documentation_route:
        primary_chunk = chunks[0]
        primary_metadata = primary_chunk.get("metadata") or {}
        primary_type = primary_metadata.get("type", "")
        has_low_ocr = (
            primary_metadata.get("ocr_quality") == "low"
            and primary_type in ("doc_pdf", "pdf")
        )
        if has_low_ocr:
            response.ocr_warning = True
            response.answer += "\n\nAttention : cette information provient d'un document numérisé dont la qualité de lecture est limitée."

        if not response.sources and state.get("sources_fallback_eligible"):
            sources = []
            for chunk in chunks:
                meta = chunk.get("metadata") or {}
                doc = chunk.get("document", "")
                snippet = doc[:100] + "..." if len(doc) > 100 else doc

                sources.append(SourceReference(
                    source=meta.get("source", "unknown"),
                    doc_type=meta.get("type", "document"),
                    title=source_display_title(meta),
                    snippet=snippet,
                ))
            response.sources = sources


    return {"response": response}


def ci_evidence_decision(state: RAGState) -> str:
    """
    Post-CI conditional edge.

    todo/contexte.txt section 744 (pmm mandate): an explicit documentary request
    in the question (wiki/documentation/procedure/politique interne) now ALWAYS
    falls back to generate() (RAG), regardless of CI's own evidence sufficiency
    status -- SUFFICIENT and CONFLICTING included, not just INSUFFICIENT. Root
    cause that prompted this: CI has no access to the document corpus at all, so
    a CI verdict that looks structurally sufficient (a tool ran cleanly, no
    error) can still be entirely off-topic for a question that explicitly asks
    what the documentation says -- see section 744 for a reproduced case (CI
    read an unrelated source file, concluded "no information found" in free
    prose not covered by assess_evidence_sufficiency's fixed canned-string
    markers, and was scored SUFFICIENT, silently blocking a RAG corpus that did
    contain the answer).

    Absent an explicit documentary request, doc_rag remains a non-automatic
    branch exactly as before section 744: SUFFICIENT and CONFLICTING keep CI's
    own answer, and INSUFFICIENT (with or without an execution failure) also
    stays on CI's own answer when nothing in the question asked for documentation.
    """
    if state.get("source_mode") == "documentation":
        return "generate"

    sufficiency = state.get("ci_evidence_sufficiency")
    if not sufficiency:
        return "format_output"

    status = sufficiency.get("status")

    if answered_by_documents(state):
        logger.info(
            "Node [route: post-CI]: explicit documentary request in the question -- falling back to "
            "RAG (generate) regardless of CI evidence sufficiency=%s (section 744). reasons=%s",
            status, sufficiency.get("reasons"),
        )
        return "generate"

    if status == EvidenceSufficiencyStatus.SUFFICIENT.value:
        return "format_output"

    if status == EvidenceSufficiencyStatus.CONFLICTING.value:
        logger.info(
            "Node [route: post-CI]: evidence sufficiency=%s -- dedicated conflicting-evidence path, "
            "staying on code_intelligence_agent's own dual-evidence answer. reasons=%s",
            status, sufficiency.get("reasons"),
        )
        return "format_output"

    if status == EvidenceSufficiencyStatus.INSUFFICIENT.value and sufficiency.get("has_execution_failure"):
        logger.info(
            "Node [route: post-CI]: evidence sufficiency=%s with has_execution_failure=True -- "
            "dedicated execution-failure path, staying on code_intelligence_agent's own answer. reasons=%s",
            status, sufficiency.get("reasons"),
        )
        return "format_output"

    logger.info(
        "Node [route: post-CI]: evidence sufficiency=%s, no explicit documentary request in the question -- "
        "doc_rag is not an automatic fallback, staying on code_intelligence_agent's own answer. reasons=%s",
        status, sufficiency.get("reasons"),
    )
    return "format_output"
