# -*- coding: utf-8 -*-
"""
Bloc P1 -- reorientation CI-d'abord / RAG-en-dernier-recours (Tranche 3,
todo/contexte.txt section 405-409).

Couverture dediee du cablage trouve deja ecrit sur le disque (Tranche 2,
constat section 408) et jusqu'ici sans aucun test dedie (recherche par
pattern `*ci_evidence*`/`*tranche_2*` sur l'arborescence complete, aucun
resultat) :

  - core/graph.py::ci_evidence_decision()   -- l'edge conditionnelle post-CI
    qui decide format_output (SUFFICIENT) vs generate/RAG (!= SUFFICIENT).
  - core/graph.py::build_graph()            -- le cablage structurel reel du
    StateGraph (qui va vers code_intelligence_agent, qui va vers
    orm_agent_loop, que hybrid_node n'est plus un noeud du graphe).
  - core/graph.py::format_output()          -- la distinction
    `ci_fell_back_to_rag` (le drapeau qui evite d'attribuer a tort les
    chunks universels de retrieve() a une reponse que CI a produite
    lui-meme quand son verdict est SUFFICIENT).

Ni classify_question_intent()/resolve_question_intent() (deja couverts par
tests/test_j18_routing_fewshot.py, code_intelligence/tests/test_intent_llm_
classifier_and_resolution.py) ni assess_evidence_sufficiency() elle-meme
(deja couverte par code_intelligence/tests/test_evidence_sufficiency.py,
12/12 confirme section 407) ne sont retestes ici -- ce fichier teste
uniquement le CABLAGE qui les relie, la seule couche encore non testee.
"""
import pytest

from core.graph.graph import (
    ci_evidence_decision,
    format_output,
    build_graph,
    hybrid_node,
)
from core.evidence.evidence_sufficiency import (
    assess_evidence_sufficiency,
    EvidenceSufficiencyStatus,
)
from core.schemas import AssistantResponse, QueryRoute


# ── A. ci_evidence_decision() -- edge conditionnelle post-CI ───────────────

def test_ci_evidence_decision_absent_key_stays_on_format_output():
    """Les 3 refus precoces de code_intelligence_agent (out-of-scope, prompt
    injection, extraction massive) retournent avant que
    assess_evidence_sufficiency() ne tourne jamais -- ci_evidence_sufficiency
    est donc absent du state pour ces cas. Ce sont des refus deliberes, pas
    des verdicts d'insuffisance de preuve : rejouer le RAG dessus serait
    activement faux, pas seulement redondant (docstring de la fonction)."""
    assert ci_evidence_decision({}) == "format_output"


def test_ci_evidence_decision_none_value_stays_on_format_output():
    """Meme garde-fou que ci-dessus, mais avec la cle presente et explicitement
    None plutot qu'absente -- les deux formes doivent etre traitees pareil."""
    assert ci_evidence_decision({"ci_evidence_sufficiency": None}) == "format_output"


def test_ci_evidence_decision_sufficient_without_doc_request_stays_on_format_output():
    state = {
        "question": "Qui peut valider une commande d'achat ?",
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.SUFFICIENT.value},
    }
    assert ci_evidence_decision(state) == "format_output"


def test_ci_evidence_decision_sufficient_with_doc_request_falls_back_to_generate():
    """Reproduit le scenario exact de todo/contexte.txt section 744 : le CI agent
    lit un hop unique hors-sujet (ex. odoo/CONTRIBUTING.rst pour une question sur
    "les regles de codage d'apres la documentation"), conclut en prose libre non
    couverte par les marqueurs fixes d'assess_evidence_sufficiency(), et est note
    SUFFICIENT a tort. Une demande documentaire explicite dans la question doit
    l'emporter meme sur un verdict SUFFICIENT -- CI n'a jamais acces au corpus
    documentaire, donc son propre verdict de suffisance ne dit rien de la
    pertinence du corpus RAG pour une question qui le demande explicitement."""
    state = {
        "question": "Quelles sont les regles de base en codage odoo d'apres la documentation ?",
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.SUFFICIENT.value},
    }
    assert ci_evidence_decision(state) == "generate"


