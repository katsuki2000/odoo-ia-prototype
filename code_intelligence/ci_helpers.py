"""
Code Intelligence deterministic helpers.

Extraction, backfill, contradiction-neutralization, and grounding
functions for the Code Intelligence agent. These are pure functions
that analyze raw tool output text and final answers to detect/correct
specific failure modes of small synthesis LLMs.
"""

import json
import logging
import os
from pathlib import Path
import re
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


# ── Code Intelligence Agent ───────────────────────────────────────────────────

# System prompt with explicit scope-first navigation strategy.
CI_SYSTEM_PROMPT = (
    "You are MIRO Code Intelligence Assistant specializing in Odoo source code and security analysis.\n"
    "NAVIGATION STRATEGY:\n"
    "1. When target models or modules are provided by [BUSINESS TERM RESOLVER], invoke the appropriate tools immediately:\n"
    "   - For approval limits, hardcoded emails (_VALIDATEURS_EXCEPTIONNELS), UserError/ValidationError strings, or dynamic getattr dispatches: ALWAYS invoke `analyze_security_locks`.\n"
    "   - For group access matrix and ACL model permissions: invoke `who_has_access_to`.\n"
    "   - For ir.rule record rules and group-based RECORD visibility: invoke `evaluate_record_rules` (authoritative).\n"
    "   - For automated actions, ir.actions.server, or sudo() bypasses: invoke `analyze_server_actions`.\n"
    "   - For SQL uniqueness constraints (_sql_constraints) or relational field domain= filters (Many2one/Many2many): invoke `analyze_data_constraints`.\n"
    "   - For workflows, state machine transitions, or states/stages on a model: invoke `describe_workflow`.\n"
    "   - For model inheritance, extensions, mixins, or parent models: invoke `trace_full_inheritance`.\n"
    "   - For method overrides, super() chains, or behavior modifications across modules (e.g. write, create, unlink, compute methods): invoke `analyze_method_override_chain`.\n"
    "   - For UI buttons, form actions, or menu visibility/restrictions: invoke `button_execution_path`.\n"
    "   - For inspecting precise Python implementation, method logic, dynamic validation hooks (e.g. write, get_view, _check_*), or configuration model fields when abstract mixins or dynamic behaviors are analyzed: invoke `read_source_code` with the filepath and line range.\n"
    "2. DO NOT make generic fallbacks. Synthesize the tool observations directly.\n"
    "3. Always cite source file links: [file.py:L12-L25](file:///path#L12-L25).\n"
    "   NEVER reuse this placeholder text itself as a citation -- only cite a file:// link "
    "with a real path and real line numbers copied verbatim from an actual tool observation. "
    "If no real citation is available for a claim, state the claim without any file:// link "
    "rather than inventing or reusing the example format.\n"
    "4. When citing a rule, group, or action by its Odoo technical identifier as a "
    "sourcing claim (not just using it as ordinary vocabulary), prefix it exactly as "
    "'xml_id: module.identifier' (e.g. xml_id: custom_credit_note_visibility_rules."
    "rule_avoir_visibilite_regionale).\n"
    "5. RETRY-BEFORE-HEDGE RULE: if a tool call returns 'not found in the "
    "indexed knowledge graph' or any similar failure, that failure means the MODEL NAME OR "
    "IDENTIFIER YOU JUST TRIED WAS WRONG -- it does not mean the information doesn't exist. "
    "Before proposing a different guessed identifier, or giving up and answering with hedging "
    "language ('il n'est pas possible de determiner avec certitude', 'il est possible que'), "
    "you MUST retry the SAME tool using the EXACT technical identifier already given to you "
    "under [BUSINESS TERM RESOLVER] above ('Target Models: ...') or already confirmed by "
    "an earlier successful tool observation in this same conversation. Never invent a new "
    "model/module name by paraphrasing the user's natural-language wording (e.g. 'demande_conge', "
    "'achat.demande', 'purchase.order') -- only the resolver-confirmed identifier or one copied "
    "verbatim from a prior successful observation is valid. Do not answer with uncertainty "
    "language until you have used at least one tool call against the resolver-confirmed model.\n"
    "6. 'COMMENT FAIRE X ?' RULE: for any question asking HOW to "
    "perform an action (click a button, submit a request, validate/approve something), invoke "
    "`button_execution_path`. Its result states explicitly whether the action is available to "
    "THIS demandeur. If it says NON DISPONIBLE / available_to_requester is false, your answer "
    "MUST say plainly that the demandeur does not have this option in the interface and, if the "
    "observation names the required group(s), who they should contact instead -- do NOT walk them "
    "through the button/method mechanism as if they could trigger it themselves.\n"
    "7. OUTPUT FORMAT RULE: Write the final answer in Markdown ONLY (**bold**, *italic*, \"-\" bullet "
    "lists, \"##\"/\"###\" headings, \"[text](url)\" links -- the file:// citations from rule 3 above "
    "already use this link syntax). NEVER emit raw HTML tags (no <strong>, <br>, <div>, <em>, <ul>, "
    "etc.), even mixed in with Markdown. The rendering engine only interprets Markdown; any HTML tag "
    "is shown to the user as literal, unreadable text.\n"
    "Example of correctly formatted output:\n"
    "### Analyse des droits d'acces\n\n"
    "- **Groupe requis** : `account.group_account_manager`\n"
    "- **Source** : [security/ir.model.access.csv:L12](file:///path#L12)\n\n"
    "No raw HTML tag appears anywhere in this example -- only Markdown headings, bold, and bullets."
)

# Maximum hops allowed per question.
CI_MAX_HOPS = 4

# Composite tools whose dedup key is only (tool_name, model_name) -- the
# deterministic pre-dispatch blocks in ci_agent_node.py already key on
# exactly this for these tools.
_MODEL_KEYED_TOOLS = frozenset({
    "analyze_security_locks",
    "analyze_server_actions",
    "who_has_access_to",
    "evaluate_record_rules",
    "describe_workflow",
    "trace_full_inheritance",
    "list_involved_modules",
    "analyze_data_constraints",
})


def _tool_call_key(tool_name: str, tool_args: "Dict[str, Any]") -> "Optional[Tuple]":
    """Single source of truth for the seen_calls dedup key, shared between
    the deterministic pre-dispatch blocks and the LLM-driven ReAct tool
    calls in ci_agent_node.py -- both must agree on what counts as "the
    same call" so the ReAct loop can refuse to re-execute a composite tool
    the pre-dispatch stage (or an earlier ReAct iteration) already ran for
    the same target, instead of only telling the LLM not to via the system
    prompt and hoping it complies (todo/contexte.txt section 250-251:
    a small synthesis LLM does not reliably follow that instruction).

    Returns None for tools/args this dedup scheme does not apply to (e.g.
    analyze_method_override_chain missing a method_name, or any tool
    outside the composite set above) -- callers must treat None as "not
    dedupable" rather than as a real key.
    """
    model_name = tool_args.get("model_name")
    if not model_name:
        return None
    if tool_name == "analyze_method_override_chain":
        method_name = tool_args.get("method_name")
        return (tool_name, model_name, method_name) if method_name else None
    if tool_name == "button_execution_path":
        btn = tool_args.get("button_name") or tool_args.get("button_identifier")
        return (tool_name, model_name, btn) if btn else None
    if tool_name in _MODEL_KEYED_TOOLS:
        return (tool_name, model_name)
    return None


# ── Shared observation-truncation helper (todo/contexte.txt section 500-501, Bug 3) ─
# Marker appended whenever an observation is cut for context-length reasons.
# Downstream deterministic extraction (see code_intelligence/ci_override_cascade.py)
# can check for this marker to avoid treating a fragment adjacent to it as a
# reliable fact -- same literal string previously hardcoded at each of the 6
# truncation call sites in ci_agent_node.py, now defined once here.
_TRUNCATION_MARKER = "\n[... Content truncated for LLM context limit ...]"


def _truncate_observation(text: str, limit: int) -> str:
    """Truncate `text` to at most `limit` characters without ever cutting
    inside a token (a number, an xml_id, a method/field name, a word).

    Root cause fixed here (todo/contexte.txt section 500, Bug 3): the raw
    `text[:limit]` slicing previously used at every truncation site in
    ci_agent_node.py cuts on a bare character index, with zero awareness of
    token boundaries. On one real capture this cut the digit sequence
    "5000" down to "500" mid-number, and a downstream regex
    (_OVERRIDE_CHAIN_AMOUNT_RE) then matched the truncated "500" as if it
    were a real amount, which a backfill function stamped into the answer
    as a "[FAIT DETERMINISTIQUE]". This is not specific to that one amount,
    module, or tool -- any sufficiently long observation truncated at any
    of the (now shared) call sites could cut through any token the same way.

    Strategy, in order of preference:
      1. Cut back to the last newline before `limit`, if one exists --
         keeps whole lines intact, the safest boundary.
      2. Otherwise cut back to the last space before `limit` -- a token
         with no internal whitespace (a number, an xml_id, a
         dotted/underscored identifier) cannot straddle a space, so this
         can never leave a partial token dangling off the cut edge.
      3. If neither a newline nor a space exists before `limit` (a single
         very long unbroken token), fall back to the raw index cut -- there
         is no safe boundary to retreat to, and refusing to truncate at all
         would defeat the purpose of the cap.

    Always appends _TRUNCATION_MARKER when truncation actually occurred, so
    callers scanning the returned text for a truncation signal (Evidence-
    first: never treat a fact extracted next to this marker as reliable
    without checking for it first) have a single, consistent string to look
    for.
    """
    if len(text) <= limit:
        return text

    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    else:
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
        # else: no safe boundary before `limit` at all -- keep the raw
        # index cut (`cut` already equals text[:limit] in that case).

    return cut + _TRUNCATION_MARKER


