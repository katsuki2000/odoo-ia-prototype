"""Main query endpoint (/api/v1/ask) for the MIRO assistant."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, AIMessage

from api.auth import get_current_user
from api.schemas import AskRequestV1, AskResponseV1
from core.graph import query_graph
from core.session_store import get_session, update_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/v1/ask", response_model=AskResponseV1)
def ask_question_v1(request: AskRequestV1, user: dict = Depends(get_current_user)):
    """V1 endpoint for asking questions, using the LangGraph agent."""
    session = get_session(request.session_id)
    chat_history = session["chat_history"]
    last_route = session["last_route"]
    last_resolved_concept = session["resolved_concept"]

    try:
        if not request.question or not request.question.strip():
            raise HTTPException(status_code=400, detail="Empty question provided.")

        token_uid = user.get("uid")
        if token_uid:
            request.user_uid = token_uid

        token_api_key = user.get("api_key")
        token_groups = user.get("groups") or []
        if not token_api_key:
            logger.warning(
                "No real Odoo API key in JWT for uid=%s -- ERP/XML-RPC calls "
                "will fall back to the admin credential.", token_uid,
            )

        response = query_graph(
            question=request.question,
            chat_history=chat_history,
            uid=request.user_uid,
            api_key=token_api_key,
            user_groups=token_groups,
            skills=request.skills,
            last_route=last_route,
            last_resolved_concept=last_resolved_concept,
            active_model=request.active_model,
            active_id=request.active_id,
        )

        if response.answer == "Une erreur interne s'est produite lors de l'exécution du pipeline.":
            raise HTTPException(status_code=503, detail="Service Unavailable: Upstream provider down.")

        updated_history = chat_history + [
            HumanMessage(content=request.question),
            AIMessage(content=response.answer),
        ]
        update_session(
            request.session_id, updated_history,
            getattr(response, "resolved_concept", None) or last_resolved_concept,
            getattr(response, "route", None) or last_route,
        )

        omitted_list = []
        if hasattr(response, "omitted_for_authorization") and response.omitted_for_authorization:
            omitted_list = [
                o.model_dump() if hasattr(o, "model_dump") else o
                for o in response.omitted_for_authorization
            ]

        return AskResponseV1(
            answer=response.answer,
            question=request.question,
            session_id=request.session_id,
            sources=[s.model_dump() for s in response.sources] if hasattr(response, 'sources') else [],
            confidence=response.confidence if hasattr(response, 'confidence') else 1.0,
            ocr_warning=response.ocr_warning if hasattr(response, 'ocr_warning') else False,
            route=getattr(response, "route", None),
            evidence_status=getattr(response, "evidence_status", None),
            resolved_concept=getattr(response, "resolved_concept", None),
            omitted_for_authorization=omitted_list,
            investigation_plan=getattr(response, "investigation_plan", None),
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg or "xmlrpc" in error_msg:
            raise HTTPException(status_code=503, detail=f"Service Unavailable: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RAG Graph error: {str(e)}")
