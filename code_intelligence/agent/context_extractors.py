"""
Heuristic regexes and extractors for question intent, amounts, companies,
move types, and sticky concept rehydration.
"""

import logging
import os
import re
import unicodedata
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

from code_intelligence.utils import _extract_amount, _question_is_approval_related


def _strip_accents(text: str) -> str:
    """Normalize a string by removing diacritics (accents) at matching time.

    Several _question_is_*_related regexes below already defensively use
    character classes like '[eé]tat' to tolerate accented/unaccented input,
    but not uniformly (see todo/contexte.txt section 764: the native N1
    question bank on disk is pure ASCII -- no accents anywhere -- which is
    exactly the kind of source this normalization protects against, along
    with NFD-decomposed copy-paste and non-French keyboards). Applied only
    to the text being matched against, never to captured group content --
    extract_ui_element_name() below must keep returning the original
    spelling of whatever UI label it extracts."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


# Deterministic patterns for tool triggers
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|actions?\s+automatiques?|automatisation\w*|"
    r"actions?\s+serveur|bypass|contourn\w*|p[eé]riodiq\w*|cron\b|planifi[eé]\w*|scheduler|recalcul\w*)\b",
    re.IGNORECASE,
)


def _question_mentions_amount(question: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(question))


# Qualitative same/different company relation extraction.
_COMPANY_DIFFERENT_PATTERN = re.compile(
    r"(?:pas\s+(?:de\s+)?la\s+m[êe]me\s+(?:soci[ée]t[ée]|filiale|entreprise)|"
    r"(?:une\s+)?autre\s+(?:soci[ée]t[ée]|filiale|entreprise)|"
    r"(?:soci[ée]t[ée]|filiale|entreprise)\s+(?:est\s+)?diff[ée]rente?)",
    re.IGNORECASE,
)
_COMPANY_SAME_PATTERN = re.compile(
    r"m[êe]me\s+(?:soci[ée]t[ée]|filiale|entreprise)",
    re.IGNORECASE,
)


def _extract_company_context(question: str) -> Dict[str, Any]:
    """Extract qualitative same/different-company relation from the question."""
    primary_id = int(os.getenv("ODOO_PRIMARY_COMPANY_ID", "1"))
    secondary_id = int(os.getenv("ODOO_SECONDARY_COMPANY_ID", "2"))
    if _COMPANY_DIFFERENT_PATTERN.search(question):
        return {"company_id": primary_id, "user": {"company_id": {"id": secondary_id}}, "company_ids": [secondary_id]}
    if _COMPANY_SAME_PATTERN.search(question):
        return {"company_id": primary_id, "user": {"company_id": {"id": primary_id}}, "company_ids": [primary_id]}
    return {}


# Move type mapping for domain_force evaluation based on business terms.
_MOVE_TYPE_ALIAS_MAP: Dict[str, str] = {
    "avoir": "out_refund",
    "avoirs": "out_refund",
    "credit note": "out_refund",
    "facture": "out_invoice",
    "factures": "out_invoice",
    "facturation": "out_invoice",
}


def _infer_move_type_context(concept) -> Dict[str, Any]:
    """Infer move_type value from business term matched during resolution."""
    if concept is None or not getattr(concept, "is_resolved", False):
        return {}
    if getattr(concept, "source_step", "") != "static_alias":
        return {}

    matched_terms = [t.strip() for t in (concept.user_term or "").split(",")]
    inferred = {
        _MOVE_TYPE_ALIAS_MAP[t] for t in matched_terms if t in _MOVE_TYPE_ALIAS_MAP
    }
    if len(inferred) != 1:
        return {}
    return {"move_type": next(iter(inferred))}


# Access-related question patterns ("qui peut...", "peut-il voir...", etc.)
_ACCESS_QUESTION_PATTERN = re.compile(
    r"\bqui\s+(?:a\s+le\s+permission|peut|peux|est\s+autoris\w*)\b|"
    r"\b(?:puis\s*[- ]\s*je|est\s*[- ]\s*ce\s*que\s+je\s+peux|can\s+i|may\s+i|"
    r"am\s+i\s+allowed|do\s+i\s+have\s+(?:access|permission|the\s+right))\s+"
    r"(?:see|view|access|read|write|create|edit|modify|delete|unlink|"
    r"voir|visualiser|acc[eé]der|consulter|lire|[ée]crire|cr[eé]er|modifier|supprimer|effacer)\b|"
    r"\b(?:peut|peux|pourra|pourrait)[\s-]*(?:il|elle|on|t[\s-]*il|t[\s-]*elle)\s+(?:\w+\s+)?(?:voir|acc[eé]der|consulter|lire|visualiser|d[eé]clencher|lancer|ex[eé]cuter|faire|cr[eé]er|modifier|supprimer|purger|utiliser)\b|"
    r"\ba[\s-]*t[\s-]*(?:il|elle)\s+(?:le\s+permission|acc[eè]s|la\s+permission)\b|"
    r"\b(?:ir\.rule|record\s+rules?|acl|acls|ir\.model\.access|droits?\s+d['’]acc[eè]s|permissions?|base\.group_\w+|group_[a-z0-9_]+)\b|"
    r"\bwho\s+(?:can|has\s+the\s+right|is\s+authoriz\w*)\b|"
    r"\b(?:can|may)\s+(?:a\s+user|the\s+user|an?\s+employee)\s+(?:see|view|access|read)\b",
    re.IGNORECASE,
)


def _question_is_access_related(question: str) -> bool:
    """True if the question is asking about access permissions or visibility."""
    return bool(_ACCESS_QUESTION_PATTERN.search(_strip_accents(question)))


_WORKFLOW_QUESTION_PATTERN = re.compile(
    r"\b(?:workflow|cycle\s+de\s+vie|machine\s+[aà]\s+[eé]tats?|state\s+machine)\b|"
    r"\b(?:passage|passer)\s+(?:d['’][^.\n]+?\s+)?de\s+l['’][eé]tat\b|"
    r"\b(?:transition|changement)\s+d['’][eé]tat\b|"
    r"\b(?:[eé]tat\s+source|[eé]tat\s+cible|champ\s+d['’][eé]tat|champ\s+state|workflow\s+d['’][eé]tats?)\b|"
    r"\b(?:lifecycle|state\s+transition)\b|"
    # "Que se passe-t-il quand on [clique/confirme/valide/poste/...]" --
    # trigger-action phrasing for a state/stage change, distinct from the
    # "etat"/"transition" vocabulary above (see todo/contexte.txt section
    # 764/765: 4/5 native N1 workflow questions use this idiom instead).
    r"\bque\s+se\s+passe[-\s]t[-\s]il\b.{0,150}?\b(?:clique|clic|confirme|valide|poste|atteint|marqu[eé]e?|passe\s+[aà])\b|"
    # "Comment se passe/se déroule/fonctionne ... la validation/approbation/
    # confirmation" -- process-description idiom (section 1275: "comment se
    # passe la validation des congés" was not triggering describe_workflow).
    r"\bcomment\s+(?:se\s+)?(?:passe|deroule|d[eé]roule|fonctionne)\s"
    r".{0,80}?\b(?:valid|appro[buv]|confirm)",
    re.IGNORECASE | re.DOTALL,
)


def _question_is_workflow_related(question: str) -> bool:
    """True if question investigates workflow state transitions or states."""
    return bool(_WORKFLOW_QUESTION_PATTERN.search(_strip_accents(question)))


_INHERITANCE_QUESTION_PATTERN = re.compile(
    r"\b(?:_inherit|_inherits|h[eé]ritage|inheritance)\b|"
    r"\b[eé]tend(?:-il)?\b|"
    r"\b(?:surcharg[eé]\w*|override\w*)\b|"
    r"\bmod[eè]le\s+(?:concret|abstrait|standard|natif|existant)\b|"
    r"\b(?:propres?|nouveaux?)\s+mod[eè]les?\b|"
    r"\bactive-t-il\b|"
    r"\bquels?\s+mod[eè]les?\s+sont\s+modifi[eé]s?\b|"
    r"\br[eé]utilise-t-il\b|"
    r"\bmodifie(?:-t-il)?\s+le\s+comportement\b",
    re.IGNORECASE,
)


def _question_is_inheritance_related(question: str) -> bool:
    """True if question inquires about model inheritance, mixins, or extensions."""
    return bool(_INHERITANCE_QUESTION_PATTERN.search(_strip_accents(question)))


_METHOD_OR_OVERRIDE_PATTERN = re.compile(
    r"\b(?:m[eé]thodes?|surcharg\w*|override\w*|super\(\))\b|"
    r"\bchanger\s+.*?\bpeut\s+modifier\b|"
    r"\bmodifie(?:-t-il)?\s+le\s+comportement\b|"
    r"\b(?:write|create|unlink|_compute_\w+|button_\w+|action_\w+)\b",
    re.IGNORECASE,
)


def _question_is_method_or_override_related(question: str) -> bool:
    """True if question inquires about method behavior, overrides, or write-time field mutations."""
    return bool(_METHOD_OR_OVERRIDE_PATTERN.search(_strip_accents(question)))


_CONSTRAINTS_QUESTION_PATTERN = re.compile(
    r"\b(?:contraintes?|_?sql_constraints?|api\.constrains?)\b|"
    r"\b(?:r[eè]gle|condition|v[eé]rification)\s+(?:empeche|bloque|interdit)\b|"
    r"\b(?:empeche|bloque|interdit|empechent|bloquent|interdisent|empechant|empêche|empêchent|empêchant)\b(?:[^,\.!?\n]{0,50}?)\b(?:de\s+\w+|d['’]\w+)\b|"
    r"\b(?:valeur\s+non\s+reconnue|valeur\s+invalide|unrecognized)\b|"
    r"\b(?:que\s+se\s+passe[-\s]t[-\s]il|qu['’]arrive[-\s]t[-\s]il)\s+(?:si|lorsqu|quand)\b",
    re.IGNORECASE,
)


def _question_is_constraint_related(question: str) -> bool:
    """True if question investigates model data constraints, validation rules, or write blockers."""
    return bool(_CONSTRAINTS_QUESTION_PATTERN.search(_strip_accents(question)))


# "What actually distinguishes X from Y" phrasing -- a security question
# that implies a real distinction must exist somewhere between two
# roles/groups, even if the ACL/ir.rule layer alone turns out identical
# (todo/contexte.txt section 778, PUR-Q1: the agent stopped after ACL+rule
# observations showed no difference and answered "no distinction exists",
# which was wrong -- the real distinction was a Python-level approval
# guard neither tool surfaces). Distinct from _question_is_access_related
# (which matches ANY access-permission wording): this one specifically
# targets the "beyond what ACL shows" phrasing that should push the agent
# one layer deeper before concluding.
_SECURITY_DISTINCTION_PATTERN = re.compile(
    r"\bqu['’]est-ce\s+qui\s+distingue\b|"
    r"\bdistingue(?:-t-il)?\s+(?:alors\s+)?r[eé]ellement\b|"
    r"\bdiff[eé]rencie\s+r[eé]ellement\b|"
    r"\b(?:vraie|r[eé]elle)\s+diff[eé]rence\s+entre\b|"
    r"\bdiff[eé]rence\s+r[eé]elle\s+entre\b",
    re.IGNORECASE,
)


def _question_is_security_distinction_related(question: str) -> bool:
    """True if the question asks what genuinely/really distinguishes two
    roles/groups, implying a real distinction should exist beyond a
    surface-level ACL/ir.rule check."""
    return bool(_SECURITY_DISTINCTION_PATTERN.search(_strip_accents(question)))


def _rehydrate_sticky_concept(concept, state: dict):
    """Reconstruct a ResolvedConcept from a sticky dict when current turn's resolution failed."""
    if concept.is_resolved:
        return concept

    sticky = state.get("resolved_concept")
    if isinstance(sticky, dict):
        if sticky.get("is_resolved") is True:
            try:
                from code_intelligence.agent.matching import ResolvedConcept
                return ResolvedConcept(**sticky)
            except Exception:
                logger.debug(
                    "_rehydrate_sticky_concept: reconstruction from sticky dict "
                    "failed (unexpected shape), degrading to original concept"
                )
                return concept

    mod = state.get("module")
    if mod and isinstance(mod, str):
        from code_intelligence.agent.matching import ResolvedConcept
        target_models = state.get("target_models", [])
        return ResolvedConcept(
            user_term=mod,
            resolved_models=list(target_models) if target_models else [],
            resolved_modules=[mod],
            confidence=1.0,
            source_step="state_module",
            is_resolved=True,
            reason=f"Resolved from state module: {mod}",
        )

    return concept