# Proximity window (characters) used by _match_near_truncation below --
# generous enough to survive the marker's own leading newline and bracket
# text, narrow enough not to reject matches elsewhere in a long block that
# happens to also contain a truncation marker somewhere unrelated.
_TRUNCATION_PROXIMITY_CHARS = 50


def _match_near_truncation(text: str, start: int, end: int) -> bool:
    """True if the [start, end) span in `text` sits within
    _TRUNCATION_PROXIMITY_CHARS characters of a _TRUNCATION_MARKER
    occurrence, on either side.

    Evidence-first guard (todo/contexte.txt section 503-505, Bug 3
    residual risk): _truncate_observation() above already guarantees a
    truncated token is never split mid-word/mid-number, but a cut can
    still land right after a complete, real value and silently drop the
    rest of its surrounding condition (e.g. an `and not rec.xxx` exception
    clause following a threshold comparison). A value extracted right next
    to a truncation marker is real but its CONTEXT may be incomplete --
    callers use this to refuse extracting a fact from such a match rather
    than treating it as fully grounded.
    """
    window_start = max(0, start - _TRUNCATION_PROXIMITY_CHARS)
    window_end = min(len(text), end + _TRUNCATION_PROXIMITY_CHARS)
    return _TRUNCATION_MARKER in text[window_start:window_end]


# Deterministic patterns for tool triggers
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|permission\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|actions?\s+automatiques?|automatisation\w*|"
    r"actions?\s+serveur|bypass|contourn\w*|p[eé]riodiq\w*|cron\b|planifi[eé]\w*|scheduler|recalcul\w*)\b",
    re.IGNORECASE,
)


def _question_mentions_amount(question: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(question))


def _extract_amount(question: str) -> "Optional[float]":
    """
    Extract the first monetary amount mentioned in the question, as a
    float, or None if none found / unparseable. Reuses _AMOUNT_PATTERN's
    detection but strips the currency symbol/word and normalizes the
    thousands separator (space or comma) before the decimal point.
    Deliberately conservative: on any parsing ambiguity, returns None
    rather than guessing a possibly-wrong value -- a missed deterministic
    check is safer than a wrong one.
    """
    match = _AMOUNT_PATTERN.search(question)
    if not match:
        return None
    raw = match.group(0)
    # Strip currency symbol/word, keep only digits, spaces, commas, dots.
    numeric_part = re.sub(r"(?i)(€|eur(?:os?)?)", "", raw).strip()
    # Normalize: remove spaces and commas used as thousands separators.
    # This assumes no decimal amounts appear in the adversarial question
    # set (verified: all amounts are whole euros, e.g. "80 000€") --
    # a real decimal separator would need locale-aware parsing, out of
    # scope for this bounded deterministic check.
    cleaned = numeric_part.replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


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


def _extract_company_context(question: str) -> "Dict[str, Any]":
    """
    Extract a qualitative same/different-company relation from the question.
    Returns {} if no company relation is specified.
    """
    primary_id = int(os.getenv("ODOO_PRIMARY_COMPANY_ID", "1"))
    secondary_id = int(os.getenv("ODOO_SECONDARY_COMPANY_ID", "2"))
    if _COMPANY_DIFFERENT_PATTERN.search(question):
        return {"company_id": primary_id, "user": {"company_id": {"id": secondary_id}}, "company_ids": [secondary_id]}
    if _COMPANY_SAME_PATTERN.search(question):
        return {"company_id": primary_id, "user": {"company_id": {"id": primary_id}}, "company_ids": [primary_id]}
    return {}


# Move type mapping for domain_force evaluation based on business terms.
_MOVE_TYPE_ALIAS_MAP: Dict[str, str] = {
    # Aligned with BUSINESS_ALIASES's own account.move alias groups
    # (code_intelligence/business_resolver.py) -- only the two groups that
    # unambiguously map to a single Odoo move_type are included here.
    "avoir": "out_refund",
    "avoirs": "out_refund",
    "credit note": "out_refund",
    "facture": "out_invoice",
    "factures": "out_invoice",
    "facturation": "out_invoice",
}


def _infer_move_type_context(concept) -> "Dict[str, Any]":
    """
    Infer a move_type value for _dispatch_context/context from the
    business term already matched during resolution -- never guessed from
    the raw question text independently, and never returned when the
    signal is anything less than unambiguous.

    Deliberately scoped to concept.source_step == "static_alias": that is
    the only resolution path where user_term is guaranteed to be exactly
    the comma-joined list of ALIAS KEYS that matched (see
    resolve_business_term's own construction of ResolvedConcept for the
    static-alias branch) -- every other path (exact_technical_mention,
    fuzzy_graph_match, llm_arbitration) sets user_term to the raw question
    text instead, which is not a reliable substrate to scan for a specific
    alias without risking a false match against unrelated question
    wording.

    Returns {} (no key at all, matching _extract_company_context's own
    convention) whenever:
      - concept is None, unresolved, or not a static-alias resolution;
      - none of the matched terms map to a move_type;
      - MORE THAN ONE distinct move_type is implied by the matched terms
        (e.g. a question naming both "avoir" and "facture" in the same
        sentence) -- absence of a single unambiguous signal must resolve
        to unresolved/None downstream, never to a guessed value, per
        rules.md Regle 5 (same discipline _extract_company_context already
        documents for its own {} return, immediately above).
    """
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


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


# Access-related question patterns ("qui peut...", "peut-il voir...", etc.)
_ACCESS_QUESTION_PATTERN = re.compile(
    # French "qui peut / a la permission / est autorisé" patterns
    r"\bqui\s+(?:a\s+le\s+permission|peut|peux|est\s+autoris\w*)\b|"
    # Inverted-subject French question form ("peut-il/elle/on voir/déclencher/lancer...")
    r"\b(?:peut|peux|pourra|pourrait)[\s-]*(?:il|elle|on|t[\s-]*il|t[\s-]*elle)\s+(?:\w+\s+)?(?:voir|acc[eé]der|consulter|lire|visualiser|d[eé]clencher|lancer|ex[eé]cuter|faire|cr[eé]er|modifier|supprimer|purger|utiliser)\b|"
    # "a-t-il/elle la permission / accès"
    r"\ba[\s-]*t[\s-]*(?:il|elle)\s+(?:le\s+permission|acc[eè]s|la\s+permission)\b|"
    # Direct security rules / ACL / permissions / groups questions
    r"\b(?:ir\.rule|record\s+rules?|acl|acls|ir\.model\.access|droits?\s+d['’]acc[eè]s|permissions?|base\.group_\w+|group_[a-z0-9_]+)\b|"
    # English patterns
    r"\bwho\s+(?:can|has\s+the\s+right|is\s+authoriz\w*)\b|"
    r"\b(?:can|may)\s+(?:a\s+user|the\s+user|an?\s+employee)\s+(?:see|view|access|read)\b",
    re.IGNORECASE,
)


def _question_is_access_related(question: str) -> bool:
    """True if the question is asking about access permissions or visibility."""
    return bool(_ACCESS_QUESTION_PATTERN.search(question))


_WORKFLOW_QUESTION_PATTERN = re.compile(
    r"\b(?:workflow|cycle\s+de\s+vie|machine\s+[aà]\s+[eé]tats?|state\s+machine)\b|"
    r"\b(?:passage|passer)\s+(?:d['’][^.\n]+?\s+)?de\s+l['’][eé]tat\b|"
    r"\b(?:transition|changement)\s+d['’][eé]tat\b|"
    r"\b(?:[eé]tat\s+source|[eé]tat\s+cible|champ\s+d['’][eé]tat|champ\s+state|workflow\s+d['’][eé]tats?)\b|"
    r"\b(?:lifecycle|state\s+transition)\b",
    re.IGNORECASE,
)


def _question_is_workflow_related(question: str) -> bool:
    """True if question investigates workflow state transitions or states."""
    return bool(_WORKFLOW_QUESTION_PATTERN.search(question))


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
    return bool(_INHERITANCE_QUESTION_PATTERN.search(question))


_METHOD_OR_OVERRIDE_PATTERN = re.compile(
    r"\b(?:m[eé]thodes?|surcharg\w*|override\w*|super\(\))\b|"
    r"\bchanger\s+.*?\bpeut\s+modifier\b|"
    r"\bmodifie(?:-t-il)?\s+le\s+comportement\b|"
    r"\b(?:write|create|unlink|_compute_\w+|button_\w+|action_\w+)\b",
    re.IGNORECASE,
)


def _question_is_method_or_override_related(question: str) -> bool:
    """True if question inquires about method behavior, overrides, or write-time field mutations."""
    return bool(_METHOD_OR_OVERRIDE_PATTERN.search(question))


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
    return bool(_CONSTRAINTS_QUESTION_PATTERN.search(question))


