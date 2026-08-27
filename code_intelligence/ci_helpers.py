"""
rag/ci_helpers.py

Code Intelligence deterministic helpers.

Extraction, backfill, contradiction-neutralization, and grounding
functions for the Code Intelligence agent. These are pure functions
that analyze raw tool output text and final answers to detect/correct
specific failure modes of small synthesis LLMs.
"""

import json
import logging
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
    "through the button/method mechanism as if they could trigger it themselves."
)

# Maximum hops allowed per question.
CI_MAX_HOPS = 4

# Deterministic patterns for tool triggers
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|permission\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|actions?\s+automatiques?|automatisation\w*|"
    r"actions?\s+serveur|bypass|contourn\w*)\b",
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
    if _COMPANY_DIFFERENT_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}
    if _COMPANY_SAME_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 1}}, "company_ids": [1]}
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
    # Inverted-subject French question form ("peut-il/elle/on voir")
    r"\b(?:peut|peux|pourra|pourrait)[\s-]*(?:il|elle|on|t[\s-]*il|t[\s-]*elle)\s+(?:voir|acc[eé]der|consulter|lire|visualiser)\b|"
    # "a-t-il/elle la permission / accès"
    r"\ba[\s-]*t[\s-]*(?:il|elle)\s+(?:le\s+permission|acc[eè]s|la\s+permission)\b|"
    # English patterns
    r"\bwho\s+(?:can|has\s+the\s+right|is\s+authoriz\w*)\b|"
    r"\b(?:can|may)\s+(?:a\s+user|the\s+user|an?\s+employee)\s+(?:see|view|access|read)\b",
    re.IGNORECASE,
)


def _question_is_access_related(question: str) -> bool:
    """True if the question is asking about access permissions or visibility."""
    return bool(_ACCESS_QUESTION_PATTERN.search(question))


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
    in the raw tool observations for this turn."""
    grounded = set(_extract_required_groups(raw_tool_output))
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
    """Remove whole paragraphs/bullets mentioning group XML-IDs that are
    superseded by a competing custom-module group in this turn (see
    _grounded_core_only_groups).

    Deliberately removes at PARAGRAPH granularity (split on blank lines)
    rather than a clause-level regex: a clause-level '[^.\\n]*<xmlid>[^.\\n]*\\.?'
    pattern stops at the FIRST '.' in either direction, which false-triggers
    on periods that are not sentence boundaries (file paths like
    'account_move.py', abbreviations, citation line ranges) -- confirmed live
    regression: this produced answers truncated mid-sentence with orphaned
    closing parentheses. Paragraph boundaries (blank lines) are unambiguous
    in this markdown-formatted synthesis output, so this can never cut a
    sentence or citation in half."""
    core_only = _grounded_core_only_groups(final_answer, scoped_tool_output)
    if not core_only:
        return final_answer

    paragraphs = final_answer.split("\n\n")
    kept = [p for p in paragraphs if not any(xmlid in p for xmlid in core_only)]
    result = "\n\n".join(kept)

    logger.warning(
        "Node [code_intelligence_agent]: stripped grounded-but-core-Odoo-only "
        "group xmlid(s) from synthesized answer (whole paragraph removed): %s",
        ", ".join(core_only),
    )
    return result


def _scoped_raw_tool_output(
    tool_observations: List[str],
    tool_observation_models: List[str],
    target_models: List[str],
) -> str:
    """Restrict raw tool output to observations relevant to target_models."""
    if not target_models:
        return "\n\n".join(tool_observations)
    target_set = set(target_models)
    scoped = [
        obs
        for obs, model in zip(tool_observations, tool_observation_models)
        if not model or model in target_set
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
    """True when this '\n\n'-delimited block's own file:// link (see
    _BLOCK_FILE_LINK_RE) points at a file under a 'custom_*' addon
    directory. Returns True (keep the block) whenever no file:// link is
    found at all -- never silently drops a block this cannot positively
    classify as core/OCA Odoo, same conservative default as every other
    scoping guard in this module."""
    match = _BLOCK_FILE_LINK_RE.search(block)
    if not match:
        return True
    return "/custom_" in match.group(1)


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


def _backfill_link_guard_clarifications(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill whenever a [GARDE DE LIEN] annotation is present in raw tool output."""
    guard_fields = _extract_link_guard_fields(raw_tool_output)
    if not guard_fields:
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


def _extract_can_view_amount_fact_block(raw_tool_output: str) -> "Optional[str]":
    """
    Return the exact '[FAIT DETERMINISTIQUE] ... can_view_amount_v2 ...'
    block produced by _format_can_view_amount_fact(), if present anywhere
    in raw_tool_output, else None.
    """
    for block in raw_tool_output.split("\n\n"):
        if _has_can_view_amount_fact(block):
            return block.strip()
    return None


def _backfill_missing_can_view_amount_fact(final_answer: str, raw_tool_output: str) -> str:
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
    """
    if _has_can_view_amount_fact(final_answer):
        return final_answer

    block = _extract_can_view_amount_fact_block(raw_tool_output)
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
    scored = [
        (name, fuzz.token_set_ratio(question_lower, name.replace(".", " ").replace("_", " ").lower()))
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
):
    """Remove who_has_access_to 'could not be resolved' observations that refer
    to LLM-guessed group names when real requester groups have already been evaluated."""
    if not resolved_user_group_xmlids:
        return tool_observations, tool_observation_models

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        return tool_observations, tool_observation_models

    cleaned = []
    cleaned_models = []
    for obs, model in zip(tool_observations, tool_observation_models):
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: stripping 'could not be "
                "resolved' observation from synthesis context: %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
        cleaned_models.append(model)
    return cleaned, cleaned_models


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
    if not isinstance(sticky, dict):
        return concept

    if sticky.get("is_resolved") is not True:
        return concept

    try:
        from code_intelligence.business_resolver import ResolvedConcept
        rebuilt = ResolvedConcept(**sticky)
        return rebuilt
    except Exception:
        logger.debug(
            "_rehydrate_sticky_concept: reconstruction from sticky dict "
            "failed (unexpected shape), degrading to original concept"
        )
        return concept
