"""
rag/ci_override_cascade.py

Method-override-cascade extraction, backfill, and contradiction-correction
helpers for the Code Intelligence agent.

Split out of rag/ci_helpers.py (2026-08-19, requested by the user as a
follow-up to the section 70 modular refactor of rag/graph.py -- same
principle: zero algorithmic change, pure relocation of a cohesive cluster
of functions that only call each other, verbatim). Covers everything that
reads analyze_method_override_chain's raw output: module names,
threshold amounts, unguarded-super() warnings, and the two synthesis-level
contradiction detectors/correctors for that same tool's findings.

_amount_present_in_text is a shared primitive also used by the hardcoded-ID
and security-lock backfills elsewhere in ci_helpers.py -- kept there, not
duplicated here.

_OVERRIDE_CHAIN_AMOUNT_RE (2026-08-20 dedup fix): also kept in ci_helpers.py,
NOT duplicated here, for the same reason -- _extract_security_lock_condition_
amounts() (a different, out-of-scope cluster in ci_helpers.py -- Python
security locks, not override cascades) reads this exact same regex directly,
because the raw 'rec.<attr> > <digits>' condition shape genuinely is shared
across both tools' outputs (see that function's own docstring for a
confirmed-live cross-contamination bug this sharing already caused once).
Imported from ci_helpers here instead, so there is exactly one definition
for both call sites to agree on.
"""

import logging
import re
from typing import List, Tuple

from code_intelligence.ci_helpers import _amount_present_in_text, _OVERRIDE_CHAIN_AMOUNT_RE

logger = logging.getLogger(__name__)


# Bloc 9 gap, found 2026-08-11 (module 1/8 rerun, bloc9-01a-business /
# bloc9-01b-technical, AFTER the has_group()/cap/truncation fixes above are
# all confirmed active): two further, distinct dropped-fact gaps on the same
# 'account.move.action_valider_avoir' override cascade, both traced by
# reading the raw analyze_method_override_chain text directly rather
# than guessing further --
#
#   (a) bloc9-01a-business: the regional module's 20000e relational-chain
#       finding is present verbatim in the (correctly-sized, post-2200-cap)
#       forced-dispatch observation, but the synthesized answer for the
#       BUSINESS-phrased question ("qui a le permission d'approuver...") ignores
#       it entirely -- not denied, just never used, a two-sentence answer
#       that only reasons from the has_group() gate. The same raw content
#       DOES get used correctly for the TECHNICAL-phrased question (01b
#       enumerates it in full) -- so this isn't a dispatch/truncation
#       problem, it's the small model treating a risk/warning-shaped
#       finding as orthogonal to an "approval rights" question instead of
#       an additional gate on top of the group requirement.
#
#   (b) bloc9-01b-technical: the third (base) override site is enumerated
#       correctly in content but mislabeled -- the LLM calls it "module
#       'account_move'" instead of "module 'custom_credit_note_approval'",
#       apparently substituting the shared file basename (all three
#       override sites live in a same-named account_move.py, only the
#       directory/module name differs) for the actual module name on the
#       one entry whose module name is a strict PREFIX of both siblings'
#       names ("custom_credit_note_approval" vs "..._regional"/"..._vip"),
#       so it's plausible the model conflated it with the file path token
#       repeated three times in the raw text rather than confusing it with
#       a sibling module. Confirmed NOT a recurrence of the original Gap 3
#       hallucination (no fabricated 4th module name, `custom_credit_note_
#       approval_global`, appears anywhere in this run) -- a narrower,
#       different failure: a real module dropped from the text entirely,
#       not an invented one added.
#
# Same deterministic-backfill principle as _backfill_missing_required_
# groups above, applied to two more fact shapes already present verbatim
# in the raw tool text: extract directly, append only what's genuinely
# missing, never override or duplicate a correct synthesis. Word-boundary
# checked for the module names specifically (plain substring would let
# 'custom_credit_note_approval' silently pass because it's a literal
# prefix of the two suffixed sibling names already correctly mentioned --
# the exact false-positive class check_bloc9_01_credit_note_cascade_e2e.py
# itself already guards against with its own word-boundary marker check).
_OVERRIDE_MODULE_RE = re.compile(r"module '([\w.]+)'")


