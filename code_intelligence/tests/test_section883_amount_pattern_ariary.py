"""Section 883 -- `_extract_amount` doit reconnaitre l'Ariary (Ar), seule devise
non-EUR presente dans le corpus, sans faux positif sur des mots francais
courants finissant en "ar"/"AR" (case-sensible, pas de IGNORECASE sur ce token).
"""
import pytest

from code_intelligence.utils import _extract_amount


@pytest.mark.parametrize("question, expected", [
    ("un avoir de 500 000 Ar", 500000.0),
    ("un avoir de plus de 500 000 Ar ?", 500000.0),
    ("un remboursement de 25 900 000 Ar", 25900000.0),
    ("le seuil est de 12 260 000 Ar", 12260000.0),
])
def test_ariary_amount_extracted(question, expected):
    assert _extract_amount(question) == expected


@pytest.mark.parametrize("question, expected", [
    ("25000€", 25000.0),
    ("25 000 EUR", 25000.0),
    ("25000 euros", 25000.0),
    ("25000 EUROS", 25000.0),
])
def test_eur_amount_still_extracted(question, expected):
    assert _extract_amount(question) == expected


@pytest.mark.parametrize("question", [
    "aucun montant ici",
    "4 permissions accordees",
    "un salaire de base",
    "il a un an d'anciennete",
    "ce montant reste a debattre",
])
def test_no_false_positive(question):
    assert _extract_amount(question) is None
