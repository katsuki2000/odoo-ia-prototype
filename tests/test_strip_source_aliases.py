"""Documentary answers must not carry the internal per-call source aliases (S1, S2, ...)."""

import pytest

from document_rag.generate_helpers import strip_source_aliases


@pytest.mark.parametrize("raw, expected", [
    ("Ces étapes sont documentées dans la procédure de déploiement [Source S2].",
     "Ces étapes sont documentées dans la procédure de déploiement."),
    ("Étapes documentées (sources S3 et S4) dans le guide.", "Étapes documentées dans le guide."),
    ("Voir la procédure [S1, S3] pour le détail.", "Voir la procédure pour le détail."),
    ("Le rollback existe [Sources S2, S3].", "Le rollback existe."),
    ("Détail dans [Source S2](http://localhost:8069/web#source-s2) du guide.", "Détail dans du guide."),
    ("Confirmé (Source: S2) ici.", "Confirmé ici."),
    ("Appliquez les règles suivantes (Sources S4-S5) :", "Appliquez les règles suivantes :"),
    ("Voir [S1 à S3] et (sources S2 – S4).", "Voir et."),
])
def test_alias_markers_are_removed(raw, expected):
    assert strip_source_aliases(raw) == expected


def test_text_without_alias_is_unchanged():
    text = "### Titre\n\n- Étape **1** : lancer `odoo-bin -u module`.\n- Étape 2.\n\nVoir [la doc](https://example.com/doc)."
    assert strip_source_aliases(text) == text


def test_fenced_code_blocks_are_untouched():
    text = "Avant [Source S2].\n```bash\necho [S1]  (source S2)\n```\nAprès [S3]."
    assert strip_source_aliases(text) == "Avant.\n```bash\necho [S1]  (source S2)\n```\nAprès."


def test_alias_opening_a_line_leaves_no_leading_space():
    assert strip_source_aliases("[S1] Texte.\nSuite [S2]") == "Texte.\nSuite"


def test_empty_and_none_like_values():
    assert strip_source_aliases("") == ""
    assert strip_source_aliases(None) is None