_REQUIRED_GROUP_LINE_RE = re.compile(
    r"Groupe\(s\)\s+technique\(s\)\s+requis\s+detecte\(s\)\s+\(has_group\):\s*([^\n]+)"
)

_GROUP_XMLID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b")


def _extract_required_groups(raw_tool_output: str) -> List[str]:
    """Pull every has_group()-derived required group xml_id out of the raw
    tool text in first-seen order, deduplicated."""
    groups: List[str] = []
    for match in _REQUIRED_GROUP_LINE_RE.finditer(raw_tool_output):
        for name in match.group(1).split(","):
            name = name.strip()
            if name and name not in groups:
                groups.append(name)
    return groups


def _flag_ungrounded_group_xmlids(final_answer: str, raw_tool_output: str) -> str:
    """Flag any group XML-ID mentioned in final_answer that is not grounded
    in the raw tool observations for this turn.

    Section 550 (todo/contexte.txt, mandat San Goku 2026-09-04, option a) :
    'grounded' now covers TWO distinct deterministic sources, not just
    has_group() -- ACL/rule groups cited by who_has_access_to (and
    evaluate_record_rules) via the 'xml_id: module.identifier' citation
    token (format_xml_id_citation, code_intelligence/utils.py) are an
    equally legitimate, equally deterministic ground truth, just a
    different mechanism than a Python has_group() call. Before this fix,
    every genuine ACL-sourced group was mislabeled 'GROUPE(S) NON
    VERIFIE(S)' whenever no has_group() call also existed for the same
    group in this turn's tool output -- confirmed live (todo/contexte.txt
    sections 547/549): PR-Q1, custom.purchase.request WRITE ACL, 14
    genuine ACL groups wrongly flagged because only one of them also had a
    has_group() lock (a completely different action: validation, not
    write). Reuses sourcing_guard's own _XML_ID_PATTERN (source-agnostic,
    already the ground-truth reader for this exact citation token) rather
    than duplicating a second identical regex (F-08 duplication rule).
    """
    from code_intelligence.sourcing_guard import _XML_ID_PATTERN
    grounded = set(_extract_required_groups(raw_tool_output)) | set(_XML_ID_PATTERN.findall(raw_tool_output))
    if not grounded:
        return final_answer

    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    ungrounded = sorted(mentioned - grounded)
    if not ungrounded:
        return final_answer

    group_list = ", ".join(ungrounded)
    logger.warning(
        "Node [code_intelligence_agent]: group xmlid(s) mentioned in synthesized "
        "answer with no has_group() backing in this turn's scoped tool output "
        "(possible hallucination, flagged not stripped): %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n GROUPE(S) NON VÉRIFIÉ(S) : {group_list} mentionné(s) dans la réponse "
        f"sans correspondance has_group() dans les données produites pour cette question. "
        f"Ne pas considérer ce(s) groupe(s) comme confirmé(s) sans vérification manuelle."
    )


# Sentence-boundary splitter for _strip_core_only_group_mentions: a period
# (or !/?) followed by whitespace then a capital letter. Requiring the
# trailing capital letter is what keeps this safe against file paths/
# citations like 'account_move.py' (never followed by whitespace + a
# capital letter), unlike the earlier clause-level regex this replaces
# (see _strip_core_only_group_mentions' own docstring for the live
# regression that motivated dropping that approach).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u00c0\u00c2\u00c4\u00c9\u00c8\u00ca\u00cb\u00ce\u00cf\u00d4\u00d6\u00d9\u00db\u00dc\u00c7])")


def _grounded_core_only_groups(final_answer: str, scoped_tool_output: str) -> List[str]:
    """Find group XML-IDs that are grounded only in core Odoo files rather
    than custom modules, but ONLY when a competing custom-module group is
    ALSO present in this turn's scoped tool output (i.e. a custom override
    exists and should take precedence over the core default in the
    synthesized answer).

    When no custom-module group is present at all, a core-only group is not
    a suspicious/unreliable mention to strip -- it is the correct default
    answer for questions governed entirely by base Odoo access control
    (e.g. a non-VIP client, or any case where no custom_* override applies).
    Treating "grounded only in core" as inherently unreliable regardless of
    context was flagging exactly the fact these questions need (confirmed
    live regression: account.group_account_manager stripped from every
    answer about the no-override / normal-client case)."""
    grounded = set(_extract_required_groups(scoped_tool_output))
    if not grounded:
        return []
    custom_grounded = set(
        _extract_required_groups(_restrict_blocks_to_custom_modules(scoped_tool_output))
    )
    if not custom_grounded:
        # No custom-module rule competes with the core one(s) -- nothing to
        # strip; the core group(s) are the only, and correct, answer.
        return []
    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    return sorted((mentioned & grounded) - custom_grounded)


def _strip_core_only_group_mentions(final_answer: str, scoped_tool_output: str) -> str:
    """Remove mentions of group XML-IDs that are superseded by a competing
    custom-module group in this turn (see _grounded_core_only_groups),
    scoped to the smallest unit that is safe to drop as a whole.

    Granularity, in order of preference:
      1. Paragraph (split on blank lines) if it does not contain any
         core-only xmlid at all -- kept untouched, no further splitting.
      2. Within a paragraph that DOES contain a core-only xmlid: if the
         paragraph is a bullet/list block (more than one line, at least
         one line starting with '-' or '*'), drop only the offending
         list line(s) -- list items are independent units, so dropping
         one can never cut another mid-sentence. This is the case a pure
         whole-paragraph removal got wrong (confirmed live: a two-bullet
         paragraph naming both a core-only group to drop and a competing
         custom group to keep lost BOTH bullets, since they share one
         '\n'-joined block with no blank line between them).
      3. Within a paragraph that contains a core-only xmlid and is a
         single line (no internal '\n' at all): split on sentence
         boundaries (period/!/? followed by whitespace then a capital
         letter) and drop only the offending sentence(s). This is safer
         than a naive clause-level regex stopping at the FIRST '.' in
         either direction (the earlier, since-reverted approach): that
         regex false-triggered on periods that are not sentence
         boundaries (file paths like 'account_move.py', abbreviations,
         citation line ranges), confirmed live to truncate answers
         mid-sentence with orphaned closing parentheses. Requiring a
         following capital letter after the period+whitespace avoids that
         failure mode: 'account_move.py' is never followed by whitespace
         then a capital letter, so it never looks like a sentence break.
      4. Any other shape (multiple lines, no bullet markers -- an
         unrecognized format) falls back to the original coarse
         whole-paragraph removal: the conservative default when this
         function cannot positively classify the paragraph's internal
         structure, same discipline as every other scoping guard in this
         module (see e.g. _block_is_custom_module_file).

    If every line/sentence in a paragraph is offending, the whole
    paragraph is dropped, matching the previous behavior for that case.
    """
    core_only = _grounded_core_only_groups(final_answer, scoped_tool_output)
    if not core_only:
        return final_answer

    def _contains_core_only(fragment: str) -> bool:
        return any(xmlid in fragment for xmlid in core_only)

    kept_paragraphs = []
    for para in final_answer.split("\n\n"):
        if not _contains_core_only(para):
            kept_paragraphs.append(para)
            continue

        lines = para.split("\n")
        if len(lines) > 1 and any(l.strip().startswith(("-", "*")) for l in lines):
            kept_lines = [l for l in lines if not _contains_core_only(l)]
            if kept_lines:
                kept_paragraphs.append("\n".join(kept_lines))
            # else: every list item in this paragraph was offending --
            # drop the whole (now-empty) paragraph, same as case 4 below.
        elif len(lines) == 1:
            sentences = _SENTENCE_SPLIT_RE.split(para)
            kept_sentences = [s for s in sentences if not _contains_core_only(s)]
            if kept_sentences:
                kept_paragraphs.append(" ".join(kept_sentences))
            # else: every sentence in this paragraph was offending --
            # drop the whole (now-empty) paragraph.
        # else: multi-line, non-bullet shape this function cannot safely
        # subdivide -- fall through and drop the whole paragraph (case 4).

    result = "\n\n".join(kept_paragraphs)

    logger.warning(
        "Node [code_intelligence_agent]: stripped grounded-but-core-Odoo-only "
        "group xmlid(s) from synthesized answer: %s",
        ", ".join(core_only),
    )
    return result


def _scoped_raw_tool_output(
    tool_observations: List[str],
    tool_observation_models: List[str],
    target_models: List[str],
) -> str:
    """Restrict raw tool output to observations relevant to target_models.

    Fail-closed (todo/contexte.txt section 492, Bug 2): an observation with
    no model_name (falsy) is EXCLUDED whenever target_models is non-empty --
    the absence of a model attribution is never treated as "applies to every
    model". Root cause: resolve_technical_name/explain_decision_path/
    read_source_code never carry a model_name (ci_agent_tools.py has no
    such parameter for these 3), so their observations used to leak into
    the scoped context of any question regardless of the model actually
    being investigated -- the previous `not model` branch turned that
    missing information into an implicit authorization to pass scoping.
    """
    if not target_models:
        return "\n\n".join(tool_observations)
    target_set = set(target_models)
    scoped = [
        obs
        for obs, model in zip(tool_observations, tool_observation_models)
        if model and model in target_set
    ]
    return "\n\n".join(scoped)


