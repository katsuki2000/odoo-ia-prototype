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
