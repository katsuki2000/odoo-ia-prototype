# -*- coding: utf-8 -*-
"""
Tests for core/html_sanitizer.py -- backend HTML-to-Markdown defense.
Verifies that common LLM-emitted HTML structures are converted to their
Markdown equivalents before reaching the frontend.
"""

from core.output import sanitize_html_to_markdown


class TestHeadingConversion:
    def test_h5_with_classes(self):
        html = '<h5 class="miro-heading mt-2 mb-1 font-weight-bold">Titre principal</h5>'
        result = sanitize_html_to_markdown(html)
        assert "## Titre principal" in result
        assert "<h5" not in result

    def test_h6_with_classes(self):
        html = '<h6 class="miro-heading mt-2 mb-1 font-weight-bold">Sous-titre</h6>'
        result = sanitize_html_to_markdown(html)
        assert "### Sous-titre" in result
        assert "<h6" not in result

    def test_h1_to_h4(self):
        for level, prefix in [(1, "# "), (2, "## "), (3, "### "), (4, "#### ")]:
            html = f"<h{level}>Heading {level}</h{level}>"
            result = sanitize_html_to_markdown(html)
            assert f"{prefix}Heading {level}" in result


class TestListConversion:
    def test_ul_with_li(self):
        html = '<ul class="miro-list pl-3 mb-2"><li><strong>Item A</strong></li><li>Item B</li></ul>'
        result = sanitize_html_to_markdown(html)
        assert "- **Item A**" in result
        assert "- Item B" in result
        assert "<ul" not in result
        assert "<li" not in result

    def test_ol_with_li(self):
        html = "<ol><li>First</li><li>Second</li><li>Third</li></ol>"
        result = sanitize_html_to_markdown(html)
        assert "1. First" in result
        assert "2. Second" in result
        assert "3. Third" in result


class TestInlineConversion:
    def test_strong_to_bold(self):
        assert "**texte gras**" in sanitize_html_to_markdown("<strong>texte gras</strong>")

    def test_strong_with_attributes(self):
        assert "**gras**" in sanitize_html_to_markdown('<strong class="foo">gras</strong>')

    def test_em_to_italic(self):
        assert "*italique*" in sanitize_html_to_markdown("<em>italique</em>")

    def test_br_to_newline(self):
        result = sanitize_html_to_markdown("Ligne 1<br/>Ligne 2")
        assert "Ligne 1\nLigne 2" in result

    def test_br_self_closing(self):
        result = sanitize_html_to_markdown("A<br>B<br />C")
        assert "<br" not in result


class TestBlockConversion:
    def test_p_tag(self):
        result = sanitize_html_to_markdown("<p>Paragraph text</p>")
        assert "Paragraph text" in result
        assert "<p" not in result

    def test_div_tag(self):
        result = sanitize_html_to_markdown("<div>Content</div>")
        assert "Content" in result
        assert "<div" not in result


class TestBugAReproduction:
    """Reproduces the exact output from the live Bug A screenshot."""

    def test_real_bug_a_output(self):
        html = (
            '<h5 class="miro-heading mt-2 mb-1 font-weight-bold">'
            "Demande de mise a disposition : besoin d'approbation</h5>"
            "<br/><br/>Oui, une demande de mise a disposition doit etre approuvee."
            '<h6 class="miro-heading mt-2 mb-1 font-weight-bold">'
            "Qui doit l'approuver ?</h6>"
            '<ul class="miro-list pl-3 mb-2">'
            "<li><strong>Directeur Technique</strong> si le montant est inferieur a 500 000 Ar.</li>"
            "<li><strong>Directeur General</strong> si le montant est superieur ou egal a 500 000 Ar.</li>"
            "</ul>"
        )
        result = sanitize_html_to_markdown(html)

        assert "<h5" not in result
        assert "<h6" not in result
        assert "<ul" not in result
        assert "<li" not in result
        assert "<br" not in result

        assert "## Demande de mise a disposition" in result
        assert "### Qui doit l'approuver" in result
        assert "- **Directeur Technique**" in result
        assert "- **Directeur General**" in result


class TestPassthrough:
    def test_no_html_unchanged(self):
        md = "### Titre\n\n- **Item** : valeur\n- Autre item"
        assert sanitize_html_to_markdown(md) == md

    def test_empty_string(self):
        assert sanitize_html_to_markdown("") == ""

    def test_none_returns_none(self):
        assert sanitize_html_to_markdown(None) is None

    def test_no_triple_newlines(self):
        html = "<p>A</p><br/><br/><p>B</p>"
        result = sanitize_html_to_markdown(html)
        assert "\n\n\n" not in result
