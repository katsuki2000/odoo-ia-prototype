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

# C.1.3: System prompt with explicit scope-first navigation strategy.
CI_SYSTEM_PROMPT = (
    "You are MIRO Code Intelligence Assistant specializing in Odoo source code and security analysis.\n"
    "NAVIGATION STRATEGY:\n"
    "1. When target models or modules are provided by [BUSINESS TERM RESOLVER S2.0], invoke the appropriate tools immediately:\n"
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
    "5. RETRY-BEFORE-HEDGE RULE (post-Bloc-8 fix): if a tool call returns 'not found in the "
    "indexed knowledge graph' or any similar failure, that failure means the MODEL NAME OR "
    "IDENTIFIER YOU JUST TRIED WAS WRONG -- it does not mean the information doesn't exist. "
    "Before proposing a different guessed identifier, or giving up and answering with hedging "
    "language ('il n'est pas possible de determiner avec certitude', 'il est possible que'), "
    "you MUST retry the SAME tool using the EXACT technical identifier already given to you "
    "under [BUSINESS TERM RESOLVER S2.0] above ('Target Models: ...') or already confirmed by "
    "an earlier successful tool observation in this same conversation. Never invent a new "
    "model/module name by paraphrasing the user's natural-language wording (e.g. 'demande_conge', "
    "'achat.demande', 'purchase.order') -- only the resolver-confirmed identifier or one copied "
    "verbatim from a prior successful observation is valid. Do not answer with uncertainty "
    "language until you have used at least one tool call against the resolver-confirmed model.\n"
    "6. 'COMMENT FAIRE X ?' RULE (Bloc 7 extension, 2026-08-07): for any question asking HOW to "
    "perform an action (click a button, submit a request, validate/approve something), invoke "
    "`button_execution_path`. Its result states explicitly whether the action is available to "
    "THIS demandeur. If it says NON DISPONIBLE / available_to_requester is false, your answer "
    "MUST say plainly that the demandeur does not have this option in the interface and, if the "
    "observation names the required group(s), who they should contact instead -- do NOT walk them "
    "through the button/method mechanism as if they could trigger it themselves."
)

# C.1.4: Maximum hops allowed per question.
CI_MAX_HOPS = 4

# J8 (Bloc 2): deterministic security-lock trigger.
# J7 found that the LLM does not reliably invoke analyze_security_locks
# on its own, even with the explicit "ALWAYS invoke" directive already in
# CI_SYSTEM_PROMPT (Q3.1: analyze_security_locks is correct and
# HIGH-confidence in isolation, but the LLM simply never calls it for
# approval-limit questions with a monetary amount). Rather than trying to
# word the prompt more forcefully -- which already failed once -- the
# amount is detected deterministically in code and the tool call is forced,
# removing the LLM from that decision entirely.
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
# Regression found on this same J8 patch (Q6.2, run of 2026-08-06): matching
# on amount alone forces analyze_security_locks even for pure ir.rule
# visibility questions ("peut voir un avoir de 80k?"), and the synthesis LLM
# then wrongly cross-attributed a Python-lock approval threshold (5000e) to
# an unrelated ir.rule rule name. Requiring an approval-intent keyword in
# addition to the amount keeps the forced dispatch scoped to what Q3.1
# actually needed (approval-limit / bypass questions), and leaves pure
# visibility questions to evaluate_record_rules alone.
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|permission\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)
# J8/J9: dedicated trigger for analyze_server_actions -- deliberately
# NOT reusing _APPROVAL_PATTERN alone (tested against the adversarial set:
# would fire on 6/9 questions, repolluting Python-lock questions like
# Q1.1/Q3.1/Q9.1 with irrelevant server-action noise -- same class of risk
# as the Q6.2 regression on _AMOUNT_PATTERN). Scoped to vocabulary that
# actually signals automation/bypass logic, not just "approval" in general.
# "tous les" / "toutes les" deliberately excluded: too generic in French
# (fires on unrelated questions like "tous les employés peuvent-ils...");
# "mêmes règles" alone already covers Q5.1's actual wording.
#
# Bloc 9 gap, found 2026-08-10 (bloc9-03c-urgente-trap, generalization
# check 3/8 on custom_hr_leave_workflow): bare `automatiq\w*` also matches
# the everyday adverb "automatiquement" in a question like "sa demande
# est-elle automatiquement validée ?" -- ordinary language asking whether
# something happens without further action, nothing to do with
# ir.actions.server/base.automation/sudo() bypass logic. On a model that
# DOES have real ServerAction nodes (hr.leave does, via hr_holidays), the
# structural guard below does not filter this out, so the false-positive
# forces analyze_server_actions to run and consumes a hop of the tight
# CI_MAX_HOPS=4 budget for a question that had nothing to do with server
# actions -- confirmed live: CI_MAX_HOPS was reached before the ReAct loop
# started, and the synthesis LLM dropped the has_group()-derived required
# group (hr_holidays.group_hr_holidays_manager) from its answer, the exact
# same failure shape as module 1/8's Gap 2 (dispatch noise crowding out a
# needed fact), just triggered by a false keyword match instead of an
# uncapped candidate list. Fix: require the automation vocabulary to
# actually be about an "action" (the noun this tool analyzes) or use the
# more specific technical term "automatisation" -- a standalone adjective/
# adverb "automatique"/"automatiquement" with no accompanying "action"
# noun no longer matches on its own.
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