def _extract_override_modules(raw_tool_output: str) -> List[str]:
    """Pull every override-cascade module name out of an
    analyze_method_override_chain raw observation ("module 'x'" lines),
    in first-seen order, deduplicated. Returns [] if no such line is
    present -- this pattern is specific to that one tool's output shape,
    so it's a safe no-op on any other observation mixed into the same
    scoped text."""
    modules: List[str] = []
    for match in _OVERRIDE_MODULE_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in modules:
            modules.append(name)
    return modules


def _word_boundary_present(marker: str, text: str) -> bool:
    """Same technique (and same false-positive this guards against) as
    check_bloc9_01_credit_note_cascade_e2e.py's own _word_boundary_present
    -- a plain substring check would let 'custom_credit_note_approval'
    silently pass just because it's a literal prefix of
    'custom_credit_note_approval_regional'/'..._vip', already mentioned
    correctly elsewhere in the same answer."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"(?![A-Za-z0-9_])", text) is not None


def _backfill_missing_override_modules(final_answer: str, raw_tool_output: str) -> str:
    r"""Deterministic backfill for gap (b) above: if the raw override-cascade
    text names a module (word-boundary) that never made it into the
    synthesized answer, append it as an explicit, clearly labeled fact.
    No-op whenever every module is already correctly named -- never
    duplicates or contradicts a correct synthesis, and deliberately does
    NOT try to detect or correct a mislabeling (e.g. 'account_move' used in
    its place) -- same over-trimming caution as the hallucination case in
    method_override_resolver.py (see contexte.txt section 24): safer to
    add the missing true fact alongside a wrong label than to try to edit
    prose the small model already got wrong once.

    Bloc 9 gap, found 2026-08-11 (real pytest run, this backfill's OWN new
    test against the real bloc9-01b-technical question wording): originally
    gated on _question_is_approval_related(question), copied from
    _backfill_missing_required_groups without checking it against the
    actual question this backfill exists to fix. That question --
    "...toutes les surcharges de la methode action_valider_avoir..." --
    never matches _APPROVAL_PATTERN: "valider" is glued to underscores on
    both sides inside "action_valider_avoir", so \bvalid\w*\b never finds a
    boundary to match at. The gate would have silently no-op'd on the exact
    live case this backfill targets, not just in the test. Dropped the
    gate entirely -- unconditional now, same as _backfill_link_guard_
    clarifications below (see its own docstring for the same reasoning):
    the extraction step (modules being non-empty) is already the real
    relevance guard, a question-wording check on top of that is redundant
    at best and actively wrong at worst, since in real usage this text
    only ever reaches scoped_tool_output when the override-cascade tool
    was actually invoked (forced pre-dispatch, gated on approval wording
    -- OR the ReAct loop's own free choice on a technical question just
    like this one, which needs no such wording at all).
    """
    modules = _extract_override_modules(raw_tool_output)
    if not modules:
        return final_answer

    missing = [m for m in modules if not _word_boundary_present(m, final_answer)]
    if not missing:
        return final_answer

    module_list = ", ".join(f"'{m}'" for m in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade module(s) missing "
        "from synthesized answer (present in raw tool output, dropped/mislabeled by synthesis): %s",
        module_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut "
        f"également le/les module(s) suivant(s), absent(s) ou mal identifié(s) "
        f"ci-dessus : {module_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


def _extract_override_chain_amounts(raw_tool_output: str) -> List[str]:
    """Pull every monetary threshold embedded in a Python comparison inside
    an override-cascade risk finding (e.g. 'rec.amount_total > 20000'), in
    first-seen order, deduplicated, whitespace stripped from the digits.
    Returns [] if no such expression is present. Deliberately scoped to
    this exact 'rec.<attr> > <digits>' shape (mirrors the real source's
    own Python syntax, quoted verbatim in the raw tool text) rather than a
    generic amount pattern -- narrow enough that it will never fire on
    unrelated prose, at the cost of not generalizing to a differently-
    worded threshold check on some future module (acceptable: this backfill
    only needs to catch a threshold ALREADY quoted in the raw text, not
    invent one)."""
    amounts: List[str] = []
    for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(raw_tool_output):
        amount = match.group(1).replace(" ", "").strip()
        if amount and amount not in amounts:
            amounts.append(amount)
    return amounts


def _backfill_missing_override_chain_amount(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for gap (a) above: if an override-cascade
    finding's own monetary threshold (already present verbatim in the raw
    tool text) never made it into the synthesized answer, append it as an
    explicit, clearly labeled fact -- same append-only, never-override
    discipline as every other backfill in this module. Checked both with
    and without a thousands-separator space (the LLM may re-render '20000'
    as '20 000' when paraphrasing correctly; either form counts as
    present).

    Bloc 9 gap, found 2026-08-11 (same live pytest run/root cause as
    _backfill_missing_override_modules above -- see its docstring): also
    used to be gated on _question_is_approval_related(question), same
    mistake, same fix -- dropped entirely, unconditional now. The amount
    this backfill exists to restore (bloc9-01a-business's missing 20000e)
    happens to come from an APPROVAL-phrased question, so that specific
    live failure would still have been caught by the old gate -- but
    leaving the gate in place would have left this backfill silently
    inert on the exact same technical-question class that broke its
    sibling function above, for no removed benefit (the amounts-list
    emptiness check is already the real relevance guard).

    Bloc 9 gap, found 2026-08-11 (module 5/8, bloc9-05c-no-link-trap live
    run pasted same day as the module 5/8 exception_conditions fix): the
    _OVERRIDE_CHAIN_AMOUNT_RE pattern ("rec.<attr> > <digits>") is not
    actually specific to analyze_method_override_chain's output shape
    -- it is generic enough to also match the literal Python condition
    text semgrep_locks_analyzer.py's exception_conditions now renders
    ("condition : rec.montant_estime > 10000 and not email_ok", from
    custom_purchase_request.action_valider's own unrelated 10000e gate).
    Confirmed live: a custom_asset_loan question that also resolved
    custom.purchase.request (legitimate -- the two models are linked)
    picked up a fabricated "la chaine de surcharge de methode contient une
    condition supplementaire declenchee au-dela de 10000e" fact for a
    model that has no method-override chain at all. Same class of bug as
    _backfill_missing_required_groups' account.group_account_invoice noise
    (contexte.txt section 30) and the Bug 3/Bug 4 contamination cases
    (contexte.txt sections 26/28) -- a backfill reading text belonging to
    a different mechanism/tool than the one it was built for. Fixed here
    by requiring _extract_override_modules(raw_tool_output) to also be
    non-empty: a genuine override-cascade amount finding never appears in
    analyze_method_override_chain's real output without an
    accompanying "module 'x'" line in the same text (see
    _REAL_OVERRIDE_CHAIN_RAW_TEXT in tests/test_graph.py), so this is a
    safe, narrow precondition -- not a new heuristic, the same
    extraction-non-empty relevance-guard principle already used
    everywhere else in this file, just applied to the right extractor.
    """
    if not _extract_override_modules(raw_tool_output):
        return final_answer

    amounts = _extract_override_chain_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    missing = [a for a in amounts if not _amount_present_in_text(a, final_answer)]
    if not missing:
        return final_answer

    amount_list = ", ".join(f"{a}€" for a in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade amount threshold(s) missing "
        "from synthesized answer (present in raw tool output, dropped by synthesis): %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode contient "
        f"une condition supplémentaire déclenchée au-delà de {amount_list}, distincte "
        f"du groupe requis ci-dessus. Fait extrait directement de l'analyse statique "
        f"du code."
    )