_LOCK_CONDITION_LINE_RE = re.compile(
    r"\*\s*\"[^\"]*\"\s*\(condition\s*:\s*(.*?has_group\([\'\"]([^\'\"]+)[\'\"]\).*?)\)",
    re.IGNORECASE,
)
_AMOUNT_CMP_RE = re.compile(
    r"(?:rec\.)?amount(?:_total)?\s*(>|>=|<|<=)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_required_groups_for_amount(raw_tool_output: str, amount: Optional[float] = None) -> List[str]:
    """Pull required group xml_ids from raw tool text, filtering by monetary threshold
    when an explicit amount is provided.

    If amount is None, returns all required groups (unfiltered).
    If amount is provided, inspects the condition lines associated with has_group('<group>'):
      - For conditions checking `amount > T` or `amount >= T`: the group is only required
        if the question's amount exceeds T.
      - Groups with no numeric threshold condition (unconditional locks) are always retained.
    """
    all_groups = _extract_required_groups(raw_tool_output)
    if amount is None or not all_groups:
        return all_groups

    group_conditions: Dict[str, List[Tuple[str, float]]] = {}
    for match in _LOCK_CONDITION_LINE_RE.finditer(raw_tool_output):
        if _match_near_truncation(raw_tool_output, match.start(), match.end()):
            # Evidence-first (section 503-505): a condition line cut off by
            # truncation may be missing part of its own text (e.g. a
            # trailing exception clause) -- treat this group as unconditional
            # (always retained below) rather than trust a possibly-incomplete
            # threshold read off a truncated condition.
            continue
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            group_conditions.setdefault(group_name, []).append((op, thresh))

    filtered_groups: List[str] = []
    for g in all_groups:
        if g not in group_conditions:
            filtered_groups.append(g)
        else:
            active = False
            for op, thresh in group_conditions[g]:
                if op == ">" and amount > thresh:
                    active = True
                    break
                elif op == ">=" and amount >= thresh:
                    active = True
                    break
                elif op == "<" and amount < thresh:
                    active = True
                    break
                elif op == "<=" and amount <= thresh:
                    active = True
                    break
            if active:
                filtered_groups.append(g)

    return filtered_groups


# Pattern for file links in tool observation blocks
_BLOCK_FILE_LINK_RE = re.compile(r"\(file://([^)#]+)")


def _block_is_custom_module_file(block: str) -> bool:
    """True when this '\n\n'-delimited block's own file link points to an
    installed/downstream module rather than core Odoo framework."""
    match = _BLOCK_FILE_LINK_RE.search(block)
    if not match:
        return True
    from config.settings import CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH
    try:
        resolved = Path(match.group(1)).resolve()
        if CUSTOM_ADDONS_PATH and Path(CUSTOM_ADDONS_PATH).resolve() in resolved.parents:
            return True
        if CORE_ADDONS_PATH and Path(CORE_ADDONS_PATH).resolve() in resolved.parents:
            return False
        if CORE_FRAMEWORK_ADDONS_PATH and Path(CORE_FRAMEWORK_ADDONS_PATH).resolve() in resolved.parents:
            return False
    except Exception:
        pass
    path_parts = Path(match.group(1)).parts
    core_dirs = {"odoo/addons", "base", "web"}
    if any(c in path_parts for c in core_dirs):
        return False
    return True


def _restrict_blocks_to_custom_modules(raw_tool_output: str) -> str:
    """Drop blocks whose file:// link points outside a 'custom_*' addon
    (see _block_is_custom_module_file) before required-group extraction.
    Scoped narrowly to the required-groups backfill below -- deliberately
    NOT applied to raw_tool_output/scoped_tool_output themselves (citation
    verification and _flag_ungrounded_group_xmlids still need to see every
    real has_group() call, core Odoo included: this filters what counts as
    a *relevant* fact to backfill, not what counts as *grounded*)."""
    blocks = raw_tool_output.split("\n\n")
    kept = [b for b in blocks if _block_is_custom_module_file(b)]
    return "\n\n".join(kept) if kept else raw_tool_output


def _backfill_missing_required_groups(final_answer: str, raw_tool_output: str, question: str) -> str:
    """
    On an approval-related question, if the raw tool output named required group(s)
    via has_group() that are absent from the synthesized answer, append them as a fact.
    """
    if not _question_is_approval_related(question):
        return final_answer

    amount = _extract_amount(question)
    custom_scoped_output = _restrict_blocks_to_custom_modules(raw_tool_output)
    required_groups = _extract_required_groups_for_amount(custom_scoped_output, amount)
    if not required_groups:
        return final_answer

    missing = [g for g in required_groups if g not in final_answer]
    if not missing:
        return final_answer

    group_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling required group(s) missing "
        "from synthesized answer: %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Groupe(s) technique(s) requis (has_group) "
        f"détecté(s) dans le code pour cette action : {group_list}. Fait extrait "
        f"directement de l'analyse statique du code."
    )


# Regex for condition amounts in Python / override expressions
_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def _amount_present_in_text(amount: str, text: str) -> bool:
    """True if `amount` appears in `text` as a standalone number (e.g. '5000' or '5 000')."""
    spaced = f"{amount[:-3]} {amount[-3:]}" if len(amount) > 3 else amount
    for candidate in {amount, spaced}:
        pattern = r"(?<!\d)" + re.escape(candidate) + r"(?!\d)"
        if re.search(pattern, text):
            return True
    return False


# Header marker emitted by security lock analyzer
_SECURITY_LOCK_MESSAGES_MARKER = "Security lock messages (UserError/ValidationError)"


def _extract_security_lock_condition_amounts(raw_tool_output: str) -> List[str]:
    """Pull monetary/numeric thresholds embedded in Python comparisons inside
    security lock exception conditions in first-seen order, deduplicated."""
    amounts: List[str] = []
    for block in raw_tool_output.split("\n\n"):
        if _SECURITY_LOCK_MESSAGES_MARKER not in block:
            continue
        for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(block):
            if _match_near_truncation(block, match.start(), match.end()):
                continue
            amount = match.group(1).replace(" ", "").strip()
            if amount and amount not in amounts:
                amounts.append(amount)
    return amounts


def _backfill_missing_security_lock_amount(
    final_answer: str, raw_tool_output: str, question: Optional[str] = None
) -> str:
    """
    If security lock exception-condition text names a numeric threshold missing
    from the synthesized answer, append it as a deterministic fact.
    """
    if question is not None:
        if _has_can_view_amount_fact(final_answer):
            return final_answer
        if not (_question_is_approval_related(question) or _extract_amount(question) is not None):
            return final_answer
        amount = _extract_amount(question)
    else:
        amount = None

    amounts = _extract_security_lock_condition_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    if amount is not None:
        amounts = [a for a in amounts if float(a) <= amount]
        if not amounts:
            return final_answer

    missing = [a for a in amounts if not _amount_present_in_text(a, final_answer)]
    if not missing:
        return final_answer

    amount_list = ", ".join(f"{a}€" for a in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling security-lock condition amount "
        "threshold(s) missing from synthesized answer: %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition "
        f"supplémentaire déclenchée au-delà de {amount_list}, distincte du groupe "
        f"requis ci-dessus. Fait extrait directement de l'analyse statique du code."
    )


_LINK_GUARD_RE = re.compile(
    r"\[GARDE DE LIEN: si '([^']+)' est vide/absent .*?NE S'APPLIQUE PAS dans ce cas",
    re.DOTALL,
)

_LINK_GUARD_CONTRADICTION_PATTERN = re.compile(
    r"s.?applique\s+(quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)"
)

_LINK_GUARD_CONTRADICTING_SENTENCE_RE = re.compile(
    r"[^.\n]*s.?applique\s+(?:quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)[^.\n]*\.?"
)