# Bloc9 08c follow-up, requested 2026-08-13: evaluate_domain_force/
# can_view_amount_v2 (deterministic_tools.py) were wired into the
# evaluate_record_rules short-circuit below on 2026-08-1x, but
# deliberately WITHOUT company context -- see that call site's own comment
# ("company/user context is not extracted from the question this session").
# This closes that specific gap: a qualitative same/different extraction,
# not an identity lookup. There is no res.company name/id resolver
# anywhere in this codebase (unlike _resolve_user_group_xmlids for
# groups), and the live test Odoo instance is documented mono-company
# (todo/etat_reel.md, Bloc 1: "la limite mono-société de l'environnement
# de test") -- so a real company NAME or ID can never be resolved against
# a live second company from natural-language text on this setup. What a
# question CAN state, and the only thing worth trusting, is the RELATION
# between the requester's company and the record's company ("la même
# société" / "une autre société"), which is all evaluate_domain_force's
# equality-based domain_force leaves (company_id = user.company_id.id)
# actually need -- the specific numeric ids compared are arbitrary
# sentinels, only their equality/inequality carries meaning. No mention
# at all -> {} (unchanged behaviour, amount-only context, same honest
# None/"cannot conclude" outcome as before this fix for any domain_force
# that also checks company_id).
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
    Extract a qualitative same/different-company relation from the
    question, in the {"company_id": ..., "user": {"company_id": {"id":
    ...}}} shape evaluate_domain_force()/can_view_amount_v2() expect for
    a company_id-referencing domain_force leaf (e.g. ['|',
    ('company_id', '=', False), ('company_id', '=',
    user.company_id.id)], the real Module 08 rule --
    code_intelligence/tests/test_s2_9_domain_force_evaluator.py).

    Checks the DIFFERENT pattern first: "pas la même société" contains
    "même société" as a substring, so SAME must never win on a negated
    phrasing. Returns {} (no company keys at all, not a guessed value)
    when the question says nothing about company at all -- absence of
    information must resolve to unresolved/None downstream, never to a
    guessed same or different, per rules.md Regle 5.

    Also populates "company_ids" (todo/contexte.txt section 101/102):
    some domain_force leaves reference the bare, unprefixed dynamic ref
    company_ids (e.g. miro_ai's rule_miro_ai_settings_company/
    rule_miro_ai_log_admin: ('company_id', 'in', company_ids)) -- in
    real Odoo's ir.rule evaluation context this is the CURRENT USER's
    own list of accessible company ids (self.env.companies.ids), the
    plural counterpart of user.company_id.id, NEVER the record's own
    company_id (the left-hand side of the tuple, already covered by the
    top-level "company_id" key above -- a different thing entirely).
    Mirrors user.company_id.id's resolved value, not company_id's,
    under an explicit mono-company assumption: this codebase has no
    signal in the question text to distinguish "the user's one company"
    from "the user's several accessible companies", so company_ids is
    always a single-element list here. Revisit if/when multi-company
    demandeurs become a real scenario this project needs to model.
    """
    if _COMPANY_DIFFERENT_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}
    if _COMPANY_SAME_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 1}}, "company_ids": [1]}
    return {}


# Bug B2 (module 02, todo/contexte.txt section 96/98): investigation
# confirmed the matched business alias is NOT lost anywhere upstream in
# routing -- it is already sitting in concept.user_term (ResolvedConcept,
# resolved earlier in code_intelligence_agent() and in scope at both
# _dispatch_context/context construction call sites) by the time the
# domain_force evaluator needs it. The only missing piece was that nothing
# ever read it for this purpose. This closes that gap for the ONE field
# module 02's real domain_force actually references (move_type) -- mirrors
# _extract_company_context immediately above exactly: same {} convention
# for "no signal", same Regle 5 discipline (never guess on ambiguity).
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


# Bloc 9 gap, found 2026-08-13 (native-Odoo-out-of-scope investigation,
# "qui peut confirmer un devis (sale.order)" question): who_has_access_to (the
# ACL/ir.rule access-matrix tool) had NO forced pre-dispatch at all, unlike
# analyze_security_locks/analyze_server_actions/
# analyze_method_override_chain below -- it only ran if the LLM's own
# free tool choice picked it, which failed here: on a "who can do X"
# question against a model with no Python lock and no server action, the
# ReAct loop made one (correctly empty) analyze_security_locks call and
# answered directly, never checking the ACL/ir.rule layer that actually
# governs access for the overwhelming majority of Odoo models -- which
# have no Python lock or server action at all; ACL is the DEFAULT
# access-control mechanism, locks/actions are the exception.
#
# Unlike those three tools, gating this on "does the model structurally
# have something interesting" doesn't make sense here: virtually every
# real Odoo model has ACL entries, so a structural guard would fire on
# nearly every question -- not a meaningful filter, and it would burn the
# tight CI_MAX_HOPS=4 budget on unrelated questions. Gate on the QUESTION
# SHAPE instead ("qui peut/a le permission/est autorise a ..." -- a small,
# closed set of French "who can" phrasings) rather than an open-ended list
# of business verbs (confirmer, valider, demarrer...) that would need a
# new entry per module forever -- the exact whack-a-mole this project
# already moved away from for analyze_security_locks's own dispatch
# (module 5/8, 2026-08-10).
_ACCESS_QUESTION_PATTERN = re.compile(
    # Original "qui peut/a le permission/est autorisé" patterns
    r"\bqui\s+(?:a\s+le\s+permission|peut|peux|est\s+autoris\w*)\b|"
    # Bloc9 08c gap (2026-08-14): "peut-il/elle voir/accéder/consulter"
    # was not matched -- the question 08c ("Un utilisateur standard ...
    # peut-il voir un document ...") was never recognized as access-
    # related, so neither who_has_access_to nor evaluate_record_rules
    # were force-dispatched. The resolver then guessed model='base',
    # can_view_amount_v2 got zero rules, and returned True for the wrong
    # model. This branch covers the inverted-subject French question form
    # ("peut-il/elle/on voir") in addition to the "qui peut" form above.
    r"\b(?:peut|peux|pourra|pourrait)[\s-]*(?:il|elle|on|t[\s-]*il|t[\s-]*elle)\s+(?:voir|acc[eé]der|consulter|lire|visualiser)\b|"
    # "a-t-il/elle le permission/accès/la permission"
    r"\ba[\s-]*t[\s-]*(?:il|elle)\s+(?:le\s+permission|acc[eè]s|la\s+permission)\b|"
    # English patterns
    r"\bwho\s+(?:can|has\s+the\s+right|is\s+authoriz\w*)\b|"
    r"\b(?:can|may)\s+(?:a\s+user|the\s+user|an?\s+employee)\s+(?:see|view|access|read)\b",
    re.IGNORECASE,
)


def _question_is_access_related(question: str) -> bool:
    return bool(_ACCESS_QUESTION_PATTERN.search(question))


# Bloc 9 cross-module gap (2026-08-10, modules 1/8, 3/8, 4/8 generalization
# checks): the "Groupe(s) technique(s) requis detecte(s) (has_group)" line
# was present in every single raw analyze_security_locks observation
# checked, but was just as reliably DROPPED from the final synthesized
# answer specifically on business/trap-phrased approval questions (present
# on purely technical-enumeration phrasings, e.g. "quelles sont toutes les
# conditions verifiees par ..."). Unlike SUPER() NON GARDE / CHAINE
# RELATIONNELLE NON VERIFIEE, which each already have a dedicated prose
# instruction in synthesis_prompt below, this line had none.
#
# Deliberately NOT fixed by adding yet another synthesis_prompt clause.
# synthesis_prompt already carries a dozen-plus specific instructions for
# an 8B model with a documented decoding-collapse failure mode under
# pressure (_detect_degenerate_repetition) and a hard Groq 413 payload
# ceiling already hit repeatedly in these same runs -- growing it further
# risks diluting attention on the instructions already there, for an
# unproven gain on this one. This project already made exactly this call
# once before and reversed it (see the J7/J8 comment above
# _AMOUNT_PATTERN: "Rather than trying to word the prompt more forcefully
# -- which already failed once -- ... removing the LLM from that decision
# entirely"). Applying the same principle here: extract the required
# group(s) directly from the raw tool text, independent of anything the
# LLM did or didn't say, and append them only if genuinely missing --
# never overriding or duplicating a correct answer.
_REQUIRED_GROUP_LINE_RE = re.compile(
    r"Groupe\(s\)\s+technique\(s\)\s+requis\s+detecte\(s\)\s+\(has_group\):\s*([^\n]+)"
)


# Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation): matches
# any Odoo group xmlid shape ('<module>.group_<name>') so the grounding
# validator below can find every group token the LLM mentioned in
# final_answer, not just the ones matching _REQUIRED_GROUP_LINE_RE (that
# regex only captures the tool's OWN summary line -- the LLM is free to
# type a group name anywhere else in its prose).
_GROUP_XMLID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b")


def _extract_required_groups(raw_tool_output: str) -> List[str]:
    """Pull every has_group()-derived required group xml_id out of the raw
    tool text, in first-seen order, deduplicated. Returns [] if no such
    line is present -- never guesses a group from anywhere else."""
    groups: List[str] = []
    for match in _REQUIRED_GROUP_LINE_RE.finditer(raw_tool_output):
        for name in match.group(1).split(","):
            name = name.strip()
            if name and name not in groups:
                groups.append(name)
    return groups


def _flag_ungrounded_group_xmlids(final_answer: str, raw_tool_output: str) -> str:
    """Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation):
    negative/grounding validator -- the mirror image of every backfill
    above (which only ever ADD a fact already known to be true). This one
    only ever FLAGS, never silently strips: same transparency principle
    already used by verify_citations/annotate_unverifiable_citations right
    below for the structurally identical problem (an LLM claim with no
    verified backing in this turn's evidence).

    Grounded set = every group xmlid extracted via _extract_required_groups
    (the exact same has_group() line format _backfill_missing_required_
    groups already trusts as authoritative) from this turn's scoped tool
    output. Any <module>.group_<x>-shaped token in final_answer that is
    NOT in that set gets flagged -- never removed, since an ungrounded
    mention may still be legitimate context (e.g. a different threshold's
    group explained for contrast) that a mechanical substring check cannot
    distinguish from a genuine hallucination; only a reviewer should act on
    the flag, not this function.

    Deliberately a no-op when grounded is empty -- a turn where no
    security-lock tool fired this hop has no reference set to check
    against, and flagging every group mention as fake in that case would
    be strictly worse than saying nothing.
    """
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
    """Bloc 9 gap fix (2026-08-14, module 1/8 follow-up, LLM free-prose
    'account.group_account_invoice' noise -- see todo/etat_reel.md and
    contexte.txt section 42/addendum): a THIRD category, orthogonal to
    _flag_ungrounded_group_xmlids' grounded/ungrounded split above -- a
    group xmlid can be genuinely grounded (a real has_group() call exists
    somewhere in this turn's scoped_tool_output) while still being
    irrelevant, because analyze_security_locks (ci_agent_tools.py)
    aggregates EVERY Python file touching the model with zero custom/core
    distinction, so a widely-shared core model like account.move always
    drags in Odoo's own core has_group() checks (e.g.
    account.group_account_invoice in _post()) alongside the real custom
    override, in the SAME block the LLM's free synthesis reads verbatim.
    _restrict_blocks_to_custom_modules already solves this for the
    deterministic backfill path (_backfill_missing_required_groups) below
    -- this reuses the exact same file-link classification to compute the
    narrower 'grounded AND custom' set, so the difference (grounded but
    ONLY present in a non-custom block) identifies a group the LLM's own
    free prose cited from core Odoo content that has nothing to do with
    the custom mechanism this question actually resolved to.

    Deliberately does NOT touch raw_tool_output itself (only the already-
    computed scoped_tool_output the caller already scoped to the resolved
    model(s)) -- consistent with the module-level comment above
    _restrict_blocks_to_custom_modules: raw_tool_output must stay fully
    unscoped for verify_citations/_force_dynamic_uncertainty_answer, which
    legitimately need visibility into every real has_group()/getattr()
    call, core Odoo included.
    """
    grounded = set(_extract_required_groups(scoped_tool_output))
    if not grounded:
        return []
    custom_grounded = set(
        _extract_required_groups(_restrict_blocks_to_custom_modules(scoped_tool_output))
    )
    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    return sorted((mentioned & grounded) - custom_grounded)


def _strip_core_only_group_mentions(final_answer: str, scoped_tool_output: str) -> str:
    """Removes, in place, the line or clause naming each group xmlid
    identified by _grounded_core_only_groups above. Unlike
    _flag_ungrounded_group_xmlids (a genuine hallucination is flagged, not
    stripped, since a reviewer should judge whether it is legitimate
    context) -- a grounded-but-core-only group is definitionally never
    relevant to a custom-mechanism question, so there is nothing left for
    a reviewer to adjudicate: removing it is safe.

    A bandeau-only warning was tried and found insufficient for this same
    shape of problem once already (module 5/8 Bug 2, link-guard
    contradiction -- see _neutralize_contradicting_link_guard_sentence
    below): the flagged sentence stays visible and readable underneath the
    warning, so a downstream check for the specific wrong content still
    fails. This follows the same in-place-removal precedent, but simpler:
    there is no template sentence to reconstruct here (unlike the
    link-guard case, where the correct conclusion had to be restated), so
    the matched clause/line is dropped rather than replaced -- bounded to
    '.'/'\n' on either side (same bounding technique as
    _LINK_GUARD_CONTRADICTING_SENTENCE_RE below) so only the specific
    clause naming the group is removed, never a neighboring sentence or
    bullet.

    No-op when _grounded_core_only_groups returns nothing -- most turns
    never aggregate a core-Odoo block at all (single-file custom modules
    are the majority case), so this rarely fires.
    """
    core_only = _grounded_core_only_groups(final_answer, scoped_tool_output)
    if not core_only:
        return final_answer

    result = final_answer
    for xmlid in core_only:
        pattern = re.compile(r"[^.\n]*" + re.escape(xmlid) + r"[^.\n]*\.?\n?")
        result = pattern.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)

    logger.warning(
        "Node [code_intelligence_agent]: stripped grounded-but-core-Odoo-only "
        "group xmlid(s) from synthesized answer (relevant only to a shared "
        "core file, not the custom mechanism this question resolved to): %s",
        ", ".join(core_only),
    )
    return result


def _scoped_raw_tool_output(
    tool_observations: List[str],
    tool_observation_models: List[str],
    target_models: List[str],
) -> str:
    """Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
    the deterministic backfills below (_backfill_missing_required_groups,
    _backfill_link_guard_clarifications) used to be handed raw_tool_output
    built from the ENTIRE concatenated tool_observations list -- every hop
    of the ReAct loop for the whole turn, regardless of which model that
    hop actually targeted. When business_resolver/the ReAct loop wandered
    onto an unrelated model in the same turn (confirmed case: a detour
    through custom.purchase.request while answering a custom.asset.loan
    question), that unrelated model's OWN [GARDE DE LIEN]/[Groupe(s)
    technique(s) requis] annotations leaked into a backfill mechanism that
    is supposed to be a 100%-reliable, model-scoped fact -- the opposite of
    what "deterministic" is meant to guarantee.

    Restricts the text handed to a backfill to observations recorded
    (tool_observation_models, index-aligned with tool_observations) against
    one of target_models, plus any observation whose model could not be
    determined (empty string -- these are meta/global tool calls, never the
    source of a per-model contamination risk, so excluding them would only
    lose legitimate content for no safety benefit). Falls back to the full
    unscoped concatenation when target_models is empty (unresolved concept
    -- no scope to restrict to, same behavior as before this fix).

    Deliberately NOT used for raw_tool_output itself (citation verification
    and dynamic-uncertainty detection still need visibility into every hop
    of the turn) -- only for the two backfill call sites, which is where
    cross-model contamination turns into a wrong fact stated with full
    (undeserved) confidence.
    """
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


# Bloc 9 gap, documented open in todo/etat_reel.md as "account.group_
# account_invoice noise" (module 1/8, bloc9-01a-business, found 2026-08-13,
# left deliberately unfixed at the time -- "necessiterait un scoping
# fichier/module plus fin qu'un scoping par modele ... delibere ment non
# traite (risque de sur-edition sans tests dedies)"). Root cause traced by
# direct inspection of the real source (2026-08-14 follow-up): analyser_
# verrous_securite (ci_agent_tools.py) aggregates analyze_python_security_
# locks' summary_text for EVERY Python file touching the model, joined
# with the same '\n\n' block separator _scoped_raw_tool_output/_extract_
# security_lock_condition_amounts already rely on -- on a widely-shared
# core model like account.move, that includes Odoo's own core account/
# models/account_move.py right alongside the custom override file. Core
# Odoo's _post() has a real, correctly-attributed has_group('account.
# group_account_invoice') check (governs posting ANY invoice, confirmed
# by direct read of /home/user/odoo-17.0/addons/account/models/
# account_move.py, line ~3941) that has nothing to do with a custom
# approval-cascade question ("qui a le permission d'approuver un avoir de
# 25000e") -- genuinely grounded, not a hallucination (_flag_ungrounded_
# group_xmlids correctly leaves it alone), just out of scope: this
# product's entire premise (Bloc 9, "Generalisation au code custom") is
# bypass/governance mechanisms in CUSTOM overlay code, never core Odoo's
# own standard access control living in a different file that happens to
# share the model.
#
# Each block's own header line already carries a file:// link (see
# analyze_python_security_locks' use of format_file_link) -- restricting
# extraction to blocks whose link points under a 'custom_*' addon
# directory removes this specific noise without touching _extract_
# required_groups itself (still used unfiltered by _flag_ungrounded_
# group_xmlids, which must keep seeing core Odoo's real has_group() calls
# too -- a mention that IS grounded there should never be flagged as a
# hallucination just because it's irrelevant to this particular question).
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
    """Deterministic backfill (see module-level comment above
    _REQUIRED_GROUP_LINE_RE for why this is a code-level fix, not a
    prompt-level one): on an approval-related question, if the raw tool
    output named required group(s) via has_group() that never made it
    into the synthesized answer, append them as an explicit, clearly
    labeled fact. No-op whenever every required group is already present
    in the answer -- this never duplicates or contradicts a correct
    synthesis, it only fills a gap.

    Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business): when the
    question specifies a monetary amount (e.g. 60 000€), only backfills
    groups whose threshold is actually reached/triggered for that amount,
    rather than blindly backfilling higher-threshold groups (e.g. base.group_system
    requiring > 100k€).

    Bloc 9 gap fix (2026-08-14, module 1/8 follow-up, 'account.group_
    account_invoice noise'): raw_tool_output is restricted to custom-
    module blocks (see _restrict_blocks_to_custom_modules) before group
    extraction, so a core-Odoo has_group() check aggregated onto the same
    shared model no longer gets backfilled as if it were part of this
    custom approval mechanism.
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
        "from synthesized answer (present in raw tool output, dropped by synthesis): %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Groupe(s) technique(s) requis (has_group) "
        f"détecté(s) dans le code pour cette action : {group_list}. Fait extrait "
        f"directement de l'analyse statique du code."
    )


