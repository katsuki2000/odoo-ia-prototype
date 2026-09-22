"""Section 896 -- detection deterministe (regex) de personas de securite pour
`security_principal_detection.detect_security_principals_from_question`, sur
les 5 vraies questions capability=security du banc N1."""
import json
from pathlib import Path

import pytest

from code_intelligence.agent.security_principal_detection import (
    detect_security_principals_from_question,
)

_BANK = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"


def _bank_question(qid: str) -> str:
    bank = json.loads(_BANK.read_text(encoding="utf-8"))
    bank = bank if isinstance(bank, list) else bank.get("questions", bank)
    return next(x["question"] for x in bank if x["id"] == qid)


def test_mnt_q1_single_persona_detected():
    got = detect_security_principals_from_question(_bank_question("MNT-Q1"))
    assert got == {"utilisateur_simple": {"group_xmlids": ["base.group_user"]}}


def test_stk_q1_single_persona_detected():
    got = detect_security_principals_from_question(_bank_question("STK-Q1"))
    assert got == {"simple_employe": {"group_xmlids": ["base.group_user"]}}


def test_sal_q1_two_personas_detected_even_though_bank_declares_it_explicitly():
    """L'extraction elle-meme doit trouver les 2 personas (le non-cablage du
    fallback quand le bank JSON declare deja security_principals est verifie
    a part, cote script, pas ici)."""
    got = detect_security_principals_from_question(_bank_question("SAL-Q1"))
    assert got == {
        "vendeur": {"group_xmlids": ["sales_team.group_sale_salesman"]},
        "utilisateur_du_portail": {"group_xmlids": ["base.group_portal"]},
    }


def test_pur_q1_no_persona_detected():
    """Les groupes sont nommes en prose, jamais dans un '<role> (xmlid)' --
    PUR-Q1 ne depend pas de ce mecanisme (893)."""
    assert detect_security_principals_from_question(_bank_question("PUR-Q1")) == {}


def test_acc_q1_no_persona_detected_missing_module_prefix():
    """'group_account_manager' n'a pas de prefixe de module dans le texte --
    jamais devine, faux negatif accepte (893 : ACC-Q1 n'en a pas besoin)."""
    assert detect_security_principals_from_question(_bank_question("ACC-Q1")) == {}


@pytest.mark.parametrize("question", [
    "Combien coute ce produit ?",
    "Explique le calcul de la marge.",
    "Un rapport (annuel) est-il disponible ?",  # parenthese sans xmlid
])
def test_no_false_positive_on_unrelated_text(question):
    assert detect_security_principals_from_question(question) == {}


def test_excluded_group_never_added():
    got = detect_security_principals_from_question(
        "Un agent (crm.group_agent, sans crm.group_manager) peut-il voir tout ?"
    )
    assert got == {"agent": {"group_xmlids": ["crm.group_agent"]}}
    assert "crm.group_manager" not in got["agent"]["group_xmlids"]