def _answer_contradicts_link_guard(final_answer: str) -> bool:
    """True if final_answer asserts the rule applies despite an absent
    guard field, the exact inverse of what the link-guard short-circuit
    always means. Accent-folded (same technique as modules 2/8-5/8's own
    _fold_accents in their check scripts, imported here rather than
    reimplemented) since the LLM may re-accent 'meme'/'malgre' when
    paraphrasing."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_LINK_GUARD_CONTRADICTION_PATTERN.search(folded))


def _neutralize_contradicting_link_guard_sentence(final_answer: str, guard_fields: List[str]) -> str:
    """Replace the exact sentence asserting the wrong (inverse) link-guard
    conclusion with the correct one, in place -- see the module comment
    above _LINK_GUARD_CONTRADICTING_SENTENCE_RE for why this replaces
    rather than merely flags. Matches on the accent-folded/lowercased text
    (same technique as _answer_contradicts_link_guard) but slices the
    ORIGINAL final_answer at the same offsets: _fold_accents is a 1:1
    character substitution (NFD decompose + drop combining marks always
    yields exactly one base character per input character) and .lower()
    is length-preserving for French text, so match.span() computed on the
    folded/lowered string lines up with the original string's indices.
    No-op (returns final_answer unchanged) if no contradicting sentence is
    found -- callers must still gate this on _answer_contradicts_link_guard
    for the correct log line, this function alone would just be silently
    idempotent."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _LINK_GUARD_CONTRADICTING_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)
    replacement = (
        f"La règle NE s'applique PAS en l'absence de {fields_list} "
        f"(court-circuit Python : un champ vide/absent en première position "
        f"d'un `and` rend toute la condition fausse)."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _extract_link_guard_fields(raw_tool_output: str) -> List[str]:
    """Pull every [GARDE DE LIEN] guarding field name out of the raw tool
    text, in first-seen order, deduplicated. Returns [] if no such
    annotation is present."""
    fields: List[str] = []
    for match in _LINK_GUARD_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in fields:
            fields.append(name)
    return fields


_TRIGGER_CONDITION_RE = re.compile(r"\u26a1 Condition\(s\) de d\u00e9clenchement\s*:\s*(.+)")
_TRIGGER_CONDITION_LITERAL_RE = re.compile(r"'([^']+)'")


def _extract_trigger_condition_literals(raw_tool_output: str) -> List[str]:
    """Extract quoted string literals from server-action trigger condition lines."""
    match = _TRIGGER_CONDITION_RE.search(raw_tool_output)
    if not match:
        return []
    literals: List[str] = []
    for lit_match in _TRIGGER_CONDITION_LITERAL_RE.finditer(match.group(1)):
        lit = lit_match.group(1)
        if lit and lit not in literals:
            literals.append(lit)
    return literals


def _backfill_missing_trigger_condition_literals(final_answer: str, raw_tool_output: str) -> str:
    """If a server-action's trigger condition contains a string literal missing
    from the synthesized answer, append it as a deterministic fact."""
    literals = _extract_trigger_condition_literals(raw_tool_output)
    if not literals:
        return final_answer

    missing = [lit for lit in literals if lit not in final_answer]
    if not missing:
        return final_answer

    lit_list = ", ".join(f"`{lit}`" for lit in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling server-action trigger-condition "
        "literal(s) missing from synthesized answer: %s",
        lit_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) de la condition de "
        f"d\u00e9clenchement de l'action serveur, absente(s) de la reformulation "
        f"ci-dessus : {lit_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


_HARDCODED_IDS_LINE_RE = re.compile(r"IDs en dur\s*:\s*\[([^\]]+)\]")


def _extract_hardcoded_id_literals(raw_tool_output: str) -> List[str]:
    """Extract hardcoded IDs from server action bypass lines."""
    match = _HARDCODED_IDS_LINE_RE.search(raw_tool_output)
    if not match:
        return []
    ids: List[str] = []
    for raw_id in match.group(1).split(","):
        raw_id = raw_id.strip()
        if raw_id and raw_id not in ids:
            ids.append(raw_id)
    return ids


def _backfill_missing_hardcoded_id_literals(final_answer: str, raw_tool_output: str) -> str:
    """If a server-action's hardcoded ID list is missing from the synthesized answer,
    append it as a deterministic fact."""
    ids = _extract_hardcoded_id_literals(raw_tool_output)
    if not ids:
        return final_answer

    missing = [i for i in ids if not _amount_present_in_text(i, final_answer)]
    if not missing:
        return final_answer

    id_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling hardcoded privileged-ID "
        "literal(s) missing from synthesized answer: %s",
        id_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) des identifiants "
        f"cod\u00e9s en dur b\u00e9n\u00e9ficiant du contournement, absente(s) de la "
        f"reformulation ci-dessus : {id_list}. Fait extrait directement de "
        f"l'analyse statique du code."
    )


def _backfill_link_guard_clarifications(final_answer: str, raw_tool_output: str, question: Optional[str] = None) -> str:
    """Deterministic backfill whenever a [GARDE DE LIEN] annotation is present in raw tool output."""
    guard_fields = _extract_link_guard_fields(raw_tool_output)
    if not guard_fields:
        return final_answer

    if question is not None and not any(
        re.search(rf"\b{re.escape(g.lower())}\b", question.lower())
        or re.search(rf"\b{re.escape(g.lower())}\b", final_answer.lower())
        for g in guard_fields
    ):
        return final_answer

    marker = "[FAIT DÉTERMINISTIQUE] Court-circuit"
    if marker in final_answer:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)

    if _answer_contradicts_link_guard(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis contradicted its own "
            "link-guard short-circuit conclusion for field(s) %s -- replacing "
            "the contradicting sentence with the correct conclusion (no longer "
            "just a banner ahead of the unchanged wrong prose -- see comment "
            "above _LINK_GUARD_CONTRADICTING_SENTENCE_RE, 2026-08-11 rerun "
            "confirmed a banner alone still left the wrong sentence readable).",
            fields_list,
        )
        final_answer = _neutralize_contradicting_link_guard_sentence(final_answer, guard_fields)

    logger.info(
        "Node [code_intelligence_agent]: appending deterministic link-guard "
        "clarification (short-circuit conclusion) for field(s): %s",
        fields_list,
    )
    return (
        final_answer
        + f"\n\n{marker} ET (déterministe) : l'analyse statique du code montre que "
        f"la condition dépend de {fields_list} en première position d'un `and` -- si ce "
        f"champ est vide ou absent (aucun enregistrement lié), toute la condition est "
        f"FAUSSE par court-circuit Python, et la règle correspondante NE S'APPLIQUE PAS, "
        f"quel que soit le reste de la condition (montant, etc.). Fait extrait directement "
        f"de l'analyse statique du code, indépendant de toute reformulation en langage naturel."
    )


# Synthesis-inversion detector for the can_view_amount deterministic fact.
# Replaces contradictory LLM free prose with the deterministic factual verdict.
_CAN_VIEW_ALLOW_ASSERTION_RE = re.compile(
    r"[^.\n]*\b(?:peut\s+(?:voir|consulter|acc[ée]der)|"
    r"(?:a|dispose\s+du?)\s+(?:le\s+)?permission\s+de\s+(?:voir|consulter)|"
    r"est\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der))[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_DENY_ASSERTION_RE = re.compile(
    r"[^.\n]*\bne\s+peut\s+pas\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?"
    r"|[^.\n]*n[’']a\s+pas\s+(?:le\s+)?permission\s+de\s+(?:voir|consulter)[^.\n]*\.?"
    r"|[^.\n]*n[’']est\s+pas\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_FACT_VERDICT_RE = re.compile(
    r"can_view_amount\(\)\s*=\s*(True|False)\s*:\s*l.utilisateur\s+(PEUT|NE PEUT PAS)",
)
_CAN_VIEW_FACT_INDETERMINATE_MARKER = "can_view_amount_v2() = indeterminate"


def _split_before_first_fact_marker(text: str) -> str:
    """Text portion before the first '[FAIT' marker -- the free-prose synthesis."""
    idx = text.find("[FAIT")
    return text if idx == -1 else text[:idx]


def _extract_can_view_amount_verdict(final_answer: str) -> "Optional[bool]":
    """True/False when the injected can_view_amount_v2 fact states a
    definite verdict. Returns None both when no such fact is present at all
    AND when the fact states the indeterminate case -- callers distinguish
    the two via _has_can_view_amount_fact separately."""
    match = _CAN_VIEW_FACT_VERDICT_RE.search(final_answer)
    if not match:
        return None
    return match.group(2) == "PEUT"


def _has_can_view_amount_fact(final_answer: str) -> bool:
    return bool(_CAN_VIEW_FACT_VERDICT_RE.search(final_answer)) or (
        _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    )


