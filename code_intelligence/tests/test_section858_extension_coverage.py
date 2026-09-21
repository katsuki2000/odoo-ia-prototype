"""
code_intelligence/tests/test_section858_extension_coverage.py

todo/contexte.txt section 858 (Option B1, mandated after the negation-
wording whack-a-mole -- 840->841->842/843->844->856->857 -- hit
diminishing returns 2 recidives in a row): _answer_lacks_extension_coverage
is a GENERIC, wording-independent replacement for trying to enumerate one
more negation verb/synonym in _MODULE_EXTENSION_DENIAL_RE -- it checks
whether final_answer cites essentially none of the real extended-model
list, regardless of how the denial or omission is phrased.
"""

from code_intelligence.rules.structure import _answer_lacks_extension_coverage

_25_MODELS = [
    "account.analytic.account", "account.analytic.applicability",
    "account.analytic.distribution.model", "account.analytic.line",
    "base.document.layout", "base.partner.merge.automatic.wizard",
    "decimal.precision", "digest.digest", "ir.actions.report",
    "ir.attachment", "ir.http", "ir.module.module", "kpi.provider",
    "onboarding.onboarding", "onboarding.onboarding.step",
    "product.category", "product.product", "product.template",
    "res.company", "res.config.settings", "res.currency", "res.groups",
    "res.partner", "res.partner.bank", "uom.uom",
]


def test_no_extended_models_never_triggers():
    # Nothing to compare against -> never a coverage problem, whatever the
    # answer says.
    assert not _answer_lacks_extension_coverage("Peu importe le texte.", [])


def test_pure_denial_lacks_coverage():
    # Section 841's exact "verbe orphelin" case -- no model name cited at
    # all, whatever the exact negation wording.
    answer = (
        "- **Héritage** : il ne s'agit pas d'une extension d'un modèle "
        "natif hors de son périmètre comptable."
    )
    assert _answer_lacks_extension_coverage(answer, _25_MODELS)


def test_857_uncovered_verb_still_caught_by_coverage():
    # Section 857's 2 residual formulations -- neither matched by
    # _MODULE_EXTENSION_DENIAL_RE ("il ne s'agit pas d'une extension d'un
    # modèle natif existant" has no perimeter marker; "ne dépend pas"
    # uses an uncovered verb) -- both still correctly flagged by coverage,
    # since neither cites a single real model name.
    answer_1 = (
        "il ne s'agit pas d'une extension d'un modèle natif existant "
        "(ex. `res.partner`)."
    )
    assert _answer_lacks_extension_coverage(answer_1, _25_MODELS)

    answer_2 = (
        "**`account.move` est un nouveau modèle créé par le module "
        "`account`** et ne dépend pas d'un modèle natif hors de son "
        "domaine comptable."
    )
    assert _answer_lacks_extension_coverage(answer_2, _25_MODELS)


def test_correct_answer_has_full_coverage():
    # The guard's own replacement text (or an LLM correctly citing the real
    # list) mentions all 25 -> well above threshold, never flagged.
    answer = "En réalité, ce module étend bien 25 modèle(s) hors de son " \
        "propre périmètre : " + ", ".join(f"'{m}'" for m in _25_MODELS) + "."
    assert not _answer_lacks_extension_coverage(answer, _25_MODELS)


def test_partial_coverage_below_threshold_is_flagged():
    answer = "Le module étend uniquement res.partner, rien d'autre hors de son périmètre."
    # 1/25 = 4% << 30% default threshold.
    assert _answer_lacks_extension_coverage(answer, _25_MODELS)


def test_partial_coverage_above_threshold_is_not_flagged():
    small_list = ["res.partner", "product.template", "res.company", "uom.uom"]
    answer = "Le module étend res.partner et product.template hors de son périmètre."
    # 2/4 = 50% >= 30% default threshold.
    assert not _answer_lacks_extension_coverage(answer, small_list)


def test_threshold_is_configurable():
    answer = "Le module étend uniquement res.partner."
    small_list = ["res.partner", "product.template", "res.company", "uom.uom"]
    # 1/4 = 25%: below a strict 0.3 threshold, above a lax 0.2 one.
    assert _answer_lacks_extension_coverage(answer, small_list, threshold=0.3)
    assert not _answer_lacks_extension_coverage(answer, small_list, threshold=0.2)


def test_accent_and_case_insensitive_matching():
    # Coverage matching must fold accents/case the same way as the rest of
    # this guard family (group_resolver._fold_accents), so a model name
    # cited with different capitalization still counts.
    answer = "Le module étend bien RES.PARTNER hors de son périmètre."
    assert not _answer_lacks_extension_coverage(answer, ["res.partner"])
