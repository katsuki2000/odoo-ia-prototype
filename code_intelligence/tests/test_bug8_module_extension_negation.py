"""
code_intelligence/tests/test_bug8_module_extension_negation.py

todo/contexte.txt section 838 (point 4, ACC-Q3/STK-Q3 negation pattern,
sections 809-836): mechanical correction of a synthesized answer that
denies a module extends any model outside its own perimeter, while
list_involved_modules' own module-mode output lists at least one such
(extends) finding.
"""

from code_intelligence.rules.structure import (
    _extract_module_extended_models,
    _answer_denies_module_extension,
    _correct_module_extension_contradiction,
)

_RAW_OUTPUT = (
    "Modules implicated for model 'account.move': account (declares).\n"
    "Module 'account' defines or extends the following models: "
    "account.move (declares), res.partner (extends), product.template (extends), "
    "res.company (extends)."
)

_QUESTION = (
    "Le module account etend-il en parallele un modele natif hors de son "
    "propre perimetre comptable ?"
)


def test_extract_module_extended_models_skips_declares():
    extended = _extract_module_extended_models(_RAW_OUTPUT)
    assert extended == ["res.partner", "product.template", "res.company"]
    assert "account.move" not in extended


def test_extract_module_extended_models_scoped_to_module():
    other = _RAW_OUTPUT + "\nModule 'sale' defines or extends the following models: sale.order (declares), account.move (extends)."
    assert _extract_module_extended_models(other, module_name="account") == [
        "res.partner", "product.template", "res.company",
    ]
    assert _extract_module_extended_models(other, module_name="sale") == ["account.move"]


def test_denial_sentence_detected():
    answer = (
        "Le module `account` n\u2019\u00e9tend pas un mod\u00e8le natif qui ne fait pas "
        "partie de son p\u00e9rim\u00e8tre comptable."
    )
    assert _answer_denies_module_extension(answer)


def test_correct_sentence_not_flagged():
    # todo/contexte.txt rule: this guard must not fire on a genuinely
    # correct answer that simply never uses a denial phrasing.
    answer = "Le module `account` \u00e9tend `res.partner` et `product.template`."
    assert not _answer_denies_module_extension(answer)


def test_correction_replaces_denial_with_real_module_list():
    answer = (
        "### Extension du module account\n\n"
        "- Le module account n\u2019\u00e9tend pas un mod\u00e8le natif qui ne fait pas "
        "partie de son p\u00e9rim\u00e8tre comptable.\n"
        "  - Il ne modifie pas, par exemple, res.partner ou d\u2019autres "
        "mod\u00e8les m\u00e9tier non li\u00e9s \u00e0 la comptabilit\u00e9.\n"
    )
    fixed = _correct_module_extension_contradiction(answer, _RAW_OUTPUT, question=_QUESTION)
    assert "n\u2019\u00e9tend pas" not in fixed
    assert "res.partner" in fixed
    assert "product.template" in fixed
    assert "res.company" in fixed
    assert "3 mod\u00e8le(s)" in fixed
    # untouched trailing content is preserved
    assert "d\u2019autres" in fixed


def test_no_correction_without_extends_evidence():
    answer = "Le module `stock` n\u2019\u00e9tend pas de mod\u00e8le hors de son propre p\u00e9rim\u00e8tre."
    raw = "Module 'stock' defines or extends the following models: stock.picking (declares)."
    fixed = _correct_module_extension_contradiction(answer, raw, question=_QUESTION)
    assert fixed == answer


def test_no_correction_for_unrelated_question():
    answer = (
        "Le module account n\u2019\u00e9tend pas un mod\u00e8le natif hors de son "
        "p\u00e9rim\u00e8tre comptable."
    )
    fixed = _correct_module_extension_contradiction(
        answer, _RAW_OUTPUT, question="Quel est le montant du seuil d'approbation ?"
    )
    assert fixed == answer