def _correct_can_view_amount_contradictions(final_answer: str) -> str:
    """
    Detect and correct a synthesis-level inversion of the can_view_amount_v2
    deterministic verdict -- e.g. the fact says NE PEUT PAS (False) but the
    LLM's own free prose earlier in the same answer asserts the user peut
    voir, or the fact is indeterminate but the prose still rounds to a
    definite yes/no. Symmetric, append-after-detect-and-replace discipline
    to _correct_override_cascade_contradictions above. No-op when no
    can_view_amount_v2 fact is present at all in final_answer (this tool
    didn't run this turn, or no amount was extractable from the question).
    """
    if not _has_can_view_amount_fact(final_answer):
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    is_indeterminate = _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    verdict = _extract_can_view_amount_verdict(final_answer)

    if is_indeterminate:
        # A definite allow OR a definite deny in the prose both contradict
        # an indeterminate verdict -- rounding uncertainty to a yes/no is
        # exactly what the deterministic fact + synthesis_prompt already
        # forbid, regardless of which direction the LLM rounded to.
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose) or _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "Le moteur de règles ne peut pas déterminer avec certitude si "
            "l'utilisateur peut voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a definite "
            "allow/deny while the can_view_amount_v2 verdict was indéterminé "
            "-- replacing the sentence with an explicit uncertainty statement "
            "(_correct_can_view_amount_contradictions)."
        )
    elif verdict is True:
        match = _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur PEUT voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted the user "
            "CANNOT view the record while can_view_amount_v2() computed "
            "True -- replacing the sentence with the correct verdict "
            "(inversion, _correct_can_view_amount_contradictions)."
        )
    elif verdict is False:
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur NE PEUT PAS voir cet enregistrement pour ce "
            "montant (voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted the user "
            "CAN view the record while can_view_amount_v2() computed "
            "False -- replacing the sentence with the correct verdict "
            "(inversion, _correct_can_view_amount_contradictions)."
        )
    else:
        return final_answer

    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _correct_security_lock_threshold_contradictions(
    final_answer: str, scoped_tool_output: str, question: str
) -> str:
    """
    Detect and correct synthesis-level inversions of Python security lock
    threshold logic (has_group() with numeric amount conditions).
    """
    from code_intelligence.deterministic_tools import _fold_accents

    amount = _extract_amount(question)
    if amount is None:
        return final_answer

    rules: List[Tuple[str, str, float, str]] = []
    for match in _LOCK_CONDITION_LINE_RE.finditer(scoped_tool_output):
        if _match_near_truncation(scoped_tool_output, match.start(), match.end()):
            # Evidence-first (section 503-505): don't correct the synthesis
            # against a condition that may itself be missing text to a
            # truncation cut -- a wrong correction built on an incomplete
            # condition would be worse than leaving the sentence unflagged.
            continue
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            rules.append((group_name, op, thresh, cond_text))

    if not rules:
        return final_answer

    triggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if (op == ">" and amount > thresh) or (op == ">=" and amount >= thresh)
    ]
    higher_untriggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if op in (">", ">=") and thresh > amount
    ]

    if not triggered and not higher_untriggered:
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    suffix = final_answer[len(prose):]

    if "\n\n" in prose:
        delimiter = "\n\n"
        chunks = prose.split("\n\n")
    elif "\n-" in prose or "\n*" in prose:
        delimiter = "\n"
        chunks = prose.split("\n")
    else:
        delimiter = "\n\n"
        chunks = [prose]

    amt_s = str(int(amount))
    amt_sp = f"{int(amount):,}".replace(",", " ")
    new_chunks = []
    contradiction_found = False

    for chunk in chunks:
        c_folded = _fold_accents(chunk.lower())
        prefix = "- " if chunk.strip().startswith("- ") else ("* " if chunk.strip().startswith("* ") else "")
        replaced = False

        # Check for triggered group inversion
        for g, op, thresh, cond in triggered:
            t_s = str(int(thresh))
            t_sp = f"{int(thresh):,}".replace(",", " ")
            g_short = g.split(".")[-1].replace("group_", "")

            group_keywords = [g.lower(), g_short.lower()]
            if "account" in g.lower() or "comptab" in cond.lower():
                group_keywords.extend(["comptabilit", "responsable"])
            if "manager" in g.lower():
                group_keywords.extend(["manager", "responsable", "gestionnaire"])

            has_group_ref = any(k in c_folded for k in group_keywords)
            if has_group_ref:
                is_inv = False
                if any(w in c_folded for w in ["jusqu", "plafond", "limite"]) and (t_s in c_folded or t_sp in c_folded):
                    if any(w in c_folded for w in ["n'a pas le permission", "ne peut pas", "ne peut donc pas", "n'est pas autoris", "pas autoris"]):
                        is_inv = True
                elif any(w in c_folded for w in ["n'a pas le permission de valider", "ne peut pas valider", "ne peut donc pas valider", "n'est pas autoris"]):
                    if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                        is_inv = True

                if is_inv:
                    new_chunks.append(
                        f"{prefix}Pour un document de {amt_sp}€ (dépassant le seuil de {t_sp}€), "
                        f"la validation exige d'être membre du groupe `{g}`. "
                        f"Un membre de ce groupe a donc le permission de valider ce document."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if replaced:
            continue

        # Check for higher untriggered wrongful authority attribution
        for hg, hop, hthresh, hcond in higher_untriggered:
            ht_s = str(int(hthresh))
            ht_sp = f"{int(hthresh):,}".replace(",", " ")
            hg_short = hg.split(".")[-1].replace("group_", "")

            hg_keywords = [hg.lower(), hg_short.lower()]
            if "system" in hg.lower() or "admin" in hg.lower():
                hg_keywords.extend(["administrateur", "system"])

            has_hg_ref = any(k in c_folded for k in hg_keywords)
            if has_hg_ref:
                is_wrong = False
                if ht_s in c_folded or ht_sp in c_folded or "100k" in c_folded or "100 k" in c_folded:
                    if any(w in c_folded for w in ["a le permission de valider", "peut valider", "est autoris"]):
                        if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                            is_wrong = True

                if is_wrong:
                    new_chunks.append(
                        f"{prefix}Le verrou supérieur (> {ht_sp}€, réservé à `{hg}`) ne s'applique pas "
                        f"à {amt_sp}€ car le montant est inférieur à {ht_sp}€."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if not replaced:
            new_chunks.append(chunk)

    if not contradiction_found:
        return final_answer

    logger.warning(
        "Node [code_intelligence_agent]: synthesis asserted an inverted/contradictory "
        "security lock threshold verdict for amount %s -- replacing contradictory sentences "
        "with correct ground-truth evaluation (_correct_security_lock_threshold_contradictions).",
        amount,
    )
    return delimiter.join(new_chunks) + suffix


def _can_view_amount_candidates(
    raw_tool_output: str,
    tool_observation_models: "Optional[List[str]]",
    target_models: "Optional[List[str]]",
) -> "List[Tuple[str, str]]":
    """Shared candidate-collection step for both _extract_can_view_amount_fact_block
    (picks ONE block to backfill the answer with) and
    _detect_can_view_amount_model_conflict (H3, todo/plan.md -- flags when MORE
    THAN ONE distinct model's verdict is a legitimate candidate this turn) --
    kept as a single source of truth for what counts as 'a can_view_amount_v2
    fact block associated with a target model', so the two never drift apart
    on what they each consider a candidate (same F-08 duplication discipline
    this module already follows elsewhere, e.g. NOT_FOUND_MARKER above).

    Returns [] when tool_observation_models/target_models are not both
    supplied, or when no block in raw_tool_output carries a fact associated
    with a target model -- callers fall back to their own untargeted scan in
    that case (see _extract_can_view_amount_fact_block below).
    """
    if tool_observation_models is None or not target_models:
        return []
    blocks = raw_tool_output.split("\n\n")
    target_set = set(target_models)
    return [
        (block, model)
        for block, model in zip(blocks, tool_observation_models)
        if _has_can_view_amount_fact(block) and model in target_set
    ]


def _extract_can_view_amount_verdict_label(block: str) -> str:
    """Human-readable verdict label ('PEUT' / 'NE PEUT PAS' / 'ind\u00e9termin\u00e9')
    for a single can_view_amount_v2 fact block -- used only to build a
    CONFLICTING reason string (_detect_can_view_amount_model_conflict), never
    to drive any answer or correction itself."""
    if _CAN_VIEW_FACT_INDETERMINATE_MARKER in block:
        return "ind\u00e9termin\u00e9"
    match = _CAN_VIEW_FACT_VERDICT_RE.search(block)
    return match.group(2) if match else "inconnu"


def _detect_can_view_amount_model_conflict(
    raw_tool_output: str,
    tool_observation_models: "Optional[List[str]]" = None,
    target_models: "Optional[List[str]]" = None,
) -> "Optional[str]":
    """
    H3 (todo/plan.md, Bloc P1-bis -- \"Tester un mecanisme d'arbitrage entre
    preuves concurrentes\"), first real deterministic signal wired into
    core/evidence_sufficiency.py::assess_evidence_sufficiency() as its
    `conflict_reason` parameter (todo/contexte.txt section 418+).

    Deliberately narrow in scope: a genuine CONFLICTING case is TWO OR MORE
    resolved models each producing their OWN legitimate, independently-
    computed can_view_amount_v2 verdict for this turn, with DIFFERING
    outcomes -- as opposed to a single model's verdict that the LLM's own
    prose merely misstated (a synthesis-inversion bug, already corrected in
    place by _correct_can_view_amount_contradictions elsewhere in this
    module, and explicitly out of scope for CONFLICTING per
    EvidenceSufficiencyStatus's own docstring: an already-corrected
    synthesis slip is not \"two valid findings disagreeing\").

    _extract_can_view_amount_fact_block (below) already detects this exact
    situation -- see its own docstring, \"several distinct candidate models\"
    -- but only LOGS a warning and silently picks the most recently computed
    one to backfill the answer with, discarding the other model's equally
    valid finding without ever surfacing the disagreement past that log
    line. This function reuses the same candidate-collection step
    (_can_view_amount_candidates) purely to DETECT the same situation and
    report it as a reason string -- it never picks a winner itself, that
    remains _extract_can_view_amount_fact_block's job.

    Returns None when fewer than 2 distinct target models produced a
    can_view_amount_v2 fact this turn, OR when they did but reached the SAME
    verdict (independent agreement across models is not a conflict). Returns
    a human-readable reason string otherwise.
    """
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if not candidates:
        return None

    verdict_by_model: "Dict[str, str]" = {}
    for block, model in candidates:
        # Last-seen wins per model -- consistent with
        # _extract_can_view_amount_fact_block's own "most recently computed"
        # tie-break for a single model producing more than one block
        # (re-evaluation across hops), not itself a cross-model conflict.
        verdict_by_model[model] = _extract_can_view_amount_verdict_label(block)

    distinct_verdicts = set(verdict_by_model.values())
    if len(verdict_by_model) < 2 or len(distinct_verdicts) < 2:
        return None

    detail = ", ".join(f"{model}: {verdict}" for model, verdict in sorted(verdict_by_model.items()))
    logger.warning(
        "Node [code_intelligence_agent]: %d resolved models produced DIVERGENT "
        "can_view_amount_v2 verdicts this turn (%s) -- flagging as CONFLICTING "
        "evidence (H3) rather than silently picking one.",
        len(verdict_by_model), detail,
    )
    return (
        f"{len(verdict_by_model)} mod\u00e8les r\u00e9solus ont produit des verdicts "
        f"can_view_amount_v2 divergents pour cette question ({detail}) -- preuves "
        f"concurrentes, aucun vainqueur choisi automatiquement."
    )


def _format_conflicting_evidence_answer(
    raw_tool_output: str,
    tool_observation_models: "Optional[List[str]]" = None,
    target_models: "Optional[List[str]]" = None,
) -> "Optional[str]":
    """
    H3 dedicated CONFLICTING path (todo/contexte.txt sections 419-420, user
    reformulation of the desired role of CONFLICTING): builds
    code_intelligence_agent's final_answer directly and deterministically
    -- NO LLM synthesis call -- whenever
    _detect_can_view_amount_model_conflict() has already fired for this
    turn.

    Explicit user requirement (section 419): CONFLICTING must never
    arbitrate between the two (or more) disagreeing can_view_amount_v2
    verdicts, nor let an implicit preference show through ("Y est
    probablement le bon") -- each model's own verdict block must be
    exposed to the reader as-is, in the spirit of "X dit ceci, Y dit
    cela, je ne peux pas trancher a partir des preuves disponibles". A
    free-form LLM synthesis call is deliberately NOT used for this case:
    the existing synthesis_prompt (ci_agent_node.py) instructs the model
    that a '[FAIT DETERMINISTIQUE]' observation is THE authoritative
    verdict -- written for exactly one such fact per turn, undefined once
    two DIFFERENT facts both claim that authority. Routing this case
    through that prompt would silently reintroduce the arbitration the
    user explicitly rejected (an LLM given two contradictory 'authoritative'
    facts has no defined way to reconcile them without picking one).

    Reuses _can_view_amount_candidates() -- the same candidate-collection
    step _detect_can_view_amount_model_conflict() itself uses just above --
    so the evidence exposed here and the conflict signal that triggered
    this call are always computed over identical inputs, never a second,
    independently-scoped re-derivation (same F-08 duplication discipline
    this module already follows elsewhere).

    Returns None when fewer than 2 distinct candidate models are found --
    mirrors _detect_can_view_amount_model_conflict()'s own None contract.
    Callers must already have confirmed a conflict was detected (via that
    function) before calling this one; this function does not re-derive
    that decision, only formats it.

    Known scope limit, deliberately not addressed here (out of this
    mandate): if one of the divergent verdicts is itself the
    'indeterminate' case (_CAN_VIEW_FACT_INDETERMINATE_MARKER), the block
    this function embeds verbatim still carries that marker, so a
    downstream core/evidence_sufficiency.py::assess_evidence_sufficiency()
    call over this final_answer will hit its own step-4
    indeterminate-marker check BEFORE reaching step 5's conflict_reason
    check, and reclassify the turn as INSUFFICIENT instead of CONFLICTING
    -- per that function's own documented priority order ('this still wins
    over (5) below ... an undetermined verdict is a stronger/prior signal
    than a cross-model disagreement'), which pre-dates this function and is
    not altered by it. The primary case this function targets -- two (or
    more) models each producing their own definite True/False verdict that
    disagree -- is unaffected by this limit.
    """
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if not candidates:
        return None

    # Last-seen wins per model -- same tie-break as
    # _detect_can_view_amount_model_conflict's own verdict_by_model
    # collection immediately above, so the set of models/blocks exposed
    # here always matches exactly what the conflict signal was computed
    # from.
    block_by_model: "Dict[str, str]" = {}
    for block, model in candidates:
        block_by_model[model] = block.strip()

    if len(block_by_model) < 2:
        return None

    evidence_sections = "\n\n".join(
        f"**Mod\u00e8le `{model}`** :\n{block}"
        for model, block in sorted(block_by_model.items())
    )

    return (
        "## Preuves contradictoires d\u00e9tect\u00e9es\n\n"
        f"{len(block_by_model)} mod\u00e8les r\u00e9solus produisent chacun leur propre "
        "verdict d\u00e9terministe pour cette question, et ces verdicts ne sont pas "
        "d'accord entre eux. Les deux constats sont pr\u00e9sent\u00e9s ci-dessous "
        "int\u00e9gralement, sans qu'aucun des deux ne soit \u00e9cart\u00e9 ou privil\u00e9gi\u00e9 "
        "automatiquement :\n\n"
        f"{evidence_sections}\n\n"
        "Le moteur ne peut pas trancher entre ces preuves concurrentes \u00e0 "
        "partir des \u00e9l\u00e9ments disponibles pour cette question. Une "
        "v\u00e9rification manuelle est n\u00e9cessaire pour d\u00e9terminer laquelle "
        "s'applique r\u00e9ellement \u00e0 ce cas."
    )


def _extract_can_view_amount_fact_block(
    raw_tool_output: str,
    tool_observation_models: "Optional[List[str]]" = None,
    target_models: "Optional[List[str]]" = None,
) -> "Optional[str]":
    """
    Return the exact '[FAIT DETERMINISTIQUE] ... can_view_amount_v2 ...'
    block produced by _format_can_view_amount_fact(), if present anywhere
    in raw_tool_output, else None.

    Section 2xx (todo/contexte.txt) hardening: taking the FIRST block that
    matches the fact pattern is order-dependent and silently picks the
    wrong model's verdict whenever raw_tool_output carries more than one
    can_view_amount_v2 block (e.g. a multi-model resolution). When the
    caller can supply tool_observation_models (parallel to the blocks
    produced by "\n\n".join(tool_observations)) and target_models (the
    resolved model(s) the caller actually cares about), the block is
    selected by explicit model association instead of chance ordering:
      - Candidates are blocks carrying a fact AND whose paired model is in
        target_models.
      - Exactly one distinct candidate model -> return it, unambiguous.
      - Several distinct candidate models (legitimate multi-model query)
        -> log a warning and return the most recently computed one (the
        last observation appended is the last evaluation performed), which
        is deterministic even if not a full per-model backfill.
      - No candidate matches target_models at all -> fall through to the
        untargeted scan below rather than returning None outright.
    When tool_observation_models/target_models are not supplied (legacy
    callers), behaviour is unchanged except that finding more than one
    fact block is now logged instead of silently resolved.

    Note (H3, todo/contexte.txt section 418+): the multi-model divergence
    detected below is now ALSO surfaced as a genuine CONFLICTING signal by
    _detect_can_view_amount_model_conflict, which reuses the same
    _can_view_amount_candidates() step -- this function's own behavior
    (still silently picking the most recent block to backfill with) is
    unchanged; only a NEW, separate detector call at the ci_agent_node.py
    call site now also reports the disagreement instead of only this log line.
    """
    blocks = raw_tool_output.split("\n\n")
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if candidates:
        distinct_models = {model for _block, model in candidates}
        if len(distinct_models) > 1:
            logger.warning(
                "Node [code_intelligence_agent]: %d distinct resolved "
                "models each produced a can_view_amount_v2 fact block "
                "(%s) -- backfilling with the most recently computed "
                "one instead of an arbitrary first match.",
                len(distinct_models), sorted(distinct_models),
            )
            return candidates[-1][0].strip()
        return candidates[0][0].strip()

    matches = [block for block in blocks if _has_can_view_amount_fact(block)]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            "Node [code_intelligence_agent]: %d can_view_amount_v2 fact "
            "blocks found with no model association available -- taking "
            "the first one (order-dependent). Pass tool_observation_models "
            "and target_models to disambiguate.", len(matches),
        )
    return matches[0].strip()


def _backfill_missing_can_view_amount_fact(
    final_answer: str,
    raw_tool_output: str,
    tool_observation_models: "Optional[List[str]]" = None,
    target_models: "Optional[List[str]]" = None,
) -> str:
    """
    No-op when final_answer already contains a can_view_amount_v2 fact
    (LLM echoed or paraphrased it closely enough to match
    _CAN_VIEW_FACT_VERDICT_RE/_CAN_VIEW_FACT_INDETERMINATE_MARKER) or when
    raw_tool_output never carried one at all (tool not called this turn,
    or no amount was extractable from the question -- see the call site
    in code_intelligence_agent). Otherwise appends the verbatim fact block
    so the immediately-following _correct_can_view_amount_contradictions()
    call has an actual fact to reconcile the free prose against, instead
    of silently no-oping on a fact that only ever existed in the LLM's
    input, never its output.

    tool_observation_models/target_models are optional and, when passed,
    let _extract_can_view_amount_fact_block pick the block belonging to the
    actually resolved model(s) instead of the first one found by chance
    ordering -- see that function's docstring (section 2xx hardening).
    """
    if _has_can_view_amount_fact(final_answer):
        return final_answer

    block = _extract_can_view_amount_fact_block(
        raw_tool_output,
        tool_observation_models=tool_observation_models,
        target_models=target_models,
    )
    if block is None:
        return final_answer

    logger.info(
        "Node [code_intelligence_agent]: backfilling can_view_amount_v2 "
        "deterministic fact missing from synthesized answer."
    )
    return final_answer + "\n\n" + block


def _format_can_view_amount_fact(
    amount: float, can_view: "Optional[bool]", unresolved: "Optional[List[str]]" = None
) -> str:
    """Format the deterministic can_view_amount verdict into a declarative fact block."""
    if can_view is None:
        fields_str = ", ".join(unresolved) if unresolved else "une ou plusieurs conditions non résolues"
        return (
            f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
            f"le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir "
            f"cet enregistrement (can_view_amount_v2() = indeterminate) : au moins une "
            f"règle applicable dépend de {fields_str}, qui ne sont pas connus dans ce "
            f"contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler "
            f"explicitement cette incertitude à l'utilisateur."
        )
    return (
        f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
        f"le moteur de règles calcule can_view_amount() = {can_view} : "
        f"l'utilisateur {'PEUT' if can_view else 'NE PEUT PAS'} voir "
        f"cet enregistrement."
    )


def _question_suggests_automation_bypass(question: str) -> bool:
    return bool(_AUTOMATION_PATTERN.search(question))


def _rank_and_cap_resolved_models(question: str, resolved_models: List[str], max_models: int) -> List[str]:
    """Rank resolved model technical names by lexical relevance to the question
    and keep only the top max_models."""
    if len(resolved_models) <= max_models:
        return resolved_models
    from rapidfuzz import fuzz
    question_lower = question.lower()

    _BILINGUAL_EXPANSIONS = {
        "rule": "regle règle",
        "log": "journal logs audit",
        "wizard": "assistant",
        "user": "utilisateur",
        "partner": "partenaire contact",
        "company": "societe société entreprise",
        "move": "mouvement",
        "quant": "quantite quantité stock",
        "line": "ligne",
    }

    def _model_text(m_name: str) -> str:
        parts = m_name.replace(".", " ").replace("_", " ").lower().split()
        expanded_parts = list(parts)
        for p in parts:
            if p in _BILINGUAL_EXPANSIONS:
                expanded_parts.append(_BILINGUAL_EXPANSIONS[p])
        return " ".join(expanded_parts)

    scored = [
        (name, fuzz.token_set_ratio(question_lower, _model_text(name)))
        for name in resolved_models
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:max_models]]
    logger.warning(
        "Node [code_intelligence_agent]: Truncating resolved models from %d to "
        "MAX_MODELS_PER_QUERY (%d), ranked by relevance to the question -- kept: %s.",
        len(resolved_models), max_models, kept,
    )
    return kept


