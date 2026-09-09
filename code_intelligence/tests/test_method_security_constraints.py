"""
code_intelligence/tests/test_method_security_constraints.py

Bloc P1 -- "enriched override chain" (see todo/contexte.txt section 231/233):
extract_method_security_constraints() attaches each security lock finding
(has_group requirement, UserError/ValidationError guard) to the specific
method override site it belongs to, instead of leaving analyze_security_locks'
flat, file-scoped dump to be manually correlated with an override cascade.

Covers:
  - extract_method_security_constraints() in isolation (line-range filtering).
  - Line-number tracking added to PythonSecurityLockAnalysis
    (required_group_linenos / exception_linenos), including the
    regex-fallback path (unknown line, must stay excluded).
  - End-to-end wiring: analyze_method_override_chain() now surfaces each
    site's own security constraints, not just the unguarded-super/
    relational-chain warnings it already reported.
"""

import textwrap

import networkx as nx
import pytest

from code_intelligence.overrides import analyze_method_override_chain
from code_intelligence.security import (
    analyze_python_security_locks,
    extract_method_security_constraints,
)


TWO_METHOD_TWO_THRESHOLD_SOURCE = textwrap.dedent("""\
    class DeepDocument(models.Model):
        _inherit = 'custom.deep.document'

        def action_validate_level2(self):
            if not self.env.user.has_group('account.group_account_manager'):
                raise UserError("Level2 requires account manager")
            return True

        def action_final_approve(self):
            if not self.env.user.has_group('base.group_system'):
                raise UserError("Final approve requires system admin")
            return True
""")


class TestExtractMethodSecurityConstraintsIsolation:
    def test_attributes_group_and_exception_to_the_right_site_only(self):
        """Two distinct has_group()/raise pairs in two different methods of
        the same file -- each must be attributed only to its own method's
        line range, never bleed into the other."""
        analysis = analyze_python_security_locks(TWO_METHOD_TWO_THRESHOLD_SOURCE, "deep_document.py")

        level2_constraints = extract_method_security_constraints(analysis, lineno=4, end_lineno=7)
        final_approve_constraints = extract_method_security_constraints(analysis, lineno=9, end_lineno=12)

        assert any("account.group_account_manager" in c for c in level2_constraints)
        assert not any("base.group_system" in c for c in level2_constraints)
        assert any("Level2 requires account manager" in c for c in level2_constraints)

        assert any("base.group_system" in c for c in final_approve_constraints)
        assert not any("account.group_account_manager" in c for c in final_approve_constraints)
        assert any("Final approve requires system admin" in c for c in final_approve_constraints)

    def test_line_range_outside_any_finding_returns_nothing(self):
        """A range that doesn't cover any real finding must yield an empty
        list, not the whole file's findings."""
        analysis = analyze_python_security_locks(TWO_METHOD_TWO_THRESHOLD_SOURCE, "deep_document.py")
        assert extract_method_security_constraints(analysis, lineno=1, end_lineno=2) == []

    def test_condition_and_link_guard_are_preserved_in_the_rendered_text(self):
        """The site-scoped rendering must not lose the condition text or a
        detected link-guard annotation -- same information already
        available in the file-level dump, just correctly attributed."""
        code = textwrap.dedent("""\
            class CustomAssetLoan(models.Model):
                _inherit = 'custom.asset.loan'

                def action_confirm(self):
                    if self.demande_achat_liee_id and self.demande_achat_liee_id.montant_estime > 2000:
                        raise UserError("Approval required above threshold")
                    return True
        """)
        analysis = analyze_python_security_locks(code, "asset_loan.py")
        constraints = extract_method_security_constraints(analysis, lineno=4, end_lineno=6)

        assert len(constraints) == 1
        assert "condition :" in constraints[0]
        assert "demande_achat_liee_id" in constraints[0]
        assert "GARDE DE LIEN" in constraints[0]

    def test_regex_fallback_findings_have_unknown_lineno_and_are_excluded(self):
        """Unparsable code falls back to a regex scan with no line
        information (lineno=0 by convention) -- such findings can't be
        attributed to any specific site and must never be surfaced by
        extract_method_security_constraints, at any line range."""
        broken_code = "def action_x(self:\n    if self.env.user.has_group('base.group_system'):\n        pass\n"
        analysis = analyze_python_security_locks(broken_code, "broken.py")

        # Confirms the regex fallback path was actually exercised.
        assert analysis.required_groups == ["base.group_system"]
        assert analysis.required_group_linenos == [0]

        assert extract_method_security_constraints(analysis, lineno=1, end_lineno=1000) == []

    def test_no_findings_returns_empty_list(self):
        analysis = analyze_python_security_locks(
            "class X:\n    def write(self, vals):\n        return super().write(vals)\n", "clean.py"
        )
        assert extract_method_security_constraints(analysis, lineno=1, end_lineno=3) == []


