"""Section 878 -- le singulier `ecriture` ne doit pas matcher la PERMISSION d'ecriture.

PUR-Q1 ("...(lecture/ecriture/creation/suppression)...") resolvait account.move via
l'alias `ecriture`, ce qui injectait des faits deterministes sur les avoirs dans une
reponse sur purchase.order. Garde positive sur le singulier : determinant
(un/une/cette/cet/chaque/possessif) devant, ou debut de requete. `l'ecriture` est
exclu a dessein (= permission dans le corpus). Pluriel et composes inchanges.
"""
import json
from pathlib import Path

import pytest

import code_intelligence.agent.loop  # noqa: F401  (ordre d'import : cycle signale en 876)
from code_intelligence.agent import aliases
from code_intelligence.agent.resolver import resolve_business_term

_BANK = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"


def _models(question: str):
    return resolve_business_term(question, None, llm=None).resolved_models


def _bank_question(qid: str) -> str:
    bank = json.loads(_BANK.read_text(encoding="utf-8"))
    bank = bank if isinstance(bank, list) else bank.get("questions", bank)
    return next(x["question"] for x in bank if x["id"] == qid)


def test_pur_q1_no_longer_resolves_account_move():
    models = _models(_bank_question("PUR-Q1"))
    assert "account.move" not in models, models
    assert "purchase.order" in models, models


@pytest.mark.parametrize("question", [
    "Le groupe a-t-il les droits de lecture et d'ecriture ?",
    "Qui a un acces en ecriture sur ce modele ?",
    "Pour l'ecriture, quels groupes ont le droit ?",
    "Il a lecture, ecriture, creation sur le modele",
    "Quel groupe a le droit d'écriture sur l'ACL ?",
])
def test_permission_sense_does_not_resolve_account_move(question):
    assert "account.move" not in _models(question)


@pytest.mark.parametrize("question", [
    "Peut-il poster une ecriture ?",
    "Comment annuler une ecriture deja postee ?",
    "Qui peut modifier cette ecriture ?",
    "ecriture",
    "Ecriture de cloture : qui valide ?",
    "Peut-il poster une écriture ?",
])
def test_accounting_singular_still_resolves_account_move(question):
    assert "account.move" in _models(question)


@pytest.mark.parametrize("question, expected", [
    ("Peut-on supprimer des ecritures ?", "account.move"),
    ("Les ecritures comptables sont-elles verrouillees ?", "account.move"),
    ("Peut-il poster une ecriture comptable ?", "account.move"),
    ("Comment corriger une ligne d'ecriture ?", "account.move.line"),
])
def test_plural_and_compounds_unchanged(question, expected):
    assert expected in _models(question)


def test_acc_q1_still_resolves_account_move():
    assert "account.move" in _models(_bank_question("ACC-Q1"))


def test_gate_is_what_fixes_pur_q1(monkeypatch):
    """Temoin negatif : avec la garde lexicale d'origine, PUR-Q1 resout de nouveau
    account.move -- le test ci-dessus detecte donc bien la regression."""
    import re
    monkeypatch.setitem(
        aliases._ALIAS_PATTERNS, "ecriture",
        re.compile(r"(?<!\w)" + re.escape("ecriture") + r"(?!\w)"),
    )
    assert "account.move" in _models(_bank_question("PUR-Q1"))