def test_ci_evidence_decision_insufficient_without_doc_request_stays_on_format_output():
    """doc_rag is no longer an automatic fallback on insufficient CI evidence --
    without an explicit documentary anchor in the question, CI's own (insufficient)
    answer is kept as-is rather than silently replaced by generate()'s RAG output."""
    state = {
        "question": "Qui peut valider une commande d'achat ?",
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value},
    }
    assert ci_evidence_decision(state) == "format_output"


def test_ci_evidence_decision_insufficient_with_doc_request_falls_back_to_generate():
    """doc_rag intervenes only when explicitly requested -- an explicit documentary
    anchor (wiki/documentation/procedure/politique interne) is the sole trigger for
    the RAG fallback on insufficient CI evidence."""
    state = {
        "question": "Selon le wiki, qui peut valider une commande d'achat ?",
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value},
    }
    assert ci_evidence_decision(state) == "generate"


def test_ci_evidence_decision_conflicting_stays_on_format_output():
    """todo/contexte.txt sections 419-420 -- reversal of the earlier rule
    (see git history of this test): the user explicitly reformulated the
    desired role of CONFLICTING (section 419) -- it must never be silently
    arbitrated or hand it to the generic doc-RAG fallback, which has no
    knowledge of the two (or more) competing code-evidence facts that
    triggered it. code_intelligence_agent now builds its own final_answer
    for this case as a deterministic, non-arbitrating exposition of every
    disagreeing fact (ci_helpers.py::_format_conflicting_evidence_answer),
    so CONFLICTING gets its OWN dedicated destination here, identical to
    SUFFICIENT's -- no longer merged into INSUFFICIENT's path."""
    state = {"ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.CONFLICTING.value}}
    assert ci_evidence_decision(state) == "format_output"


def test_ci_evidence_decision_conflicting_is_traceable_not_silent(caplog):
    """Contrainte utilisateur explicite (section 419-420) : CONFLICTING ne
    doit pas disparaitre silencieusement du log au pretexte qu'il partage
    desormais sa destination avec SUFFICIENT -- le statut et les raisons
    doivent rester visibles pour que ce chemin dedie reste auditable comme
    un choix delibere, pas un accident de l'egalite de destination."""
    import logging
    state = {
        "ci_evidence_sufficiency": {
            "status": EvidenceSufficiencyStatus.CONFLICTING.value,
            "reasons": ["deux constats deterministes se contredisent (hypothetique)"],
        }
    }
    with caplog.at_level(logging.INFO):
        result = ci_evidence_decision(state)
    assert result == "format_output"
    assert any(
        "conflicting" in record.getMessage().lower()
        and "deux constats deterministes se contredisent" in record.getMessage()
        for record in caplog.records
    ), "le statut CONFLICTING et ses raisons doivent apparaitre dans le log, pas disparaitre silencieusement"


def test_ci_evidence_decision_insufficient_is_logged(caplog):
    import logging
    state = {
        "ci_evidence_sufficiency": {
            "status": EvidenceSufficiencyStatus.INSUFFICIENT.value,
            "reasons": ["no tool observations gathered (hop_count == 0)"],
        }
    }
    with caplog.at_level(logging.INFO):
        ci_evidence_decision(state)
    assert any("insufficient" in record.getMessage().lower() for record in caplog.records)


@pytest.mark.parametrize(
    "question,tool_observations,hop_count,final_answer,expected_decision",
    [
        # SUFFICIENT: au moins une observation pertinente, aucun marqueur
        # d'incertitude dans la reponse finale. Pas de requete documentaire
        # explicite -- sans objet ici, SUFFICIENT ne consulte jamais ce signal.
        (
            "Qui peut approuver un achat au-dela de 5000 ?",
            ["Verrou trouve : has_group('account.group_account_manager') requis au-dela de 5000."],
            1,
            "Le responsable comptable doit approuver au-dela de 5000.",
            "format_output",
        ),
        # INSUFFICIENT, question sans ancrage documentaire explicite : doc_rag
        # n'est plus un fallback automatique -- reste sur la reponse (insuffisante)
        # de CI plutot que de basculer silencieusement vers generate() (RAG).
        (
            "Qui peut approuver un achat au-dela de 5000 ?",
            [],
            0,
            "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question.",
            "format_output",
        ),
        # INSUFFICIENT, question sans ancrage documentaire explicite (outils
        # executes mais aucune observation pertinente, que des "not found").
        (
            "Qui peut approuver un achat au-dela de 5000 ?",
            ["Model 'custom.unknown.model' was not found in the indexed knowledge graph."],
            1,
            "Je n'ai pas trouve d'information pertinente.",
            "format_output",
        ),
        # INSUFFICIENT, mais question portant un ancrage documentaire explicite
        # ("selon le wiki") -- seul cas ou generate() (RAG) est autorise a tourner.
        (
            "Selon le wiki, qui peut approuver un achat au-dela de 5000 ?",
            [],
            0,
            "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question.",
            "generate",
        ),
    ],
)
def test_ci_evidence_decision_matches_assess_evidence_sufficiency_end_to_end(
    question, tool_observations, hop_count, final_answer, expected_decision,
):
    """Test d'integration cible (pas un mock) entre les deux fonctions reelles
    des Tranches 1 et 2 -- assess_evidence_sufficiency() (Tranche 1,
    core/evidence_sufficiency.py) produit le verdict, ci_evidence_decision()
    (Tranche 2, core/graph.py) le consomme via son .to_display_dict(), gate
    desormais par la presence d'un ancrage documentaire explicite dans la
    question (doc_rag n'est plus un fallback automatique). Ce test attrape
    une derive de schema entre les deux modules qu'un test purement unitaire
    sur des dicts a la main (groupe A ci-dessus) ne verrait pas -- ex. un
    renommage de champ 'status' d'un cote sans l'autre."""
    result = assess_evidence_sufficiency(tool_observations, hop_count, final_answer)
    state = {"question": question, "ci_evidence_sufficiency": result.to_display_dict()}
    assert ci_evidence_decision(state) == expected_decision


# ── B. build_graph() -- cablage structurel du StateGraph ────────────────────

@pytest.fixture(scope="module")
def compiled_graph_view():
    """Compile le graphe reel (build_graph()) et retourne sa representation
    introspectable (app.get_graph()) -- pas un mock, le vrai cablage produit
    par ce module. Necessite le graphe Code Intelligence reel et les
    dependances du projet (marque integration implicitement par cette
    dependance, comme test_bloc_p1_j7_plan_route_conflict.py)."""
    app = build_graph()
    return app.get_graph()


def _edge_targets(graph_view, source: str) -> set:
    return {edge.target for edge in graph_view.edges if edge.source == source}


@pytest.mark.integration
def test_route_dispatches_documentaire_hybride_code_intelligence_to_ci_agent(compiled_graph_view):
    """Contrainte utilisateur (1) : le routeur amont ne doit plus etre le
    decideur principal a 4 branches -- DOCUMENTAIRE/HYBRIDE/CODE_INTELLIGENCE
    doivent tous les 3 converger vers le meme noeud code_intelligence_agent
    cote graphe, quelle que soit la classification amont."""
    targets = _edge_targets(compiled_graph_view, "route")
    assert targets == {"code_intelligence_agent", "orm_agent_loop"}, (
        f"route() ne doit dispatcher que vers ces 2 noeuds de premier niveau "
        f"(CI ou ERP pur), pas vers 4 branches distinctes -- trouve : {targets}"
    )


@pytest.mark.integration
def test_donnees_erp_is_the_only_route_reaching_orm_agent_loop_directly(compiled_graph_view):
    """Le seul chemin de premier niveau vers orm_agent_loop doit venir de
    route -- confirme que DONNEES_ERP reste le seul cas qui court-circuite
    code_intelligence_agent, conformement au plan (Domaine B, donnees
    pures)."""
    incoming_sources = {edge.source for edge in compiled_graph_view.edges if edge.target == "orm_agent_loop"}
    assert incoming_sources == {"route"}


@pytest.mark.integration
def test_code_intelligence_agent_only_reaches_verify_answer_or_generate(compiled_graph_view):
    """Post-CI, il ne doit exister que 2 destinations possibles -- pas de
    3e branche cachee reintroduite en aval. Verrouille la forme de l'edge
    conditionnelle cablee par ci_evidence_decision() ; la cle historique
    "format_output" mene desormais a la verification (section 1129)."""
    targets = _edge_targets(compiled_graph_view, "code_intelligence_agent")
    assert targets == {"verify_answer", "generate"}


@pytest.mark.integration
def test_orm_agent_loop_reaches_verify_answer_directly_bypassing_evidence_gate(compiled_graph_view):
    """Le chemin ERP pur (Domaine B) ne passe jamais par
    assess_evidence_sufficiency()/ci_evidence_decision() -- c'est un chemin
    de premier niveau distinct, pas un cas particulier de CI. Une seule
    destination attendue (la verification, section 1129), jamais 'generate'."""
    targets = _edge_targets(compiled_graph_view, "orm_agent_loop")
    assert targets == {"verify_answer"}


@pytest.mark.integration
def test_generate_reaches_verify_answer(compiled_graph_view):
    assert _edge_targets(compiled_graph_view, "generate") == {"verify_answer"}


@pytest.mark.integration
def test_hybrid_node_is_not_wired_into_the_compiled_graph(compiled_graph_view):
    """hybrid_node (erp_data/orm_agent_node.py) reste importable pour
    compatibilite ascendante (verifie par l'import en tete de ce fichier)
    mais ne doit plus etre un noeud du graphe compile -- son role est repris
    naturellement par le fallback CI -> RAG (module docstring de
    core/graph.py)."""
    assert callable(hybrid_node), "hybrid_node doit rester importable/appelable independamment du graphe"
    assert "hybrid_node" not in compiled_graph_view.nodes


# ── C. format_output() -- distinction ci_fell_back_to_rag ──────────────────

def _low_ocr_chunk():
    return {
        "document": "texte numerise",
        "metadata": {"source": "scan.pdf", "type": "pdf", "ocr_quality": "low"},
    }


def test_format_output_no_ocr_leak_when_ci_answer_is_sufficient():
    """Regression cible directement citee par le docstring de format_output() :
    quand code_intelligence_agent a tourne ce tour ET que son verdict est
    SUFFICIENT (donc generate() n'a jamais produit cette reponse), les
    chunks universels de retrieve() -- sans rapport avec les observations
    d'outil de CI -- ne doivent PAS se voir attribuer un avertissement OCR
    qui ne les concerne pas."""
    state = {
        "response": AssistantResponse(answer="Reponse de CI.", confidence=1.0, sources=[]),
        "retrieved_chunks": [_low_ocr_chunk()],
        "route": QueryRoute.CODE_INTELLIGENCE.value,
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.SUFFICIENT.value},
    }
    result = format_output(state)
    assert result["response"].ocr_warning is not True
    assert "qualité de lecture est limitée" not in result["response"].answer