class TestPythonSecurityLockAnalysisLinenoTracking:
    def test_required_group_linenos_index_aligned_with_required_groups(self):
        code = textwrap.dedent("""\
            class X:
                def a(self):
                    if not self.env.user.has_group('grp.one'):
                        raise UserError("no")

                def b(self):
                    if not self.env.user.has_group('grp.two'):
                        raise UserError("no")
        """)
        analysis = analyze_python_security_locks(code, "x.py")
        assert len(analysis.required_group_linenos) == len(analysis.required_groups)
        assert analysis.required_groups == ["grp.one", "grp.two"]
        # has_group() calls land on lines 3 and 7 of the dedented source.
        assert analysis.required_group_linenos == [3, 7]

    def test_exception_linenos_index_aligned_with_exception_messages(self):
        code = textwrap.dedent("""\
            class X:
                def a(self):
                    raise UserError("first")

                def b(self):
                    raise ValidationError("second")
        """)
        analysis = analyze_python_security_locks(code, "x.py")
        assert len(analysis.exception_linenos) == len(analysis.exception_messages)
        assert analysis.exception_linenos == [3, 6]


class TestAnalyzeMethodOverrideChainSurfacesSecurityConstraints:
    """End-to-end: analyze_method_override_chain() must now attach each
    override site's own security constraints, on top of the
    unguarded-super/relational-chain warnings it already reported."""

    def test_two_sites_each_get_their_own_group_requirement(self, tmp_path):
        base_file = tmp_path / "base_mod.py"
        base_file.write_text(textwrap.dedent("""\
            class CustomDeepDocument(models.Model):
                _name = 'custom.deep.document'

                def action_validate(self):
                    if not self.env.user.has_group('base.group_user'):
                        raise UserError("basic access required")
                    return True
        """))
        override_file = tmp_path / "override_mod.py"
        override_file.write_text(textwrap.dedent("""\
            class CustomDeepDocument(models.Model):
                _inherit = 'custom.deep.document'

                def action_validate(self):
                    if not self.env.user.has_group('account.group_account_manager'):
                        raise UserError("manager access required")
                    return super().action_validate()
        """))

        G = nx.DiGraph()
        G.add_node(
            "method:custom.deep.document.action_validate",
            node_type="Method",
            override_sites=[
                {"module": "base_mod", "filepath": str(base_file), "lineno": 4, "end_lineno": 7},
                {"module": "override_mod", "filepath": str(override_file), "lineno": 4, "end_lineno": 7},
            ],
        )

        report = analyze_method_override_chain(G, "custom.deep.document", "action_validate")

        assert "VERROU RATTACHE AU SITE: has_group('base.group_user')" in report
        assert "VERROU RATTACHE AU SITE: has_group('account.group_account_manager')" in report

        # Execution order is the reverse of override_sites (most-dependent
        # module runs first, matching Odoo's real MRO) -- override_mod
        # comes first in the report, base_mod second.
        override_section = report.split("module 'base_mod'")[0]
        base_section = report.split("module 'base_mod'")[1]
        assert "account.group_account_manager" in override_section
        assert "base.group_user" not in override_section
        assert "base.group_user" in base_section
        assert "account.group_account_manager" not in base_section

    def test_site_with_no_security_finding_still_shows_no_structural_risk_note(self, tmp_path):
        """A site with a real security lock but no unguarded-super/
        relational-chain risk must still print the existing "no structural
        risk" note for THOSE two checks -- the new security-constraint
        line is additive, it must not silently replace or hide it."""
        f = tmp_path / "clean_mod.py"
        f.write_text(textwrap.dedent("""\
            class CustomDeepDocument(models.Model):
                _name = 'custom.deep.document'

                def action_validate(self):
                    if not self.env.user.has_group('base.group_user'):
                        raise UserError("basic access required")
                    return True
        """))

        G = nx.DiGraph()
        G.add_node(
            "method:custom.deep.document.action_validate",
            node_type="Method",
            override_sites=[
                {"module": "clean_mod", "filepath": str(f), "lineno": 4, "end_lineno": 7},
            ],
        )

        report = analyze_method_override_chain(G, "custom.deep.document", "action_validate")

        assert "VERROU RATTACHE AU SITE: has_group('base.group_user')" in report
        assert "aucun risque structurel" in report