# Bloc 9 gap, found 2026-08-11 (module 1/8 rerun, bloc9-01a-business /
# bloc9-01b-technical): the override-cascade module-name and threshold-
# amount extraction/backfill cluster that used to live here (originally:
# _OVERRIDE_MODULE_RE, _extract_override_modules, _word_boundary_present,
# _backfill_missing_override_modules, _extract_override_chain_amounts,
# _backfill_missing_override_chain_amount) was relocated to
# rag/ci_override_cascade.py on 2026-08-20 -- see that module's own
# docstring for the full history/rationale. _OVERRIDE_CHAIN_AMOUNT_RE
# itself stays HERE, not there: _extract_security_lock_condition_amounts
# below (a different, unrelated cluster -- Python security locks) reads
# it directly, and the two tools' raw output genuinely share this exact
# 'rec.<attr> > <digits>' condition shape. ci_override_cascade.py imports
# it from here rather than redefining it.
_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def _amount_present_in_text(amount: str, text: str) -> bool:
    """True if `amount` (a bare digit string, e.g. '5000') appears in
    `text` as a genuine standalone number -- either unspaced ('5000') or
    with a thousands-separator space ('5 000') -- never as a substring of
    a larger number (e.g. '25 000' must NOT count as containing '5000').

    Bloc 9 gap, found 2026-08-13 (module 1/8, bloc9-01a-business rerun,
    AFTER the block-scoping fix for _extract_security_lock_condition_
    amounts is confirmed working on bloc9-01b/01c): 01a's own question
    text ('un avoir de 25 000€') gets echoed verbatim in the synthesized
    answer's opening sentence -- and the old plain `in` substring check
    (`spaced in final_answer`) treated '5 000' as already present the
    moment it appeared as a literal substring of '25 000€', so
    _backfill_missing_security_lock_amount silently no-op'd, believing a
    fact was already covered when it was never actually stated (the
    answer never mentions the real 5000e threshold on its own terms).
    Reproduced directly against the live 01a answer text before this fix
    (spaced='5 000' found inside '25 000€' -- true positive on the bug,
    false negative on the actual check) and confirmed absent after it.

    Both call sites (_backfill_missing_override_chain_amount and
    _backfill_missing_security_lock_amount) previously defined their own
    identical local `_amount_present` closure with this exact bug --
    consolidated here as a single shared, digit-boundary-aware
    implementation instead of fixing the bug twice.
    """
    spaced = f"{amount[:-3]} {amount[-3:]}" if len(amount) > 3 else amount
    for candidate in {amount, spaced}:
        pattern = r"(?<!\d)" + re.escape(candidate) + r"(?!\d)"
        if re.search(pattern, text):
            return True
    return False


