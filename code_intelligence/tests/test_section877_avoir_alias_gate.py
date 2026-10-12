"""Section 877 -- l'alias `avoir` (note de credit) ne doit pas matcher le verbe.

SAL-Q5 ("...de ne pas avoir de date de confirmation...") resolvait account.move
via l'alias `avoir`, ce qui declenchait un dump analyze_data_constraints de
43 798 car. (31 s). Garde positive sur le singulier : determinant devant, ou
debut de requete. Le pluriel `avoirs` reste inchange.
"""
import json
import re
from pathlib import Path

import pytest

import code_intelligence.agent.loop  # noqa: F401  (ordre d'import : cycle signale en 876)
from code_intelligence.agent import aliases
from code_intelligence.agent.resolver import resolve_business_term

_BANK = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"


def _sal_q5_question() -> str:
    bank = json.loads(_BANK.read_text(encoding="utf-8"))
    bank = bank if isinstance(bank, list) else bank.get("questions", bank)
    return next(x["question"] for x in bank if x["id"] == "SAL-Q5")


def _models(question: str):
    return resolve_business_term(question, None, llm=None, use_static_aliases=True).resolved_models


def test_sal_q5_no_longer_resolves_account_move():
    models = _models(_sal_q5_question())
    assert models == ["sale.order"], models


@pytest.mark.parametrize("question", [
    "Une commande ne peut pas avoir de date de livraison vide ?",
    "Faut-il avoir le groupe manager pour confirmer ?",
    "Un vendeur doit-il d'avoir un accord avant de valider ?",
])
def test_verb_avoir_does_not_resolve_account_move(question):
    assert "account.move" not in _models(question)


@pytest.mark.parametrize("question", [
    "avoir",
    "Avoir client : qui valide ?",
    "Qui peut approuver un avoir de 25000€ ?",
    "Comment valider l'avoir client ?",
    "Qui approuve cet avoir exceptionnel ?",
    "Peut-on annuler un avoir deja valide ?",
    "Comment créer un avoir (note de crédit) dans Odoo ?",
    "Comment créer et valider un avoir ou une note de crédit sur une facture ?",
    "Qui doit approuver un avoir dans la politique interne ?",
])
def test_noun_avoir_still_resolves_account_move(question):
    assert "account.move" in _models(question)


@pytest.mark.parametrize("question", [
    "avoirs",
    "Regles sur les avoirs fournisseurs",
    "Combien d'avoirs ont ete approuves ?",
])
def test_plural_avoirs_unchanged(question):
    assert "account.move" in _models(question)


def test_savoir_still_not_matched():
    assert not resolve_business_term("je veux savoir comment faire", None, use_static_aliases=True).resolved_models


def test_gate_is_what_fixes_sal_q5(monkeypatch):
    """Temoin negatif : avec la garde lexicale d'origine, SAL-Q5 resout a
    nouveau account.move -- le test ci-dessus detecte donc bien la regression."""
    monkeypatch.setitem(
        aliases._ALIAS_PATTERNS, "avoir",
        re.compile(r"(?<!\w)" + re.escape("avoir") + r"(?!\w)"),
    )
    assert "account.move" in _models(_sal_q5_question())
