"""Asynchronous query endpoints (/api/v1/ask/jobs) for the MIRO assistant."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage

from api.ask_jobs import DuplicateJobError, JobCapacityError, ask_jobs
from api.auth import get_current_user
from api.language import request_language
from api.public_errors import public_http_exception
from api.schemas import AskJobAcceptedV1, AskJobRequestV1, AskJobStatusV1, AskRequestV1, AskResponseV1
from core.graph.graph import query_graph
from core.session.session_store import get_session, update_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1')


def _answer_question(request: AskRequestV1, accept_language: str | None, user: dict) -> AskResponseV1:
    """Run the LangGraph agent for one authenticated question; only raises HTTPException."""
    try:
        if not request.question.strip():
            raise HTTPException(status_code=400, detail='Empty question provided.')

        uid = user['uid']
        chat_history = get_session(request.session_id, owner_uid=uid)

        api_key = user.get('api_key')
        token_company_id = user.get('company_id')
        company_id = request.company_id if token_company_id is None else int(token_company_id)
        if not api_key:
            logger.warning('No Odoo API key in the JWT for uid=%s: ERP calls will be refused.', uid)
            if request.source_mode == 'system':
                raise HTTPException(
                    status_code=403,
                    detail='The Odoo user identity is unavailable for this system request.',
                )

        response = query_graph(
            question=request.question,
            chat_history=chat_history,
            uid=uid,
            api_key=api_key,
            source_mode=request.source_mode,
            language=request_language(request.language, accept_language),
            company_id=company_id,
            company_ids=[company_id],
            db=user.get('db'),
        )

        update_session(
            request.session_id,
            chat_history + [HumanMessage(content=request.question), AIMessage(content=response.answer)],
            owner_uid=uid,
        )

        return AskResponseV1(
            answer=response.answer,
            question=request.question,
            session_id=request.session_id,
            sources=[source.model_dump() for source in response.sources],
            confidence=response.confidence,
            ocr_warning=response.ocr_warning,
            route=response.route,
            evidence_dossier=[evidence.model_dump() for evidence in response.evidence_dossier],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('MIRO question processing failed.')
        raise public_http_exception(exc) from None


@router.post('/ask/jobs', response_model=AskJobAcceptedV1, status_code=202)
def submit_ask_job(
    request: AskJobRequestV1,
    http_request: Request,
    user: dict = Depends(get_current_user),
):
    """Start a question in the background; poll GET /api/v1/ask/jobs/{job_id} for the answer."""
    accept_language = http_request.headers.get('accept-language')
    try:
        ask_jobs.submit(
            request.job_id, user['uid'], request.question,
            lambda: _answer_question(request, accept_language, user),
        )
    except DuplicateJobError:
        raise HTTPException(status_code=409, detail='Job already submitted.') from None
    except JobCapacityError:
        raise HTTPException(status_code=429, detail='Too many questions in progress.') from None
    return AskJobAcceptedV1(job_id=request.job_id)


@router.get('/ask/jobs/{job_id}', response_model=AskJobStatusV1)
def get_ask_job(job_id: str, user: dict = Depends(get_current_user)):
    job = ask_jobs.get(job_id, user['uid'])
    if job is None:
        raise HTTPException(status_code=404, detail='Unknown job.')
    return AskJobStatusV1(
        status=job.status, question=job.question, elapsed_ms=job.elapsed_ms,
        result=job.result, error_status=job.error_status, error_detail=job.error_detail,
    )