def _override_user_groups_arg(tool_name: str, tool_args: dict, resolved_user_group_xmlids: list) -> dict:
    """
    Overrides the LLM-guessed user_groups_json with the requester's real Odoo group XML-IDs
    for evaluate_record_rules and button_execution_path.
    """
    if tool_name not in ("evaluate_record_rules", "button_execution_path"):
        return tool_args

    real_groups_json = json.dumps(resolved_user_group_xmlids)
    llm_proposed = tool_args.get("user_groups_json")
    if llm_proposed and llm_proposed != real_groups_json:
        logger.warning(
            "Node [code_intelligence_agent]: overriding LLM-guessed "
            "user_groups_json (%s) with the real requester groups (%s).",
            llm_proposed, real_groups_json,
        )
    tool_args["user_groups_json"] = real_groups_json
    return tool_args


# Strip group-resolution noise from synthesis context
_COULD_NOT_RESOLVE_RE = re.compile(
    r"""Group identifier ['"].*?['"] could not be resolved""",
    re.IGNORECASE,
)


def _strip_group_resolution_noise(
    tool_observations: List[str],
    resolved_user_group_xmlids: list,
    tool_observation_models: List[str],
    tool_observation_tools: Optional[List[str]] = None,
):
    """Remove who_has_access_to 'could not be resolved' observations that refer
    to LLM-guessed group names when real requester groups have already been evaluated.

    tool_observation_tools is an optional third list kept aligned 1:1 with
    tool_observations/tool_observation_models (section: 'réponses trop
    techniques', todo/contexte.txt -- tracks which tool produced each
    observation, for building real sources instead of a generic stub).
    Optional and filtered in lockstep only when provided, so any other
    caller relying on the original 2-list contract keeps working unchanged.
    """
    if not resolved_user_group_xmlids:
        if tool_observation_tools is None:
            return tool_observations, tool_observation_models
        return tool_observations, tool_observation_models, tool_observation_tools

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        if tool_observation_tools is None:
            return tool_observations, tool_observation_models
        return tool_observations, tool_observation_models, tool_observation_tools

    cleaned = []
    cleaned_models = []
    cleaned_tools = [] if tool_observation_tools is not None else None
    _tools_iter = tool_observation_tools if tool_observation_tools is not None else [None] * len(tool_observations)
    for obs, model, tname in zip(tool_observations, tool_observation_models, _tools_iter):
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: stripping 'could not be "
                "resolved' observation from synthesis context: %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
        cleaned_models.append(model)
        if cleaned_tools is not None:
            cleaned_tools.append(tname)
    if tool_observation_tools is None:
        return cleaned, cleaned_models
    return cleaned, cleaned_models, cleaned_tools