def test_format_output_ocr_warning_applies_when_ci_fell_back_to_rag():
    """Cas symetrique : CI a tourne mais son verdict est != SUFFICIENT ET la
    question portait un ancrage documentaire explicite (seul cas ou generate()
    est autorise a tourner sous le nouveau gating) -- l'avertissement OCR
    redevient legitime, meme si route est reste 'code_intelligence' (le
    routeur amont ne reflete plus qui a produit la reponse sous le cablage
    CI-d'abord)."""
    state = {
        "question": "Selon le wiki, quelle est la procedure ?",
        "response": AssistantResponse(answer="Reponse RAG de repli.", confidence=0.5, sources=[]),
        "retrieved_chunks": [_low_ocr_chunk()],
        "route": QueryRoute.CODE_INTELLIGENCE.value,
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value},
    }
    result = format_output(state)
    assert result["response"].ocr_warning is True
    assert "qualité de lecture est limitée" in result["response"].answer


def test_format_output_insufficient_without_doc_request_does_not_fall_back_to_rag():
    """doc_rag n'est plus un fallback automatique : meme verdict INSUFFICIENT,
    mais sans ancrage documentaire explicite dans la question -- generate()
    n'a jamais tourne (ci_evidence_decision() serait reste sur format_output),
    donc les chunks universels de retrieve() ne doivent pas se voir attribuer
    un avertissement OCR qui appartient a une reponse RAG jamais produite."""
    state = {
        "question": "Qui peut valider une commande d'achat ?",
        "response": AssistantResponse(answer="Reponse (insuffisante) de CI.", confidence=0.2, sources=[]),
        "retrieved_chunks": [_low_ocr_chunk()],
        "route": QueryRoute.CODE_INTELLIGENCE.value,
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value},
    }
    result = format_output(state)
    assert result["response"].ocr_warning is not True
    assert "qualité de lecture est limitée" not in result["response"].answer


