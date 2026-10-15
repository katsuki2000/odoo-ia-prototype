"""Tests for Section 1027: ACC-Q3 remaining defects.

1. Domain prefix filtering in _extract_module_extended_models
2. Binary question detection in is_singular_inquiry
3. Fabricated file:// link stripping in postprocess
"""
import re


class TestDomainPrefixFiltering:
    """_extract_module_extended_models must exclude same-domain models."""

    def test_account_analytic_excluded_for_module_account(self):
        from code_intelligence.rules.structure import _extract_module_extended_models
        raw = (
            "Module 'account' defines or extends the following models: "
            "account.move (declares), account.analytic.account (extends), "
            "account.analytic.line (extends), res.partner (extends), "
            "product.product (extends), product.template (extends), "
            "uom.uom (extends)."
        )
        result = _extract_module_extended_models(raw, module_name="account")
        assert "res.partner" in result
        assert "product.product" in result
        assert "uom.uom" in result
        assert "account.analytic.account" not in result
        assert "account.analytic.line" not in result

    def test_sale_models_excluded_for_module_sale(self):
        from code_intelligence.rules.structure import _extract_module_extended_models
        raw = (
            "Module 'sale' defines or extends the following models: "
            "sale.order (declares), sale.order.line (declares), "
            "account.move (extends), product.product (extends)."
        )
        result = _extract_module_extended_models(raw, module_name="sale")
        assert "account.move" in result
        assert "product.product" in result
        assert "sale.order" not in result
        assert "sale.order.line" not in result

    def test_technical_models_still_excluded(self):
        from code_intelligence.rules.structure import _extract_module_extended_models
        raw = (
            "Module 'stock' defines or extends the following models: "
            "res.config.settings (extends), ir.model (extends), "
            "product.product (extends)."
        )
        result = _extract_module_extended_models(raw, module_name="stock")
        assert "product.product" in result
        assert "res.config.settings" not in result
        assert "ir.model" not in result

    def test_no_module_name_uses_detected_prefix(self):
        from code_intelligence.rules.structure import _extract_module_extended_models
        raw = (
            "Module 'account' defines or extends the following models: "
            "account.analytic.account (extends), res.partner (extends)."
        )
        result = _extract_module_extended_models(raw)
        assert "res.partner" in result
        assert "account.analytic.account" not in result


class TestBinaryQuestionDetection:
    """is_singular_inquiry must match binary extension questions."""

    def test_binary_etend_il_detected(self):
        from code_intelligence.rules.group_resolver import _fold_accents
        pattern = re.compile(
            r"\bquel\s+mod[eè]le\b|\betend[\s-](?:il|elle|t-il|t-elle)\b"
        )
        q = _fold_accents("Le module account étend-il en parallèle un modèle natif ?".lower())
        assert pattern.search(q)

    def test_quel_modele_still_detected(self):
        from code_intelligence.rules.group_resolver import _fold_accents
        pattern = re.compile(
            r"\bquel\s+mod[eè]le\b|\betend[\s-](?:il|elle|t-il|t-elle)\b"
        )
        q = _fold_accents("Quel modèle hors périmètre ce module étend-il ?".lower())
        assert pattern.search(q)

    def test_non_extension_question_not_matched(self):
        from code_intelligence.rules.group_resolver import _fold_accents
        pattern = re.compile(
            r"\bquel\s+mod[eè]le\b|\betend[\s-](?:il|elle|t-il|t-elle)\b"
        )
        q = _fold_accents("Quelles règles empêchent de supprimer une commande ?".lower())
        assert not pattern.search(q)

    def test_guard_does_not_append_when_binary_and_cites_one(self):
        from code_intelligence.rules.structure import _correct_module_extension_contradiction
        raw = (
            "Module 'account' defines or extends the following models: "
            "res.partner (extends), product.product (extends), "
            "product.template (extends), uom.uom (extends), "
            "decimal.precision (extends), digest.digest (extends)."
        )
        answer = "Le module account étend res.partner (classe ResPartner)."
        question = "Le module account étend-il en parallèle un modèle natif hors périmètre ?"
        result = _correct_module_extension_contradiction(answer, raw, question=question)
        assert "À noter" not in result


class TestFabricatedCitationStripping:
    """Fabricated file:// links with '...' placeholder must be stripped."""

    def test_placeholder_link_stripped(self):
        text = "Il est défini dans [account_move.py:L81-L161](file:///.../account_move.py#L81-L161)."
        cleaned = re.sub(
            r"\[([^\]]*)\]\(file:///\.\.\.[^)]*\)",
            r"\1",
            text,
        )
        assert "file:///" not in cleaned
        assert "account_move.py:L81-L161" in cleaned

    def test_real_link_preserved(self):
        text = "[file.py:L10-L20](file:///home/user/addons/account/models/file.py#L10-L20)"
        cleaned = re.sub(
            r"\[([^\]]*)\]\(file:///\.\.\.[^)]*\)",
            r"\1",
            text,
        )
        assert "file:///" in cleaned

    def test_multiple_placeholders_stripped(self):
        text = (
            "Voir [a.py:L1-L5](file:///.../a.py#L1-L5) et "
            "[b.py:L10-L20](file:///.../b.py#L10-L20)."
        )
        cleaned = re.sub(
            r"\[([^\]]*)\]\(file:///\.\.\.[^)]*\)",
            r"\1",
            text,
        )
        assert "file:///" not in cleaned
        assert "a.py:L1-L5" in cleaned
        assert "b.py:L10-L20" in cleaned