def test_correction_does_not_swallow_preceding_clause_across_model_name_dot():
    # Section 840 regression: a model name like "account.move" contains a
    # literal '.', which used to make the (now-removed) unbounded [^.\n]*
    # prefix anchor right after that '.' and swallow every character up to
    # the real denial phrase, including an unrelated CORRECT clause sharing
    # the same comma-joined sentence (reproduced verbatim from a real ACC-Q3
    # rejeu, todo/contexte.txt section 840).
    answer = (
        "En r\u00e9sum\u00e9, **account.move est un nouveau mod\u00e8le cr\u00e9\u00e9 par le module "
        "account** et **le module ne s\u2019\u00e9tend pas sur un mod\u00e8le natif hors de "
        "son p\u00e9rim\u00e8tre comptable**."
    )
    fixed = _correct_module_extension_contradiction(answer, _RAW_OUTPUT, question=_QUESTION)
    assert "account.move est un nouveau mod\u00e8le cr\u00e9\u00e9 par le module account" in fixed
    assert "ne s\u2019\u00e9tend pas" not in fixed
    assert "res.partner" in fixed and "product.template" in fixed and "res.company" in fixed


def test_correction_does_not_leave_dangling_verb_before_replacement():
    # Section 841 regression: when the denial is nested in a construction
    # like "il ne s'agit pas de ..." (verb+subject NOT part of the matched
    # negation fragment itself), the OLD fragment-only replacement left
    # "il ne s'agit " dangling immediately before the new standalone
    # sentence ("il ne s'agit En r\u00e9alit\u00e9, ...") -- grammatically broken.
    # The whole-sentence expansion (option 4, section 842) fixes this as a
    # side effect: the entire sentence containing "il ne s'agit" is now
    # part of the replaced span, so no dangling verb stem can remain.
    answer = (
        "- **H\u00e9ritage** : il ne s\u2019agit pas d\u2019une extension d\u2019un mod\u00e8le natif "
        "hors de son p\u00e9rim\u00e8tre comptable."
    )
    fixed = _correct_module_extension_contradiction(answer, _RAW_OUTPUT, question=_QUESTION)
    assert "il ne s\u2019agit En r\u00e9alit\u00e9" not in fixed
    assert "s\u2019agit pas" not in fixed
    assert "res.partner" in fixed and "product.template" in fixed and "res.company" in fixed


def test_module_mode_evidence_survives_model_scoped_filtering_via_raw_tool_output():
    # Section 840: list_involved_modules' MODULE-mode observation is
    # recorded under tool_observation_models="account" (the module name),
    # never under the resolved MODEL name "account.move" -- so
    # _scoped_raw_tool_output (filtered on resolved models) structurally
    # never contains it. _apply_backfill_chain must be given the unscoped
    # raw_tool_output for this one guard, or the correction silently no-ops
    # even though the evidence genuinely exists in this turn's tool calls.
    import code_intelligence.agent.tools  # noqa: F401 -- warm up import order
    from code_intelligence.agent.postprocess import _apply_backfill_chain

    final_answer = (
        "En r\u00e9sum\u00e9, le module ne s\u2019\u00e9tend pas sur un mod\u00e8le natif hors de son "
        "p\u00e9rim\u00e8tre comptable."
    )
    scoped_tool_output = "some account.move-scoped block, no module-mode sentence here"
    raw_tool_output = scoped_tool_output + "\n\n" + _RAW_OUTPUT

    unfixed = _apply_backfill_chain(final_answer, scoped_tool_output, _QUESTION)
    assert "ne s\u2019\u00e9tend pas" in unfixed

    fixed = _apply_backfill_chain(
        final_answer, scoped_tool_output, _QUESTION, raw_tool_output=raw_tool_output,
    )
    assert "ne s\u2019\u00e9tend pas" not in fixed
    assert "res.partner" in fixed


def test_several_denial_sentences_yield_a_single_real_extension_statement():
    answer = (
        "- **Extension** : le module account ne s\u2019\u00e9tend pas hors de son p\u00e9rim\u00e8tre comptable. "
        "Le module account n\u2019\u00e9tend pas non plus un mod\u00e8le natif en dehors de son domaine.\n"
    )
    fixed = _correct_module_extension_contradiction(answer, _RAW_OUTPUT, question=_QUESTION)
    assert fixed.count("\u00e9tend bien 3 mod\u00e8le(s)") == 1
    assert "n\u2019\u00e9tend pas" not in fixed