# Bloc 9 gap, module 1/8 (2026-08-12, bloc9-01b-technical): the marker-only
# E2E check (scripts/check_bloc9_01_credit_note_cascade_e2e.py) verifies
# that expected module names/amounts appear SOMEWHERE in the final answer
# (via expected_markers, and via the two backfills above when synthesis
# drops them) -- but never checks whether the LLM's own free prose ABOVE
# those facts actively contradicts them. Live run confirmed 3/3 by that
# check (all expected markers present, no forbidden markers) while the
# free prose still asserted, verbatim: (1) "Aucune autre surcharge n'a été
# détectée dans les autres modules analysés" -- immediately followed by
# the [FAIT DÉTERMINISTIQUE] naming the two other override modules that
# very sentence denies exist -- and (2) a fabricated Odoo execution
# semantic ("la surcharge la plus spécifique... est exécutée en premier...
# si elle ne lève pas d'erreur, les autres ne seront pas exécutées"), which
# is not how Odoo resolves an override chain: there is no such
# specificity-based short-circuit, and the real order (given by this same
# tool, vip -> regional -> base here) is never actually used in that
# sentence. Exactly the same family of bug as Bug 2 already documented for
# module 5/8 (_LINK_GUARD_CONTRADICTING_SENTENCE_RE): a correct fact
# appended below a free-text sentence does not, on its own, correct that
# sentence for a reader reading top-to-bottom -- a Discuss end user reads
# the wrong claim before ever reaching the fact that contradicts it. Not a
# script false positive to silence: the check does exactly what it was
# built to do (verify facts); this is a real quality gap the check was
# never designed to catch (prose/fact consistency, not fact presence).
# Same fix shape as module 5/8's Bug 2: detect the specific confirmed-real
# wrong sentence and replace it in place, do not merely append a fact
# after it.
#
# Second confirmed-real denial phrasing added 2026-08-13 (module 1/8
# rerun, bloc9-01b-technical, same session as the security-lock
# per-block scoping fix above): "il n'y a pas de surcharges de la
# methode ... detectees dans les fichiers analyses" -- a STRONGER,
# more harmful denial than "aucune autre surcharge" (that one at least
# implies one override is known; this one denies ANY exist at all),
# live-confirmed immediately followed by the [FAIT DETERMINISTIQUE]
# naming all three real modules, and by a further hallucinated tangent
# suggesting the reader grep generic core Odoo files
# (account/models/account_move.py, account/populate/account_move.py)
# that have nothing to do with this custom cascade. Coincided with this
# run being the first to hit a Groq 413 ("payload too large") on EVERY
# one of the three questions -- plausibly the ReAct-loop ToolMessage
# being cut to _TOOL_MSG_HARD_CAP=400 chars by _reduce_message_context
# left the synthesis LLM with too little real tool content to reason
# from, rather than a synthesis-quality regression on its own. That
# truncation behavior is a separate, pre-existing, documented tradeoff
# (see _reduce_message_context/_invoke_with_rate_limit above) -- NOT
# touched here; widening it would need its own dedicated diagnosis
# (which tool messages to prioritize keeping, whether 400 chars is
# still adequate now that scoped_tool_output routinely carries more
# than one tool's block per turn) rather than a incidental change
# bundled into this narrower prose-correction fix.
_OVERRIDE_COUNT_DENIAL_RE = re.compile(
    r"[^.\n]*aucune\s+autre\s+surcharge[^.\n]*\.?"
    r"|[^.\n]*il\s+n['\u2019]y\s+a\s+pas\s+de\s+surcharges?[^.\n]*detectees?[^.\n]*\.?"
)