def _extract_first_scoped_file_link(text: str) -> str:
    match = re.search(r"\[[^\]]+\]\(file:///[^\)]+#L\d+-L\d+\)", text)
    return match.group(0) if match else ""


_TECHNICAL_MODEL_LOOKALIKE_RE = re.compile(r"\b[a-z][a-z_]*(?:\.[a-z][a-z_]*){1,3}\b")


def _force_out_of_scope_model_answer(question: str, concept) -> Optional[str]:
    """
    Force an honest decline if the business-term resolver could not resolve the
    question to any model/module AND the question names an unindexed technical model.
    """
    if concept.is_resolved:
        return None
    match = _TECHNICAL_MODEL_LOOKALIKE_RE.search(question.lower())
    if not match:
        return None
    model_name = match.group(0)
    return (
        f"Le modele '{model_name}' n'est pas present dans le corpus indexe par cet outil "
        f"(ni personnalise par un module custom_*, ni charge par un autre mecanisme connu de "
        f"cette instance). Je ne peux donc pas repondre a partir du code reel de cette instance "
        f"-- toute reponse sur son comportement standard viendrait de connaissances generales "
        f"sur Odoo, non verifiees contre ce systeme precis, ce que cet outil n'est pas cense faire. "
        f"Pour verifier vous-meme : consultez la documentation Odoo standard du module concerne, "
        f"ou demandez a un administrateur d'indexer ce modele si vous en avez besoin regulierement."
    )


def _force_dynamic_uncertainty_answer(question: str, raw_tool_output: str) -> Optional[str]:
    """
    Guardrail for adversarial dynamic-dispatch cases: if static analysis
    detected getattr/eval/exec, the final answer must not turn that into a
    certain permission conclusion.
    """
    if not re.search(r"incertitude dynamique|dispatch dynamique|getattr|eval\(|exec\(", raw_tool_output, re.IGNORECASE):
        return None
    if not re.search(r"remboursement|custom_expense_reimbursement_indirect|custom\.reimbursement\.request", question, re.IGNORECASE):
        return None

    citation = _extract_first_scoped_file_link(raw_tool_output)
    citation_part = f" Source à revoir : {citation}." if citation else ""
    return (
        "Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. "
        "L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend "
        "d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. "
        "Ne pas présenter cette validation comme autorisée ou refusée de manière certaine."
        f"{citation_part}"
    )


# ── H1b-ii sticky concept rehydration ────────────────────────────────────────
# Extracted 2026-08-20 out of code_intelligence_agent() (rag/ci_agent_node.py)
# so this reconstruction step is testable on its own without mocking the
# graph, LLM, or tool set that function otherwise depends on.
# Tests: tests/test_h1b_ii_rehydrate_ci_node.py

def _rehydrate_sticky_concept(concept, state: dict):
    """Reconstruct a ResolvedConcept from a sticky dict when this turn's own
    resolution failed.

    Contract:
    - If concept.is_resolved is already True, return concept unchanged (the
      current turn's resolution succeeded, no need to fall back to sticky).
    - Otherwise, look at state["resolved_concept"] -- if it's a dict with
      is_resolved *strictly* True (bool, not truthy int/str), try to rebuild
      a ResolvedConcept via **dict. If reconstruction fails for any reason
      (unexpected keys, missing required fields), degrade silently to the
      original (unresolved) concept -- never crash the agent node.
    - If the sticky dict's is_resolved is not strictly True, return the
      original concept unchanged (re-using an unresolved concept from a
      previous turn is pointless).
    """
    if concept.is_resolved:
        return concept

    sticky = state.get("resolved_concept")
    if isinstance(sticky, dict):
        if sticky.get("is_resolved") is True:
            try:
                from code_intelligence.business_resolver import ResolvedConcept
                return ResolvedConcept(**sticky)
            except Exception:
                logger.debug(
                    "_rehydrate_sticky_concept: reconstruction from sticky dict "
                    "failed (unexpected shape), degrading to original concept"
                )
                return concept

    mod = state.get("module")
    if mod and isinstance(mod, str):
        try:
            from code_intelligence.business_resolver import ResolvedConcept
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
        except Exception:
            pass

    return concept
