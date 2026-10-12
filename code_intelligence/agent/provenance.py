"""Provenance footer of a code-intelligence answer: states what the answer rests on."""

from core.evidence.evidence_sufficiency import EvidenceSufficiencyResult, EvidenceSufficiencyStatus

GRAPH_SOURCE_FOOTER = "[Source: Graphe de Connaissances Code Intelligence]"
UNSUPPORTED_SOURCE_FOOTER = (
    "[Source: connaissances générales du modèle de langage. "
    "Aucune preuve retrouvée dans le graphe de votre instance : à vérifier avant usage.]"
)


def source_footer(sufficiency: EvidenceSufficiencyResult) -> str:
    """The graph label only when at least one observation supports the answer.

    A captured execution failure keeps the graph label: its own notice already
    tells the reader that the investigation did not complete.
    """
    unsupported = (
        sufficiency.status is EvidenceSufficiencyStatus.INSUFFICIENT
        and sufficiency.relevant_observation_count == 0
        and not sufficiency.has_execution_failure
    )
    return UNSUPPORTED_SOURCE_FOOTER if unsupported else GRAPH_SOURCE_FOOTER