def test_format_output_documentaire_route_without_ci_sufficiency_no_longer_leaks_ocr():
    """todo/contexte.txt section 414 -- ce test remplace l'ancienne version qui
    verrouillait (a tort) une fuite comme "non-regression du chemin DOCUMENTAIRE
    historique". Sous le graphe compile actuel (build_graph(), sections 405-408),
    route == 'documentaire' + chunks presents + ci_evidence_sufficiency ABSENT
    n'est plus atteignable que via l'un des 3 refus precoces de
    code_intelligence_agent (out-of-scope / prompt-injection / extraction
    massive -- les seuls chemins qui retournent avant qu'assess_evidence_
    sufficiency() ne tourne). Dans ce cas, `response` porte un message de
    refus delibere, sans aucun rapport avec les chunks universels de
    retrieve() -- l'avertissement OCR NE DOIT PAS s'y attacher. L'ancienne
    assertion (ocr_warning is True) reproduisait exactement ce faux positif."""
    state = {
        "response": AssistantResponse(answer="Cette question sort du perimetre de MIRO AI.", confidence=0.0, sources=[]),
        "retrieved_chunks": [_low_ocr_chunk()],
        "route": QueryRoute.DOCUMENTAIRE.value,
    }
    result = format_output(state)
    assert result["response"].ocr_warning is not True
    assert "qualité de lecture est limitée" not in result["response"].answer