# ── UI Patterns ─────────────────────────────────────────────────────────

"""
code_intelligence/ci_agent_node/ui_patterns.py

Regex-based extraction of UI element names (buttons/menus/fields) and
detection of module-level UI inquiries from a question. Extracted from the
former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import re
from typing import Optional

_UI_NAME_STOPWORDS = {
    "visible", "visibles", "invisible", "invisibles",
    "specifique", "specifiques", "spécifique", "spécifiques",
    "particulier", "particuliers", "particuliere", "particulières", "particulière",
    "dedie", "dedies", "dédié", "dédiés", "dediee", "dédiée", "dediees", "dédiées",
    "nouveau", "nouveaux", "nouvelle", "nouvelles",
    "ajoute", "ajoutes", "ajouté", "ajoutés", "ajoutee", "ajoutée", "ajoutees", "ajoutées",
    "cree", "crees", "créé", "créés", "creee", "créée", "creees", "créées",
    "supplementaire", "supplementaires", "supplémentaire", "supplémentaires",
    "personnalise", "personnalises", "personnalisé", "personnalisés",
    "existant", "existants", "existante", "existantes",
    "present", "presents", "présent", "présents", "presente", "présente", "presentes", "présentes",
    "special", "speciaux", "spécial", "spéciaux", "speciale", "spéciale", "speciales", "spéciales",
    "custom", "new", "existing", "specific", "dedicated", "added", "created",
    "un", "une", "des", "le", "la", "les", "ce", "cette", "ces", "dans", "sur",
}

_MODULE_UI_PATTERN = re.compile(
    r"\b(?:modifie(?:-t-il)?\s+(?:une\s+)?vue|ajoute(?:-t-il)?\s+(?:un\s+)?bouton|dossier\s+views|vue\s+xml|interface)\b",
    re.IGNORECASE,
)


def matches_module_level_ui_inquiry(question: str) -> bool:
    return bool(_MODULE_UI_PATTERN.search(_strip_accents(question)))


_GROUP_IDENTIFIER_PATTERN = re.compile(r"(?:[a-z0-9_]+\.)?group_", re.IGNORECASE)
_METHOD_NAME_PREFIX_PATTERN = re.compile(r"(?:button|action)_", re.IGNORECASE)
# The question is about what a user SEES (visibility/display of a field or
# element), as opposed to e.g. a constraint or a workflow. Matched against
# the accent-stripped question. "voir" is boundary-anchored so that "avoir"
# does not match.
_UI_VISIBILITY_INTENT_PATTERN = re.compile(
    r"\b(?:voit|voient|voir|visibles?|invisibles?|affich\w*|apparai\w*|masqu\w*|cach\w*)\b",
    re.IGNORECASE,
)
_BARE_PAREN_IDENTIFIER_PATTERN = re.compile(r"\(([a-z][a-z0-9]*_[a-z0-9_]*)\)")


def is_group_identifier(name: str) -> bool:
    """True if `name` looks like a security-group identifier (group_x or
    module.group_x). A group is never a button/menu/field of a view, so it
    must never be handed to button_execution_path (todo/contexte.txt section
    875/876: ACC-Q1/ACC-Q2 "(group_account_manager)" was taken for a button)."""
    return bool(name) and bool(_GROUP_IDENTIFIER_PATTERN.match(name))


def _bare_parenthesized_ui_candidate(question: str) -> Optional[str]:
    """Last-resort fallback of extract_ui_element_name: a snake_case identifier
    in parentheses with no bouton/champ keyword. Kept only when it is not a
    group AND either looks like a method (button_*/action_*) or the question
    is about what a user sees. A field named in a constraint question
    (SAL-Q5 "(prepayment_percent)", MNT-Q5 "(repeat_interval)") is not a UI
    element the question asks about; a field named in a visibility question
    (ACC-Q4 "(account_id)", "voit-il") is (todo/contexte.txt section 876)."""
    intent_is_visibility = bool(_UI_VISIBILITY_INTENT_PATTERN.search(_strip_accents(question)))
    for cand in _BARE_PAREN_IDENTIFIER_PATTERN.finditer(question):
        name = cand.group(1).strip()
        if is_group_identifier(name):
            continue
        if _METHOD_NAME_PREFIX_PATTERN.match(name) or intent_is_visibility:
            return name
    return None


def extract_ui_element_name(question: str) -> Optional[str]:
    """Best-effort extraction of the UI element (button/menu/field) name a
    question is asking about, filtering out generic qualifier words that
    are never themselves the element's name (see _UI_NAME_STOPWORDS)."""
    match = re.search(
        r"\b(?:bouton|button|menu|menuitem|champ|field)s?\s+(?:statistique\s+)?['\"«]([^'\"»]+)['\"»]",
        question, re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b(?:bouton|button|menu|champ|field)s?\s+(?:de\s+|d['’]\s*)?([a-zA-Z0-9_]+)\b",
            question, re.IGNORECASE,
        )
    if not match:
        match = re.search(
            r"\b(?:voir\s+ou\s+configurer|voir\s+ou\s+modifier|voir|configurer|modifier|afficher|masquer)\s+"
            r"(?:le|la|l['’]|les)?\s*([^?]+?)\s+sur\s+(?:la\s+fiche|le\s+formulaire|la\s+vue)",
            question, re.IGNORECASE,
        )
    if not match:
        # Action-verb + parenthetical label, no bouton/champ keyword needed
        # (todo/contexte.txt section 767/768: SAL-Q4 "deverrouiller (Unlock)"
        # -- the native N1 bank glosses the French action verb with the
        # actual UI label in parens instead of naming it explicitly).
        match = re.search(
            r"\b(?:verrouiller|d[eé]verrouiller|valider|confirmer|annuler|approuver|rejeter|"
            r"publier|archiver|d[eé]sarchiver|dupliquer|imprimer|envoyer|cl[oô]turer|"
            r"remettre|r[eé]ouvrir|marquer|d[eé]bloquer|bloquer|activer|d[eé]sactiver|"
            r"facturer|payer|rembourser)\s*\(([A-Za-z][A-Za-z0-9 _\-]{0,40})\)",
            question, re.IGNORECASE,
        )
    if not match:
        # Bare technical field name in parens, no keyword at all (section
        # 767/768: ACC-Q4 "le compte comptable (account_id)" -- requires an
        # underscore to stay a snake_case-looking technical name, keeping
        # false positives low (a bare English gloss like "(Unlock)" is
        # handled by the action-verb pattern above, not this one).
        # Section 876: the candidate is now gated (see
        # _bare_parenthesized_ui_candidate) -- group names are skipped and a
        # non-method identifier is kept only for a visibility-type question.
        candidate = _bare_parenthesized_ui_candidate(question)
        if candidate is not None:
            return candidate
    if not match:
        return None
    name = match.group(1).strip()
    if name.lower() in _UI_NAME_STOPWORDS:
        return None
    return name

# ── Module Inference ───────────────────────────────────────────────────

"""
code_intelligence/ci_agent_node/module_inference.py

Shared helper for inferring the most relevant custom module(s) declaring/
extending a set of resolved models, ranked by lexical overlap with the
question. Extracted from the former ci_agent_node.py monolith, where this
exact computation was duplicated verbatim in two places (resolved_info
business-context block, and the inheritance pre-dispatch's module-target
fallback) -- refactor, see todo/contexte.txt. Behavior unchanged.
"""

import re
from typing import Any, List


def rank_custom_modules_for_models(G: Any, resolved_models: List[str], question: str) -> List[str]:
    """Return custom modules declaring/extending resolved_models, ranked by
    lexical overlap with the question (most relevant first). Empty list if
    none found or G is None."""
    if G is None:
        return []
    from .tool_helpers import _is_custom_module_filepath

    all_custom_mods = []
    for rm in resolved_models:
        if not G.has_node(f"model:{rm}"):
            continue
        rm_mods = set()
        for v in G.neighbors(f"model:{rm}"):
            if v.startswith("module:"):
                mod_data = G.nodes[v]
                fp = mod_data.get("filepath", "")
                if _is_custom_module_filepath(fp):
                    rm_mods.add(v.replace("module:", ""))
        if rm_mods:
            all_custom_mods.append(rm_mods)

    if not all_custom_mods:
        return []

    common_mods = set.intersection(*all_custom_mods) if len(all_custom_mods) > 1 else all_custom_mods[0]
    candidate_mods = list(common_mods if common_mods else all_custom_mods[0])
    q_words = set(re.findall(r"\w+", question.lower()))

    def _mod_rank(m):
        parts = set(m.split("_"))
        return (len(parts.intersection(q_words)), len(m))

    candidate_mods.sort(key=_mod_rank, reverse=True)
    return candidate_mods
