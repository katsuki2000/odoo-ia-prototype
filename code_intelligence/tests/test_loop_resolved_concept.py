from dataclasses import asdict

from api.schemas import AskResponseV1
from code_intelligence.agent.resolution.matching import ResolvedConcept
from core.graph.graph_nodes import format_output
from core.schemas import AssistantResponse


def _loop_concept() -> dict:
    return asdict(
        ResolvedConcept(
            user_term="validation des conges",
            resolved_models=["hr.leave"],
            confidence=0.6,
            source_step="llm_arbitration",
            is_resolved=True,
        )
    )


def test_format_output_exposes_the_loop_concept_next_to_the_routing_concept():
    routing_concept = {"is_resolved": False, "source_step": "unresolved", "resolved_models": []}
    state = {
        "response": AssistantResponse(answer="ok", confidence=1.0),
        "resolved_concept": routing_concept,
        "loop_resolved_concept": _loop_concept(),
    }

    response = format_output(state)["response"]

    assert response.resolved_concept == routing_concept
    assert response.loop_resolved_concept["resolved_models"] == ["hr.leave"]
    assert response.loop_resolved_concept["source_step"] == "llm_arbitration"


def test_loop_concept_is_none_when_the_loop_did_not_run():
    response = format_output({"response": AssistantResponse(answer="ok", confidence=1.0)})["response"]

    assert response.loop_resolved_concept is None


def test_api_response_carries_the_loop_concept():
    payload = AskResponseV1(answer="a", question="q", session_id="s", loop_resolved_concept=_loop_concept())

    assert payload.model_dump()["loop_resolved_concept"]["resolved_models"] == ["hr.leave"]
    assert AskResponseV1(answer="a", question="q", session_id="s").loop_resolved_concept is None