def test_format_output_conflicting_does_not_count_as_fell_back_to_rag():
    """todo/contexte.txt sections 419-420: reversal of the earlier version of
    this test. CONFLICTING no longer shares INSUFFICIENT's '!= SUFFICIENT'
    treatment here -- code_intelligence_agent's own answer for a CONFLICTING
    verdict is now a deterministic dual-evidence exposition it produced
    itself (ci_helpers.py::_format_conflicting_evidence_answer), NOT
    generate()'s RAG output (ci_evidence_decision() routes CONFLICTING to
    format_output directly, never to generate()) -- so the universal
    retrieve() chunks' OCR warning must NOT attach to it, exactly the same
    false-attribution this module's docstring already forbids for the
    SUFFICIENT case just above."""
    state = {
        "response": AssistantResponse(answer="Preuves contradictoires exposees par CI.", confidence=0.5, sources=[]),
        "retrieved_chunks": [_low_ocr_chunk()],
        "route": QueryRoute.CODE_INTELLIGENCE.value,
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.CONFLICTING.value},
    }
    result = format_output(state)
    assert result["response"].ocr_warning is not True
    assert "qualité de lecture est limitée" not in result["response"].answer


def _insufficient_state(question):
    return {
        "question": question,
        "response": AssistantResponse(answer="Reponse.", confidence=0.5, sources=[]),
        "retrieved_chunks": [],
        "route": QueryRoute.CODE_INTELLIGENCE.value,
        "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value},
    }


def test_format_output_flags_rag_fallback_only_when_rag_produced_the_answer():
    fell_back = format_output(_insufficient_state("Selon le wiki, quelle est la procedure ?"))
    stayed = format_output(_insufficient_state("Qui peut approuver une commande ?"))
    assert fell_back["response"].rag_fallback is True
    assert stayed["response"].rag_fallback is False
