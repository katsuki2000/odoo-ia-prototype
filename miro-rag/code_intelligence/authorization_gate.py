"""
code_intelligence/authorization_gate.py

Bloc 7 / J23-J24: implements the option decided at J22 -- "toute
explication filtrée selon les droits du demandeur" (generalized gating,
not only the bypasses already known to be sensitive).

Gating happens PER TOOL OBSERVATION, before synthesis ever sees the text.
This is deliberate: filtering only the final synthesized answer (e.g. by
regexing sensitive strings out of it afterwards) would not catch the
synthesis LLM paraphrasing an omitted fact in its own words. Gating the
raw observation removes the fact from the LLM's context entirely, so it
cannot leak it back out reworded.

Two independent sources of privileged content are gated:

1. ir.rule group rules the demandeur is NOT a member of
   (RuleEvaluationResult.ignored_group_rules from
   evaluer_regles_enregistrement / evaluer_regles_raw). Their name and
   domain_force are stripped from the tool observation text -- revealing
   which restriction exists for a group the demandeur isn't part of is
   exactly the kind of thing such a rule exists to hide from them.

2. Security-bypass / internal-logic analyses (analyser_verrous_securite,
   analyser_actions_serveur): hardcoded validator lists, sudo() overrides,
   dynamic-dispatch uncertainty. These are gated unless the demandeur
   holds a management-level right (write or unlink) on the model in
   question, via the same ACL/ir.rule graph already used by
   qui_a_acces_a -- a user who can already write/delete records on a
   model is not learning anything new by seeing how its bypasses work; a
   read-only user is.

Every omission is recorded as an explicit OmittedItem -- never silently
dropped -- and is kept separate from sourcing_guard.py's citation
verification and from the response's confidence score, per J23-24's own
requirement: "distinct du score de couverture (A1), pour ne pas casser
le principe de sourcing".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set

import networkx as nx

# Tool names whose output can reveal an internal security-bypass mechanism
# (hardcoded validator lists, sudo() overrides, dynamic dispatch) rather
# than plain structural facts. Gated unless the demandeur has management
# rights (write/unlink) on the model the observation is about.
GATED_TOOL_NAMES: Set[str] = {"analyser_verrous_securite", "analyser_actions_serveur"}

_OMISSION_MARKER = "ÉLÉMENT OMIS POUR RAISON D'AUTORISATION"

# Deliberately NOT DOTALL and scoped with [^\n]*: the line that follows in
# the summary (the CONCLUSION line) starts with "  -> " (arrow), not "  - "
# (dash), so a lookahead keyed on "  - " would never match that boundary
# and a .*? would silently swallow the CONCLUSION text too. Matching only
# up to the next newline keeps the redaction scoped to this one line.
_IGNORED_RULES_LINE = re.compile(r"  - Règles de Groupe ignorées \(non-membre\):[^\n]*")


@dataclass
class OmittedItem:
    """
    A single element withheld from the demandeur for authorization reasons.
    `reason` is always explicit and human-readable -- never a bare status
    code -- so it can be surfaced to the user as-is, distinct from a
    confidence/coverage score.
    """
    label: str
    reason: str


def _has_elevated_access(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> bool:
    """
    True if the demandeur's real Odoo groups (never LLM-guessed -- see
    rag/graph.py's _override_user_groups_arg) grant WRITE or UNLINK on
    model_name, per the same ACL graph qui_a_acces_a already reads.
    Read-only access, or no resolvable access at all, is NOT elevated.
    """
    if not model_name:
        return False

    from code_intelligence.deterministic_tools import (
        _eval_single_droit,
        resolve_group_identifier,
    )

    write_groups, write_auth, _ = _eval_single_droit(G, model_name, "write")
    unlink_groups, unlink_auth, _ = _eval_single_droit(G, model_name, "unlink")

    if write_auth or unlink_auth:
        # ACL grants the right to all authenticated users -- not gated.
        return True

    candidate_groups = list(write_groups | unlink_groups)
    if not candidate_groups or not user_groups:
        return False

    return any(
        resolve_group_identifier(G, str(ug), candidate_groups) is not None
        for ug in user_groups
    )


def _strip_ignored_rule_details(observation: str) -> str:
    """Remove the 'Règles de Groupe ignorées (non-membre): ...' line's
    content (rule names + domain_force) from an evaluer_regles_enregistrement
    summary, replacing it with an explicit omission marker. The line's mere
    presence (that some rules were evaluated and ignored) is kept -- only
    the identifying details of those specific rules are withheld."""
    return _IGNORED_RULES_LINE.sub(
        f"  - Règles de Groupe ignorées (non-membre) : [{_OMISSION_MARKER}]",
        observation,
    )


def gate_observation(
    tool_name: str,
    model_name: str,
    observation: str,
    G: nx.DiGraph,
    user_groups: List[str],
    rule_result: Optional["object"] = None,
) -> "tuple[str, Optional[OmittedItem]]":
    """
    Gate a single tool observation against the demandeur's real rights.

    rule_result: the RuleEvaluationResult already computed for this exact
    evaluer_regles_enregistrement call, if tool_name is that tool (the
    caller in rag/graph.py already computes it once for the
    can_view_amount deterministic fact -- reused here rather than
    recomputed a second time).

    Returns (gated_text, omitted_item_or_None). gated_text is what should
    be handed to the synthesis LLM instead of the raw observation;
    omitted_item is appended by the caller to the response's
    omitted_for_authorization list, or None if nothing was withheld.
    """
    if tool_name == "evaluer_regles_enregistrement" and rule_result is not None:
        ignored = getattr(rule_result, "ignored_group_rules", None) or []
        if ignored:
            gated_text = _strip_ignored_rule_details(observation)
            names = ", ".join(r.rule_name or r.rule_xml_id for r in ignored)
            omitted = OmittedItem(
                label=f"ir.rule sur '{model_name}' non applicable(s) au demandeur : {names}",
                reason=(
                    f"{_OMISSION_MARKER} : ces règles de sécurité visent des groupes dont le "
                    "demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne "
                    "sont pas divulgués."
                ),
            )
            return gated_text, omitted
        return observation, None

    if tool_name in GATED_TOOL_NAMES and model_name:
        if not _has_elevated_access(G, model_name, user_groups):
            omitted = OmittedItem(
                label=f"{tool_name}({model_name})",
                reason=(
                    f"{_OMISSION_MARKER} : cette analyse porte sur un mécanisme de sécurité "
                    "interne (verrou codé en dur / contournement) et le demandeur ne dispose "
                    f"pas d'un accès de gestion (write ou unlink) sur '{model_name}'."
                ),
            )
            gated_text = (
                f"[{_OMISSION_MARKER}] Analyse de '{model_name}' via {tool_name} exécutée ; "
                "contenu non divulgué au demandeur actuel faute de droits de gestion "
                "suffisants sur ce modèle."
            )
            return gated_text, omitted

    return observation, None