# Bloc 9 gap, found 2026-08-11 (module 5/8, bloc9-05c-no-link-trap): the
# override-cascade threshold-amount backfill that used to live here
# (_backfill_missing_override_chain_amount) was relocated to
# rag/ci_override_cascade.py on 2026-08-20 -- see that module's own
# docstring for the full history/rationale.
#


# Literal header line analyze_python_security_locks (semgrep_locks_analyzer.py)
# always emits once result.exception_messages is non-empty ("  - Messages de
# verrous (UserError/ValidationError):") -- used below as the block-scoped
# guard that this raw_tool_output block actually came from that tool, not a
# different one (e.g. analyze_method_override_chain) sharing the same
# 'rec.<attr> > <digits>' condition shape. Restored 2026-08-20: this constant
# was referenced by _extract_security_lock_condition_amounts below and by this
# module's own comments but had no assignment anywhere in the file -- lost,
# not intentionally removed, most likely during the 2026-08-20
# ci_override_cascade.py split (see that module's docstring) since the
# function that used to sit directly above this one before the split
# (_backfill_missing_override_chain_amount) was relocated there. Never
# triggered an ImportError (nothing imports this name from outside this
# module), so it only surfaced as a silent NameError at call time.
_SECURITY_LOCK_MESSAGES_MARKER = "Security lock messages (UserError/ValidationError)"


