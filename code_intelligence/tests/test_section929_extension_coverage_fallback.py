"""
code_intelligence/tests/test_section929_extension_coverage_fallback.py

todo/contexte.txt section 929 (points 2/3, unified as fix G): two real
regressions found in the SAME rejeu, both landing on
_correct_module_extension_contradiction (code_intelligence/rules/structure.py):

- SAL-Q3: "Aucun modele natif hors du perimetre 'vente' n'est directement
  etendu par sale.order." -- a passive-voice denial ("Aucun X n'est
  etendu") that _MODULE_EXTENSION_DENIAL_RE's active-voice-only patterns
  ("n'etend pas", "ne s'etend pas", ...) do not match at all. Verified
  directly: _answer_denies_module_extension() returns False on this exact
  text, so the guard never even attempts a correction, despite real
  extends-evidence being available this same turn (verified separately by
  running dispatch_inheritance() against the real graph: 'account.move
  (extends)' is present in the module-mode observation it produces).

- ACC-Q3: the guard DOES fire on the answer's first denial sentence, but
  the answer restates the same wrong claim in its closing "En resume"
  sentence with a trailing context _MODULE_EXTENSION_DENIAL_RE's suffix
  alternation (perimetre|hors de|en dehors de) does not cover: "...n'etend
  pas un modele natif d'un autre domaine." -- left uncorrected, directly
  contradicting the corrected sentence just above it.

Fix: (a) add "domaine" to the suffix alternation (closes ACC-Q3's specific
gap, same incremental pattern as sections 840/841/842-843/844/856/857);
(b) call the already-existing, wording-independent
_answer_lacks_extension_coverage (section 858) as a second, coverage-based
trigger in _correct_module_extension_contradiction, appending a corrective
note when the answer still cites essentially none of the real extended-model
list after the regex-based pass -- catching any future denial phrasing
_MODULE_EXTENSION_DENIAL_RE does not recognize (closes SAL-Q3's class of gap
for good, not just this one wording).
"""

from code_intelligence.rules.structure import (
    _answer_denies_module_extension,
    _correct_module_extension_contradiction,
)

_SALE_RAW_OUTPUT = (
    "Modules implicated for model 'sale.order': sale (declares).\n"
    "Module 'sale' defines or extends the following models: "
    "account.move (extends), account.move.line (extends), "
    "crm.team (extends), res.partner (extends)."
)

_SALE_QUESTION = (
    "sale.order est-il un nouveau modele ou une extension ? Quel modele "
    "natif hors du perimetre 'vente' ce module etend-il directement, et "
    "sous quel nom de classe ?"
)

_ACCOUNT_RAW_OUTPUT = (
    "Modules implicated for model 'account.move': account (declares).\n"
    "Module 'account' defines or extends the following models: "
    "account.move (declares), res.partner (extends), "
    "product.template (extends), res.company (extends)."
)

_ACCOUNT_QUESTION = (
    "account.move est-il un nouveau modele ou une extension ? Le module "
    "account etend-il en parallele un modele natif hors de son propre "
    "perimetre comptable ?"
)


# ── SAL-Q3 class: passive-voice denial, regex never matches ─────────────

def test_passive_voice_denial_not_matched_by_regex():
    # Red witness: confirms _answer_denies_module_extension really does not
    # catch this exact, real (not invented) phrasing.
    answer = (
        "Aucun modele natif hors du perimetre « vente » n'est directement "
        "etendu par sale.order. Le modele est donc autonome, avec la "
        "classe principale nommee sale.order."
    )
    assert not _answer_denies_module_extension(answer)


def test_passive_voice_denial_still_corrected_via_coverage_fallback():
    answer = (
        "Aucun modele natif hors du perimetre « vente » n'est directement "
        "etendu par sale.order. Le modele est donc autonome, avec la "
        "classe principale nommee sale.order."
    )
    fixed = _correct_module_extension_contradiction(
        answer, _SALE_RAW_OUTPUT, question=_SALE_QUESTION
    )
    assert "account.move" in fixed
    # The original (wrong but now-superseded) sentence is not required to
    # disappear -- unlike the regex path, the fallback appends a corrective
    # note rather than attempting an in-place rewrite it cannot reliably
    # locate for an unrecognized phrasing.
    assert fixed != answer


def test_answer_already_citing_real_models_is_left_alone():
    # No coverage problem -> no fallback note appended, whatever the guard's
    # regex does or does not match.
    answer = (
        "sale.order est un nouveau modele. Le module sale etend par "
        "ailleurs account.move et account.move.line en dehors de son "
        "propre perimetre."
    )
    fixed = _correct_module_extension_contradiction(
        answer, _SALE_RAW_OUTPUT, question=_SALE_QUESTION
    )
    assert fixed == answer


# ── ACC-Q3 class: regex fires once, later restatement uses an uncovered
#    trailing context ("d'un autre domaine") ─────────────────────────────

def test_uncovered_trailing_context_domaine_now_matched():
    answer = (
        "account.move est un modele propre a l'application comptable et "
        "n'etend pas un modele natif d'un autre domaine."
    )
    assert _answer_denies_module_extension(answer)


def test_acc_q3_style_duplicated_denial_fully_corrected():
    # Reproduces the exact self-contradiction pattern from todo/contexte.txt
    # section 929 point 3: first sentence uses a recognized ending
    # ("hors de son propre perimetre"), the closing "En resume" restates
    # the same wrong claim with the previously-uncovered "d'un autre
    # domaine" ending. Both must be corrected, and the final answer must
    # not contain a residual denial of either shape.
    answer = (
        "Le modele account.move est declare dans le module account. "
        "En realite, ce module n'etend pas de modele natif hors de son "
        "propre perimetre.\n\n"
        "En resume, account.move est un modele propre a l'application "
        "comptable et n'etend pas un modele natif d'un autre domaine."
    )
    fixed = _correct_module_extension_contradiction(
        answer, _ACCOUNT_RAW_OUTPUT, question=_ACCOUNT_QUESTION
    )
    assert "res.partner" in fixed
    assert "product.template" in fixed
    assert "res.company" in fixed
    # No denial of either shape should survive.
    assert "n'etend pas" not in fixed


# ── Non-regression: existing section 838/840/841/856/858 behavior ───────

def test_no_correction_without_extends_evidence_still_holds():
    answer = "Le module `stock` n'etend pas de modele hors de son propre perimetre."
    raw = "Module 'stock' defines or extends the following models: stock.picking (declares)."
    fixed = _correct_module_extension_contradiction(answer, raw, question=_ACCOUNT_QUESTION)
    assert fixed == answer


def test_no_correction_for_unrelated_question_still_holds():
    answer = (
        "Aucun modele natif hors du perimetre « vente » n'est directement "
        "etendu par sale.order."
    )
    fixed = _correct_module_extension_contradiction(
        answer, _SALE_RAW_OUTPUT, question="Quel est le montant du seuil d'approbation ?"
    )
    assert fixed == answer
