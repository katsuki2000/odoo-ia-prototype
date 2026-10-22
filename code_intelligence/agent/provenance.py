"""Provenance footer of a code-intelligence answer: states what the answer rests on."""

import re

from core.evidence.evidence_sufficiency import EvidenceSufficiencyResult, EvidenceSufficiencyStatus

GRAPH_SOURCE_FOOTER = "[Source: Système]"
UNSUPPORTED_SOURCE_FOOTER = (
    "[Source: connaissances générales du modèle de langage. "
    "Aucune preuve retrouvée dans le graphe de l'instance : à vérifier avant usage.]"
)
_GROUP_XMLID_RE = re.compile(r'\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b', re.IGNORECASE)


def _scoped_raw_tool_output(observations, models, target_models):
    if not target_models:
        return '\n\n'.join(observations)
    targets = set(target_models)
    return '\n\n'.join(
        observation for observation, model in zip(observations, models)
        if model and model in targets
    )


def _flag_ungrounded_group_xmlids(final_answer: str, raw_tool_output: str) -> str:
    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    grounded = set(_GROUP_XMLID_RE.findall(raw_tool_output))
    ungrounded = sorted(mentioned - grounded)
    if not ungrounded or not grounded:
        return final_answer
    groupList = ', '.join(ungrounded)
    return (
        final_answer.rstrip()
        + f'\n\nGROUPE(S) NON VÉRIFIÉ(S) : {groupList} mentionné(s) sans observation correspondante.'
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