def _extract_security_lock_condition_amounts(raw_tool_output: str) -> List[str]:
    """Pull every monetary/numeric threshold embedded in a Python comparison
    inside an analyze_security_locks exception condition (e.g.
    'rec.montant_estime > 10000'), in first-seen order, deduplicated.
    Returns [] whenever _SECURITY_LOCK_MESSAGES_MARKER -- the literal
    header line analyze_python_security_locks always emits once it has at
    least one exception message -- is absent from the raw text. See the
    module-level comment above _SECURITY_LOCK_MESSAGES_MARKER for why this
    does not reuse _extract_override_chain_amounts' own guard.

    Bloc 9 gap, found 2026-08-13 (module 1/8 rerun, bloc9-01a-business /
    bloc9-01c-vip-trap, AFTER the module 4/8 security-lock backfill above
    is confirmed working on custom_purchase_request): on account.move, the
    SAME scoped_tool_output can legitimately contain BOTH this tool's own
    block (custom_credit_note_approval's real security lock, 'rec.
    amount_total > 5000') AND an unrelated analyser_chaine_surcharge_
    methode block (custom_credit_note_approval_regional's override-cascade
    finding, 'rec.amount_total > 20000') in the same turn, because both
    tools target account.move and _scoped_raw_tool_output only scopes by
    MODEL, not by tool/block -- the two blocks share a model, so model-
    scoping cannot separate them (unlike the module 5/8 cross-MODEL
    contamination that fix already covers). The old version of this
    function gated on the marker being present ANYWHERE in the full
    (already-joined) text, then scanned amounts from the ENTIRE text --
    so it silently picked up the unrelated 20000 from the override-cascade
    block and labeled it a "verrou de securite" amount, live-confirmed on
    both bloc9-01a-business (20000 asserted as the security-lock threshold
    instead of the real 5000, which never appeared anywhere in the answer)
    and bloc9-01c-vip-trap (the backfilled 20000 fact directly contradicts
    the answer's OWN correct prose two lines above it, which cites 5000).
    Neither the check script's expected_markers (only checks '20000'/
    'account.group_account_manager' appear somewhere, never which fact
    they're attributed to) nor the existing test
    (test_no_op_on_unrelated_rec_comparison_outside_security_lock_text,
    which only exercises the override-cascade text ALONE, marker absent)
    covered this combined-block scenario.

    Fixed by scoping the marker check AND the amount scan to the same
    '\n\n'-delimited block, instead of the whole raw_tool_output string --
    tool_observations/scoped_tool_output are always joined with '\n\n'
    (see _scoped_raw_tool_output), and no single tool's own rendering has
    been observed to contain an internal blank line, so this is a safe,
    already-implicit block boundary rather than a new assumption.
    """
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
    """Deterministic backfill, symmetric to _backfill_missing_required_groups
    and _backfill_missing_override_chain_amount, for the fact shape found
    on module 4/8 (custom_purchase_request): if analyze_security_locks's
    raw exception-condition text names a numeric threshold that never made
    it into the synthesized answer, append it as an explicit, clearly
    labeled fact. No-op whenever the threshold is already present (checked
    with and without a thousands-separator space, same tolerance as
    _backfill_missing_override_chain_amount) -- never duplicates or
    contradicts a correct synthesis, only fills a gap.

    Bloc 9 gap fix (2026-08-14, module 8/8 follow-up): when question specifies
    a monetary amount or is a read visibility rule question (where can_view_amount
    fact is present), thresholds strictly greater than the question's amount are
    not triggered and are not backfilled as noise.
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
        "threshold(s) missing from synthesized answer (present in raw tool output, "
        "dropped by synthesis): %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition "
        f"supplémentaire déclenchée au-delà de {amount_list}, distincte du groupe "
        f"requis ci-dessus. Fait extrait directement de l'analyse statique du code."
    )


# Bloc 9 gap, found 2026-08-10 (bloc9-05c-no-link-trap, generalization check
# 5/8 on custom_asset_loan): the [GARDE DE LIEN] annotation appended by
# semgrep_locks_analyzer.py (see SecurityLockASTVisitor._detect_link_guard_
# field docstring) already states the correct short-circuit conclusion in
# the raw tool text -- but a live run showed the synthesis LLM misreading
# it anyway, concluding the rule "applies when NOT linked", the exact
# inverse of the ground truth, DESPITE the condition being quoted correctly
# elsewhere in the same answer. Unlike the required-groups gap (content
# silently dropped), this is content present AND read, but reasoned about
# incorrectly -- so the fix is not "add it if missing" but "always restate
# the computed conclusion explicitly", the same principle already applied
# to _format_can_view_amount_fact (a boolean verdict is safer handed to the
# LLM pre-computed than left for it to (mis)derive from raw material).
_LINK_GUARD_RE = re.compile(
    r"\[GARDE DE LIEN: si '([^']+)' est vide/absent .*?NE S'APPLIQUE PAS dans ce cas",
    re.DOTALL,
)

# Bloc 9 gap, module 5/8 Bug 2 (2026-08-11, bloc9-05c-no-link-trap). First
# attempt (same day) only PREPENDED a correction banner ahead of the
# unchanged wrong prose. Confirmed still failing on a real rerun the same
# day: the banner fires and logs correctly, but the literal wrong sentence
# ("s'applique quand meme...") remains fully readable right below it --
# scripts/check_bloc9_05_asset_loan_e2e.py's forbidden_markers check still
# flags it, and more importantly a non-technical Discuss end user skimming
# past a disclaimer would still read the wrong sentence as the answer. This
# product's stated audience is non-dev (Discuss chat widget, sources hidden
# behind a collapsed chevron) -- the visible answer must be correct on its
# own, not correct-only-if-the-reader-notices-the-caveat-first. Revised to
# surgically replace the exact matched sentence instead of merely flagging
# it -- narrower than a general rewrite (over-trimming risk already flagged
# for the hallucination case in method_override_resolver.py, contexte.txt
# section 24): only the specific confirmed-real contradiction pattern is
# touched, matched at the single-sentence boundary, nothing else in the
# answer is altered.
_LINK_GUARD_CONTRADICTION_PATTERN = re.compile(
    r"s.?applique\s+(quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)"
)

# Same confirmed-real vocabulary as _LINK_GUARD_CONTRADICTION_PATTERN above,
# widened to capture the WHOLE sentence containing it (bounded by '.'/'\n' on
# either side) so the replacement can swap out the entire wrong claim, not
# just the matched fragment -- leaving fragments of the wrong sentence behind
# (e.g. "..., quel que soit le montant du materiel, dans le cas ou...") would
# still read as a wrong claim once stitched to a different ending.
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
    """
    Bloc 9 gap, module 6/8 (bloc9-06c-technical-condition-capture,
    2026-08-11): the server-action trigger-condition line
    (analyze_server_actions's "\u26a1 Condition(s) de d\u00e9clenchement:
    rec.move_type == 'in_refund' and rec.partner_id.id in
    FOURNISSEURS_PRIVILEGIES") gets correctly PARAPHRASED by the synthesis
    LLM ("avoirs re\u00e7us de trois fournisseurs sp\u00e9cifiques") but the
    literal string constant inside the condition ('in_refund') never
    survives verbatim -- same class of gap as _extract_override_chain_amounts
    above, at the string-literal granularity instead of the numeric-
    threshold one.

    Deliberately extracts only the QUOTED STRING LITERALS inside the
    trigger-condition line, not the whole boolean expression -- backfilling
    the entire multi-clause condition every time the LLM's (correct,
    readable) paraphrase doesn't reproduce it byte-for-byte would be noisy
    and largely redundant; the specific literal token is the actual thing a
    consultant needs to grep the code for. Returns [] if the line isn't
    present at all (tool wasn't invoked, or found no trigger condition).
    """
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
    """Deterministic backfill, same append-only/never-override discipline
    as every other backfill in this module: if a server-action's trigger
    condition contains a quoted string literal (already present verbatim
    in the raw tool text) that never made it into the synthesized answer,
    append it as an explicit, clearly labeled fact. No-op whenever every
    literal is already present -- never duplicates or contradicts a
    correct synthesis."""
    literals = _extract_trigger_condition_literals(raw_tool_output)
    if not literals:
        return final_answer

    missing = [lit for lit in literals if lit not in final_answer]
    if not missing:
        return final_answer

    lit_list = ", ".join(f"`{lit}`" for lit in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling server-action trigger-condition "
        "literal(s) missing from synthesized answer (present in raw tool output, "
        "paraphrased away by synthesis): %s",
        lit_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) de la condition de "
        f"d\u00e9clenchement de l'action serveur, absente(s) de la reformulation "
        f"ci-dessus : {lit_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


# Bloc 9 gap, module 6/8 (bloc9-06c-technical-condition-capture, found
# 2026-08-13 -- rerun immediately AFTER the analyze_server_actions
# truncation-cap fix is confirmed active on disk): the cap fix restores
# sudo()/in_refund to the stored observation and to the final answer
# (06b/06c both pass on those markers now), but 06c still drops the
# hardcoded privileged-partner IDs (42, 108, 231) -- present verbatim in
# the raw tool text ("[SENSITIVE BYPASS] IDs en dur: [42, 108, 231]
# -> traitement privilegie non documente") but never reaching the LLM's
# paraphrase. Same class of gap as the trigger-condition literal above (a
# bracketed technical detail the small model summarizes away in favor of
# prose, e.g. "trois fournisseurs specifiques"), just on the sibling line
# one row below it in the same finding -- confirmed NOT a truncation
# symptom this time (the raw check's own direct call already shows "42"
# present under the now-3000 cap), so a dedicated backfill rather than
# another cap raise.
_HARDCODED_IDS_LINE_RE = re.compile(r"IDs en dur\s*:\s*\[([^\]]+)\]")


def _extract_hardcoded_id_literals(raw_tool_output: str) -> List[str]:
    """Pull every hardcoded-ID token out of a server-action bypass finding's
    \"IDs en dur: [...]\" line, in first-seen order, deduplicated. Returns []
    if no such line is present -- tool wasn't invoked, the finding was
    gated out for an unprivileged requester (authorization_gate.py), or no
    hardcoded-ID bypass exists on this model at all."""
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
    """Deterministic backfill, same append-only/never-override discipline as
    every other backfill in this module: if a server-action's hardcoded-ID
    bypass list (already present verbatim in the raw tool text) never made
    it into the synthesized answer, append it as an explicit, clearly
    labeled fact. No-op whenever every ID is already present -- never
    duplicates or contradicts a correct synthesis. Reuses
    _amount_present_in_text for a digit-boundary-safe presence check (an
    ID is just a bare digit string, e.g. '42' must not count as already
    present merely because '142' or '420' appears somewhere in the
    answer) -- same reasoning as its existing use for monetary amounts.
    """
    ids = _extract_hardcoded_id_literals(raw_tool_output)
    if not ids:
        return final_answer

    missing = [i for i in ids if not _amount_present_in_text(i, final_answer)]
    if not missing:
        return final_answer

    id_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling hardcoded privileged-ID "
        "literal(s) missing from synthesized answer (present in raw tool "
        "output, paraphrased away by synthesis): %s",
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
    """Deterministic backfill, always appended (not conditional on question
    wording, unlike _backfill_missing_required_groups) whenever a [GARDE DE
    LIEN] annotation is present in the raw tool output -- restates the
    already-computed short-circuit conclusion explicitly as a labeled fact,
    regardless of what the LLM said, so an incorrect natural-language
    reading of the raw condition text can never be the only thing the user
    sees. Idempotent: no-op if the marker sentence is already present
    (e.g. a future synthesis run that gets it right on its own).
    """
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


# Bloc9 08c follow-up (2026-08-14): synthesis-inversion detector for the
# can_view_amount_v2 deterministic fact, symmetric to module 5/8's Bug 2 fix
# (_correct_override_cascade_contradictions / _neutralize_contradicting_
# link_guard_sentence above) but for THIS fact instead of the link-guard
# short-circuit. The diagnostic logging already added at the injection call
# site ("Injected deterministic can_view_amount_v2 fact ...") only lets a
# human distinguish a resolution/wiring gap (model not found, zero rules
# applied -> would silently default this to True) from a synthesis-level
# inversion of an otherwise-correct verdict -- it does not fix the inversion
# case even once the log confirms that's what happened. This closes that
# second half: if the appended [FAIT DETERMINISTIQUE] disagrees with what
# the LLM's own free prose asserted earlier in the same answer, replace the
# wrong sentence in place -- an appended correct fact below a wrong sentence
# does not, on its own, correct that sentence for a top-to-bottom reader.
#
# CUTOFF (found in sandbox testing, 2026-08-14, before this was wired in
# here): once the can_view_amount_v2 fact itself is appended to final_answer
# (e.g. "...l'utilisateur PEUT voir cet enregistrement."), the same ALLOW/
# DENY assertion regex also matches that appended sentence -- an auto-
# collision where the fact would flag itself as contradicting itself.
# _split_before_first_fact_marker scans only the free-prose portion of
# final_answer BEFORE the first "[FAIT" marker to avoid this.
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
    """Text portion before the first '[FAIT' marker -- the free-prose
    synthesis, excluding every deterministic fact appended by the backfills
    in this module. See the CUTOFF note above _CAN_VIEW_ALLOW_ASSERTION_RE
    for the auto-collision this avoids."""
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
    """Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business):
    detect and correct synthesis-level inversions of Python security lock
    threshold logic (has_group() with numeric amount conditions).

    Small synthesis LLMs frequently conflate independent threshold gates
    (e.g. >50k requires account.group_account_manager, >100k requires base.group_system)
    by treating them as exclusive authority tiers / upper bounds -- claiming that a
    manager only has the right up to 50k and cannot validate at 60k, and/or claiming
    that the higher admin group is required/authorized at 60k.

    This detector reconciles the free prose against the ground-truth lock conditions
    extracted from scoped_tool_output for the specific monetary amount in question.
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


