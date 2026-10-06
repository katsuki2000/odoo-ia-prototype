import pytest

from core.verification.claims import ClaimType
from core.verification.extractors import extract_claims


def _claims(text, claim_type):
    return [claim for claim in extract_claims(text) if claim.claim_type is claim_type]


def _values(text):
    return [{reading.value for reading in claim.readings} for claim in _claims(text, ClaimType.NUMBER)]


@pytest.mark.parametrize("text, expected", [
    ("12 500,50", {12500.5}),
    ("1,234.56", {1234.56}),
    ("1.234.567", {1234567.0}),
    ("12,5", {12.5}),
    ("15 000", {15000.0}),
    ("0,500", {0.5}),
    ("1,234", {1234.0, 1.234}),
])
def test_number_formats_and_ambiguous_separators(text, expected):
    assert _values(f"Le montant est de {text} euros.") == [expected]


@pytest.mark.parametrize("text", [
    "Le 2026-10-05 à 14:30 ou le 05/10/2026.",
    "Odoo 17.0, version 17.0.1.2 et 4.0.0.",
    "Voir a.py:123, #L12-L25, lignes 10-12 et ligne 8.",
    "1. Premier\n2) Second\n### 3. Titre\n- 4. Item",
    "Les champs account_move_2 et res_id3.",
    "```python\nthreshold = 99999\n```",
    "[a.py:L12](file:///tmp/addons/a.py#L12-L25)",
    "Texte.\n[Source: Graphe 55]",
    "Texte.\n[ACCES RESTREINT] ELEMENTS OMIS:\n  - 9999 : raison",
    "Texte.\n[VÉRIFICATION DÉTERMINISTE] Affirmation(s) retirée(s) : 8888, a.group_x.",
])
def test_excluded_zones_yield_no_claim(text):
    assert extract_claims(text) == []


def test_repeated_claim_is_merged_with_every_span():
    claims = _claims("Seuil 5000 puis encore 5000.", ClaimType.NUMBER)
    assert len(claims) == 1
    assert len(claims[0].spans) == 2


def test_group_claims_need_the_group_prefix_form():
    text = "Groupes : account.group_account_manager, base.group_user, module.group ou account.move."
    assert [claim.key for claim in _claims(text, ClaimType.GROUP)] == [
        "account.group_account_manager", "base.group_user",
    ]


def test_method_claims_need_parentheses_and_a_lowercase_name():
    text = "Appelez `action_post()`, `account.move.write()`, super(), _(), Foo() et action_confirm."
    keys = [claim.key for claim in _claims(text, ClaimType.METHOD)]
    assert keys == ["action_post", "account.move.write", "super"]


def test_method_claim_splits_owner_and_name():
    claim = _claims("account.move.action_post()", ClaimType.METHOD)[0]
    assert (claim.owner, claim.name) == ("account.move", "action_post")
