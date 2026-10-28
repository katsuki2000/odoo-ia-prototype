"""Main query endpoint (/api/v1/ask) for the MIRO assistant."""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage, AIMessage

from api.ask_jobs import DuplicateJobError, JobCapacityError, ask_jobs
from api.auth import get_current_user
from api.public_errors import public_error_details
from api.schemas import AskJobAcceptedV1, AskJobRequestV1, AskJobStatusV1, AskRequestV1, AskResponseV1
from core.graph.graph import query_graph
from core.session.session_store import get_session, update_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_language_tag(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().replace("-", "_")
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:_[A-Za-z0-9]{1,8})*", normalized):
        return None
    return normalized


def _request_language(explicit: str | None, accept_language: str | None) -> str | None:
    language = _normalize_language_tag(explicit)
    if language:
        return language
    candidates = []
    for position, item in enumerate((accept_language or "").split(",")):
        parts = [part.strip() for part in item.split(";")]
        language = _normalize_language_tag(parts[0])
        if not language:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            candidates.append((-quality, position, language))
    return min(candidates)[2] if candidates else None


def _answer_question(request: AskRequestV1, accept_language: str | None, user: dict) -> AskResponseV1:
    """Run the LangGraph agent for one authenticated question; only raises HTTPException."""
    try:
        if not request.question or not request.question.strip():
            raise HTTPException(status_code=400, detail="Empty question provided.")

        token_uid = user.get("uid")
        if token_uid is None:
            raise HTTPException(status_code=401, detail="Token missing uid")
        request.user_uid = token_uid

        session = get_session(request.session_id, owner_uid=token_uid)
        chat_history = session["chat_history"]
        last_route = session["last_route"]

        token_api_key = user.get("api_key")
        token_groups = user.get("groups") or []
        token_company_id = user.get("company_id")
        if token_company_id is not None:
            company_id = int(token_company_id)
        else:
            company_id = int(request.company_id)
        request_language = _request_language(request.language, accept_language)
        if not token_api_key:
            logger.warning(
                "No real Odoo API key in JWT for uid=%s -- ERP/XML-RPC calls "
                "will be refused; documentation answers are unaffected.", token_uid,
            )

        response = query_graph(
            question=request.question,
            chat_history=chat_history,
            uid=request.user_uid,
            api_key=token_api_key,
            user_groups=token_groups,
            skills=request.skills,
            last_route=last_route,
            source_mode=request.source_mode,
            language=request_language,
            company_id=company_id,
            company_ids=[company_id],
        )

        if response.answer == "Une erreur interne s'est produite lors de l'exécution du pipeline.":
            raise HTTPException(status_code=503, detail="Service Unavailable: Upstream provider down.")

        updated_history = chat_history + [
            HumanMessage(content=request.question),
            AIMessage(content=response.answer),
        ]
        update_session(
            request.session_id, updated_history,
            getattr(response, "route", None) or last_route,
            owner_uid=token_uid,
        )

        omitted_list = []
        if hasattr(response, "omitted_for_authorization") and response.omitted_for_authorization:
            omitted_list = [
                o.model_dump() if hasattr(o, "model_dump") else o
                for o in response.omitted_for_authorization
            ]

        evidence_dossier_list = []
        if hasattr(response, "evidence_dossier") and response.evidence_dossier:
            evidence_dossier_list = [
                e.model_dump() if hasattr(e, "model_dump") else e
                for e in response.evidence_dossier
            ]

        return AskResponseV1(
            answer=response.answer,
            question=request.question,
            session_id=request.session_id,
            sources=[s.model_dump() for s in response.sources] if hasattr(response, 'sources') else [],
            confidence=response.confidence if hasattr(response, 'confidence') else 1.0,
            ocr_warning=response.ocr_warning if hasattr(response, 'ocr_warning') else False,
            route=getattr(response, "route", None),
            omitted_for_authorization=omitted_list,
            evidence_dossier=evidence_dossier_list,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MIRO question processing failed.")
        statusCode, detail = public_error_details(exc)
        raise HTTPException(status_code=statusCode, detail=detail) from None


@router.post("/api/v1/ask", response_model=AskResponseV1)
def ask_question_v1(
    request: AskRequestV1,
    http_request: Request,
    user: dict = Depends(get_current_user),
):
    """V1 endpoint for asking questions, using the LangGraph agent."""
    return _answer_question(request, http_request.headers.get("accept-language"), user)


@router.post("/api/v1/ask/jobs", response_model=AskJobAcceptedV1, status_code=202)
def submit_ask_job(
    request: AskJobRequestV1,
    http_request: Request,
    user: dict = Depends(get_current_user),
):
    """Start a question in the background; poll GET /api/v1/ask/jobs/{job_id} for the answer."""
    accept_language = http_request.headers.get("accept-language")
    try:
        ask_jobs.submit(
            request.job_id, user["uid"], request.question,
            lambda: _answer_question(request, accept_language, user),
        )
    except DuplicateJobError:
        raise HTTPException(status_code=409, detail="Job already submitted.") from None
    except JobCapacityError:
        raise HTTPException(status_code=429, detail="Too many questions in progress.") from None
    return AskJobAcceptedV1(job_id=request.job_id)


@router.get("/api/v1/ask/jobs/{job_id}", response_model=AskJobStatusV1)
def get_ask_job(job_id: str, user: dict = Depends(get_current_user)):
    job = ask_jobs.get(job_id, user["uid"])
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return AskJobStatusV1(
        status=job.status, question=job.question, elapsed_ms=job.elapsed_ms,
        result=job.result, error_status=job.error_status, error_detail=job.error_detail,
    )