# Confirmed-real vocabulary only (same discipline as
# _LINK_GUARD_CONTRADICTION_PATTERN above): the fabricated short-circuit
# claim found live requires BOTH "erreur" and a "ne (sera|seront) pas
# exécutée(s)" clause in the same sentence, with "erreur" preceding the
# verb clause -- matches "si elle ne lève pas d'erreur, les autres ne
# seront pas exécutées" verbatim. Deliberately narrow (same over-editing
# caution as every other neutralizer in this file, see the hallucination
# case in method_override_resolver.py, contexte.txt section 24) rather
# than a generic "any wrong claim about execution order" detector.
_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE = re.compile(
    r"[^.\n]*erreur[^.\n]*ne\s+(?:seront|sera)\s+pas\s+executee?s?[^.\n]*\.?"
)


def _answer_denies_other_overrides(final_answer: str) -> bool:
    """True if final_answer explicitly claims no other override exists --
    only meaningful as a contradiction when the raw tool output actually
    lists 2+ modules (checked by the caller, _correct_override_cascade_
    contradictions). Accent-folded, same technique as
    _answer_contradicts_link_guard."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_COUNT_DENIAL_RE.search(folded))


def _answer_asserts_override_shortcircuit(final_answer: str) -> bool:
    """True if final_answer asserts a specificity-based short-circuit
    ("most specific override runs first, others are skipped if it doesn't
    raise") that does not exist in Odoo's real override semantics."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded))