# Bloc9 08c gap, found 2026-08-14 (bloc9-08c-nested-domain-trap, live
# rerun after the company-context fix): every OTHER deterministic fact
# injected into tool_observations by this module (required groups,
# override-chain amount/modules, trigger-condition literals, hardcoded
# IDs, link-guard clarification) has a matching _backfill_missing_X that
# guarantees the fact survives into final_answer even when synthesis
# drops or reworks it. The can_view_amount_v2 fact never had one -- it
# only ever reached tool_observations (the synthesis LLM's INPUT), and
# synthesis_prompt explicitly tells the model never to quote the
# '[FAIT DETERMINISTIQUE]' label or the mechanism name verbatim "as if
# that were the explanation". A small instruction-following model
# reliably obeys that by paraphrasing the verdict into free prose
# instead of copying the exact template -- confirmed on the real
# bloc9-08c-nested-domain-trap transcript (todo/etat_reel.md): the
# answer says "can_view_amount() = True... l'utilisateur PEUT voir cet
# enregistrement", a loose paraphrase (comma + "ce qui signifie que"
# instead of the exact " : ") that does NOT match
# _CAN_VIEW_FACT_VERDICT_RE, so _has_can_view_amount_fact() returns
# False on that real answer and _correct_can_view_amount_contradictions()
# silently no-ops just above -- an inversion of the actual verdict
# (confirmed False by direct can_view_amount_v2() replay in sandbox
# against the real domain_force strings from this run's raw tool output
# and a correctly-extracted different-company context) reaches the user
# uncorrected, because the fact it needed to compare the prose against
# was never actually present in final_answer to compare against.
#
# Closes the gap the same way as every sibling backfill: append the
# exact fact block, recovered verbatim from raw_tool_output (never
# re-derived or reworded here), when no such fact is already present in
# final_answer -- so _correct_can_view_amount_contradictions (called
# right after this one) always has a real fact to check the prose
# against, whether the LLM echoed one or not.
def _extract_can_view_amount_fact_block(raw_tool_output: str) -> "Optional[str]":
    """
    Return the exact '[FAIT DETERMINISTIQUE] ... can_view_amount_v2 ...'
    block produced by _format_can_view_amount_fact(), if present anywhere
    in raw_tool_output, else None. Observations are '\n\n'-joined (see
    raw_tool_output/_scoped_raw_tool_output), so splitting on that same
    separator and testing each block with the existing
    _has_can_view_amount_fact() marker check is enough to recover the
    block verbatim, without re-deriving or reformatting its wording here.
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
        "deterministic fact missing from synthesized answer (present in "
        "raw tool output, dropped/paraphrased by synthesis) -- Bloc9 08c "
        "gap, 2026-08-14."
    )
    return final_answer + "\n\n" + block


def _format_can_view_amount_fact(
    amount: float, can_view: "Optional[bool]", unresolved: "Optional[List[str]]" = None
) -> str:
    """
    Bloc 9 gap (2026-08-10, bloc9-02b-no-groups): the previous phrasing
    addressed the synthesis LLM directly in second-person imperative
    INSIDE the data block itself ("ne doit JAMAIS etre recalcule ...
    reprendre ce verdict tel quel"), blurring the line between fact and
    instruction. Live run confirmed the small model (llama-3.1-8b-instant)
    treated that sentence as safe, quotable content and echoed it VERBATIM
    as the entire final answer -- with zero mention of WHY (no rule name,
    no reasoning), on the one question where this was the only observation
    present (no applicable group rule to also cite).

    Kept purely declarative here -- the "never contradict this verdict"
    instruction now lives in synthesis_prompt instead (code_intelligence_
    agent), alongside an explicit instruction to still explain the verdict
    using the OTHER observations in the same response. Extracted as a
    standalone function so this specific regression (no imperative
    second-person sentence inside the injected fact) has a fast,
    deterministic unit test independent of the full ReAct loop / LLM.

    Bloc9 08c fix (deterministic_tools.py can_view_amount_v2): can_view is
    now Optional[bool]. The call site switched from the old regex-based
    can_view_amount() -- which silently returns True whenever a
    domain_force condition it cannot parse (e.g. company_id) is present,
    confirmed root cause of 08c -- to can_view_amount_v2()'s tri-state
    verdict. can_view=None means at least one applicable rule's
    domain_force could not be conclusively evaluated against the available
    context: this is NOT the same as "no restriction found" and must never
    be phrased as an allow/deny answer. unresolved lists the field name(s)
    that blocked a conclusive verdict (e.g. ['company_id']), so the fact
    can name exactly what is missing instead of a generic disclaimer.
    """
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


# Bloc 9 gap, found 2026-08-11 (bloc9-07c-sudo-scope-trap, module 7/8 first
# live run): MAX_MODELS_PER_QUERY's own truncation (config.settings, applied
# in code_intelligence_agent right after resolve_business_term) was a plain
# `resolved_models[:MAX_MODELS_PER_QUERY]` slice -- whichever models
# business_resolver happened to list FIRST survive, with no regard for which
# one the question is actually about. Confirmed live: a question combining
# "sudo()" + "remboursement" resolved to multiple candidate models, the
# truncation dropped custom.reimbursement.request (the one the whole
# question is about) before the forced-dispatch loops below even ran, and
# the ReAct loop was left to answer from evaluate_record_rules alone
# -- producing a confidently wrong "sans restriction" claim on a getattr()
# dynamic-dispatch case that should have triggered the dynamic-uncertainty
# guardrail instead. Same class of fix as _rank_and_cap_override_methods
# (rag/ci_override_cascade.py, imported by rag/ci_agent_node.py) above
# (narrow an expensive/scarce resource by relevance instead of an
# arbitrary order), applied one level earlier in the pipeline -- to which
# MODELS get to compete for the hop budget at all, not just which methods
# on an already-chosen model do.
def _rank_and_cap_resolved_models(question: str, resolved_models: List[str], max_models: int) -> List[str]:
    """Rank resolved model technical names by lexical relevance to the
    question (dots/underscores turned into spaces, fuzzy-compared to the
    question text) and keep only the top max_models. No-op (returns the
    input unchanged) when there are already few enough candidates.
    """
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
    Bloc 7 (J23-24) / real-auth fix: for evaluate_record_rules, the
    tool call's user_groups_json must always reflect the DEMANDEUR's real
    Odoo groups -- never a value invented by the LLM from free text, which
    has no way to know the actual requester's real group memberships.

    resolved_user_group_xmlids: the demandeur's real group DB IDs (signed
    into the JWT by the Odoo controller from request.env.user.groups_id),
    already translated to xml_id strings by _resolve_user_group_xmlids()
    -- the graph identifies groups by xml_id, never by raw DB id (see that
    function's docstring for the bug this fixes).

    Also applies to button_execution_path (Bloc 7 extension, 2026-08-07):
    a "comment faire X ?" question needs the button's REAL availability for
    THIS demandeur, same reasoning as evaluate_record_rules -- the
    LLM has no way to know the actual requester's real group memberships,
    so whatever it proposes for user_groups_json is discarded here too.

    Mutates and returns tool_args for convenience; any value the LLM
    proposed is discarded and logged. No-op for every other tool.
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


# ── Q6.1 fix: strip group-resolution noise from synthesis context ─────────────

# Regex matching the "could not be resolved" boilerplate emitted by
# who_has_access_to (deterministic_tools.py L461-465) when the LLM-guessed
# group identifier doesn't match any group in the knowledge graph.
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
    to LLM-guessed group names, when the real-auth override has already
    injected the demandeur's actual groups into evaluate_record_rules.

    Context (Q6.1 regression): the synthesis LLM sees BOTH:
      - a 'could not be resolved' message from who_has_access_to (which does NOT
        receive the override, and uses whatever group name the LLM guessed),
      - a correct [FAIT DÉTERMINISTIQUE] can_view_amount() verdict computed
        on the real resolved groups via evaluate_record_rules.

    The synthesis then self-contradicts: it mentions the resolution failure
    (obsolete artifact of the LLM-guessed names) while simultaneously
    presenting the correct verdict.  Stripping the noise at the source is
    the simplest fix -- the who_has_access_to 'could not be resolved' message
    adds zero information once evaluate_record_rules has already
    run with the real groups.

    Conditions for stripping (all must be true):
      1. Real groups were resolved (the override is active).
      2. The observation matches the 'could not be resolved' pattern.
      3. At least one other observation is a [FAIT DÉTERMINISTIQUE] block
         (meaning evaluate_record_rules already computed the real
         verdict -- the 'could not be resolved' message is truly obsolete).
    """
    if not resolved_user_group_xmlids:
        return tool_observations, tool_observation_models  # No override active, keep everything.

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        return tool_observations, tool_observation_models  # No authoritative verdict yet, keep everything.

    cleaned = []
    cleaned_models = []
    for obs, model in zip(tool_observations, tool_observation_models):
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: Q6.1 fix -- stripping 'could not be "
                "resolved' observation from synthesis context (real groups override "
                "is active and a deterministic fact is present): %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
        cleaned_models.append(model)
    return cleaned, cleaned_models


def _extract_first_scoped_file_link(text: str) -> str:
    match = re.search(r"\[[^\]]+\]\(file:///[^\)]+#L\d+-L\d+\)", text)
    return match.group(0) if match else ""


# Bloc 9 gap (2026-08-13, check_native_odoo_out_of_scope.py on
# mrp.production): resolve_business_term() correctly returns
# is_resolved=False when a question names a genuinely out-of-corpus Odoo
# model (native, untouched by any custom_* module's manifest depends,
# not in CORE_MODULES_ALWAYS_LOADED) -- but nothing downstream ever acted
# on that signal. A live run showed the LLM, left with no forced tool
# dispatch and no resolved model, still trying to be helpful: it opened by
# correctly stating the model "n'a pas ete trouve dans le graphique de
# connaissance indexe", then in the SAME answer fabricated a plausible-
# sounding role-based conclusion ("les utilisateurs qui ont le role
# 'Gestionnaire de production'...") from its own pretrained Odoo
# knowledge anyway -- exactly the ungrounded-answer failure this whole
# system exists to avoid (same self-contradiction shape as module 5/8's
# Bug 2, different mechanism: no deterministic fact existed here to
# contradict, the LLM just filled the void itself).
#
# Deliberately narrow-scoped, same discipline as _force_dynamic_
# uncertainty_answer above being gated on specific question vocabulary:
# only fires when the question contains a dotted lowercase identifier
# that LOOKS like a real Odoo technical model name (e.g. "mrp.production")
# -- never on a generic/meta question that doesn't name a specific model
# at all, where an "I don't recognize this model" decline would itself be
# wrong. Deliberately does NOT try to detect "is this question about Odoo
# behavior in general" (that classification problem is exactly what this
# whole resolver pipeline already exists to solve, imperfectly); this
# guard only closes the specific confirmed gap: an explicit, unresolved,
# model-shaped mention.
_TECHNICAL_MODEL_LOOKALIKE_RE = re.compile(r"\b[a-z][a-z_]*(?:\.[a-z][a-z_]*){1,3}\b")


def _force_out_of_scope_model_answer(question: str, concept) -> Optional[str]:
    """
    Guardrail: if the business-term resolver could not resolve the
    question to any model/module AND the question names something that
    looks like a real Odoo technical model identifier, force an honest
    decline instead of letting free synthesis fall back to the LLM's own
    ungrounded general knowledge of Odoo. See the module comment above
    _TECHNICAL_MODEL_LOOKALIKE_RE for the live failure this closes and why
    the trigger is scoped this narrowly.
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