def _neutralize_override_count_denial(final_answer: str, modules: List[str]) -> str:
    """Replace the exact sentence denying any other override with the real
    count and module list, in place -- same offset-alignment technique as
    _neutralize_contradicting_link_guard_sentence (fold+lower is a 1:1,
    length-preserving transform for French text, so match.span() computed
    on the folded string lines up with the original). No-op if no such
    sentence is found."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_COUNT_DENIAL_RE.search(folded)
    if not match:
        return final_answer

    modules_list = ", ".join(f"'{m}'" for m in modules)
    replacement = (
        f"Il existe en réalité {len(modules)} surcharges de cette méthode, "
        f"dans les modules suivants : {modules_list}."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _neutralize_override_shortcircuit_sentence(final_answer: str, modules: List[str]) -> str:
    """Replace the exact sentence asserting a fabricated specificity-based
    short-circuit with the real execution semantics, in place -- same
    technique as _neutralize_override_count_denial above. modules must
    already be in real execution order (as returned by
    _extract_override_modules, itself sourced from
    resolve_method_override_chain's reversed load order) -- this
    function does not reorder them, only restates them."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    order = " → ".join(modules) if modules else "l'ordre indiqué par l'outil"
    replacement = (
        f"Odoo n'applique aucun court-circuit basé sur la spécificité ou "
        f"l'absence d'erreur : les surcharges s'exécutent toutes, dans "
        f"l'ordre réel {order}, et l'exécution d'une surcharge ne s'arrête "
        f"que si elle omet d'appeler super() ou lève explicitement une erreur."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _correct_override_cascade_contradictions(final_answer: str, raw_tool_output: str) -> str:
    """Entry point wiring the two neutralizations above into the same
    deterministic-correction discipline as _backfill_link_guard_
    clarifications: detect a confirmed-real contradiction between the
    LLM's free prose and the override-cascade facts, and replace the wrong
    sentence in place rather than only appending a correct fact below it
    -- an appended fact does not, by itself, correct a wrong sentence a
    top-to-bottom reader already read. No-op when the raw text does not
    describe an override chain at all, or describes only a single-module
    chain (a single override correctly saying "no other override exists"
    is not a contradiction)."""
    modules = _extract_override_modules(raw_tool_output)

    if len(modules) > 1 and _answer_denies_other_overrides(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis denied the existence "
            "of other overrides while %d modules were present in the raw "
            "tool output -- replacing the denial sentence with the real "
            "count and module list.",
            len(modules),
        )
        final_answer = _neutralize_override_count_denial(final_answer, modules)

    if modules and _answer_asserts_override_shortcircuit(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a "
            "fabricated specificity-based short-circuit for the override "
            "cascade -- replacing the sentence with the real (sequential, "
            "non-short-circuiting) execution semantics."
        )
        final_answer = _neutralize_override_shortcircuit_sentence(final_answer, modules)

    return final_answer


# Bloc 9 gap fix (2026-08-11, module 1/8, bloc9-01c-vip-trap): the
# SUPER() NON GARDÉ warning from method_override_resolver.py contains two
# pieces of information the synthesis LLM reliably drops when Groq 413
# truncation cuts the override-chain observation: (1) the condition field
# name (e.g. `rec.partner_id.avoir_vip_exempt`) and (2) the fact that
# super() is called unconditionally after a conditional branch. Same
# extraction-then-backfill pattern as every other backfill in this module.
_UNGUARDED_SUPER_RE = re.compile(
    r"SUPER\(\) NON GARD[ÉE].*?module '([\w.]+)'\).*?"
    r"branche conditionnelle \(`([^`]+)`\)"
)


def _extract_unguarded_super_findings(raw_tool_output: str) -> List[Tuple[str, str]]:
    """Extract (module, condition) pairs from SUPER() NON GARDÉ warnings
    in the override-chain analysis output."""
    return _UNGUARDED_SUPER_RE.findall(raw_tool_output)


def _backfill_missing_unguarded_super(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for SUPER() NON GARDÉ warnings from the
    override-cascade analysis (method_override_resolver.py). Same append-
    only, never-override discipline as every other backfill: if the raw
    tool output contains an unguarded-super warning whose condition field
    (e.g. `avoir_vip_exempt`) is missing from the synthesized answer,
    append it as a labeled fact. Covers the case where Groq 413 payload
    truncation drops the override-chain detail before the synthesis LLM
    ever sees it -- confirmed live on bloc9-01c-vip-trap (2026-08-11)."""
    findings = _extract_unguarded_super_findings(raw_tool_output)
    if not findings:
        return final_answer

    missing_items = []
    for module, condition in findings:
        # Extract the terminal field name from the condition expression,
        # e.g. "avoir_vip_exempt" from "rec.partner_id.avoir_vip_exempt".
        field_name = condition.rsplit(".", 1)[-1] if "." in condition else condition
        if field_name not in final_answer:
            missing_items.append((module, condition))

    if not missing_items:
        return final_answer

    parts = []
    for module, condition in missing_items:
        parts.append(
            f"module '{module}' : branche conditionnelle `{condition}` "
            f"avec super() rappelé inconditionnellement (risque d'annulation "
            f"silencieuse de cette logique)"
        )

    detail = " ; ".join(parts)
    logger.info(
        "Node [code_intelligence_agent]: backfilling SUPER() NON GARDÉ finding(s) "
        "missing from synthesized answer: %s", detail,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de "
        f"surcharge : {detail}. "
        f"Fait extrait directement de l'analyse statique du code."
    )


# Bloc 9 gap, found 2026-08-10 (bloc9-01a-business, generalization check
# 1/8 on custom_credit_note_approval): find_methods_with_override_risk_findings
# has no cap -- on a model shared across many adversarial customization
# modules (account.move is extended by credit-note-approval AND
# expense-risk AND others), EVERY flagged method across ALL of them gets
# forced-dispatched for any single approval-related question, regardless
# of whether it has anything to do with what was actually asked. Confirmed
# live: the regional director's 20000e cascade finding on
# action_valider_avoir never reached the synthesis answer once an
# unrelated hr_expense finding on a different method was dispatched
# alongside it in the same tool_observations blob -- the small synthesis
# LLM has a limited context budget and no way to know which finding the
# question actually needs. Ranking by lexical relevance to the question
# (rapidfuzz, already a project dependency -- see business_resolver.py)
# and capping the dispatch keeps the forced pre-dispatch scoped to what
# the question is actually about, same discipline as the other J8/J9
# structural guards (narrow the expensive step, don't widen the prompt).
# Bloc 9 gap, found 2026-08-10 (bloc9-01a-business, module 1/8 rerun AFTER
# the original cap=2 fix from earlier the same day): capping at 2 instead
# of 1 does not actually solve the problem it was written for whenever
# EXACTLY 2 candidates are flagged (the common case on a heavily-shared
# model like account.move: action_valider_avoir -- the one the question is
# about -- plus exactly one unrelated flagged method from a different
# customization module, e.g. hr_expense's _compute_commercial_partner_id).
# The old "no-op when <= cap" guard let BOTH through untouched in that
# exact case, so the irrelevant second method still consumed a full hop of
# the tight CI_MAX_HOPS=4 budget for zero value to the question -- confirmed
# live: hop_count reached 3 from forced pre-dispatch alone (1 verrous_
# securite + 2 override-cascade) before the ReAct loop even started, only 1
# hop remained, and CI_MAX_HOPS was hit before evaluate_record_rules
# or any further exploration could run, reproducing the exact "noise crowds
# out the needed fact" failure this cap was meant to prevent in the first
# place. Lowering the cap to 1 removes the ambiguity entirely: only the
# single most lexically-relevant flagged method is ever forced-dispatched,
# freeing a full extra hop for the ReAct loop on every question that
# triggers this guard, not just ones where more than 2 candidates happened
# to be flagged.
_MAX_OVERRIDE_CASCADE_DISPATCH = 1


def _rank_and_cap_override_methods(question: str, method_names: List[str]) -> List[str]:
    """Rank override-risk-flagged method names by lexical relevance to the
    question (method name with underscores turned into spaces, fuzzy-
    compared to the question text) and keep only the top
    _MAX_OVERRIDE_CASCADE_DISPATCH (1 -- see module-level comment above).
    No-op (returns the input unchanged) when there is already at most one
    candidate -- nothing to rank or drop in that case.
    """
    if len(method_names) <= _MAX_OVERRIDE_CASCADE_DISPATCH:
        return method_names
    from rapidfuzz import fuzz
    question_lower = question.lower()
    scored = [
        (name, fuzz.token_set_ratio(question_lower, name.replace("_", " ").lower()))
        for name in method_names
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:_MAX_OVERRIDE_CASCADE_DISPATCH]]
    logger.info(
        "Node [code_intelligence_agent]: override-cascade dispatch capped -- "
        "%d flagged method(s) found, keeping top %d by relevance to the question: %s.",
        len(method_names), _MAX_OVERRIDE_CASCADE_DISPATCH, kept,
    )
    return kept
