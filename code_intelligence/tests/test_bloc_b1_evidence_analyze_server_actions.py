"""
code_intelligence/tests/test_bloc_b1_evidence_analyze_server_actions.py

B1 (todo/contexte.txt section 450+, tool 6/24, 1/4 Analyse CI): unit tests
for the structured Evidence produced by analyze_server_action_code() via
_build_server_action_evidence(). Complements test_s2_3_server_actions.py
(which covers the pre-existing regex detection behavior, untouched here)
with dedicated coverage of the new `evidence` field: 4 categories always
asserted explicitly (positive or negative), confidence="LOW" on every
fact (deliberate divergence from the 5 Composites CI's confidence="HIGH",
per the arbitrage documented in contexte.txt), empty scope, and
evidence_id determinism.
"""

import textwrap

from code_intelligence.server_actions import analyze_server_action_code


class TestServerActionEvidenceEmptyCode:
    """No code at all -- still 4 explicit negative facts, not an empty list."""

    def test_count_and_confidence(self):
        analysis = analyze_server_action_code("", "action.empty")
        assert len(analysis.evidence) == 4
        assert all(e.confidence == "LOW" for e in analysis.evidence)

    def test_all_four_categories_negative(self):
        analysis = analyze_server_action_code("   ", "action.blank")
        sources = {e.source for e in analysis.evidence}
        assert sources == {
            "server_action:action.blank:sudo",
            "server_action:action.blank:hardcoded_ids",
            "server_action:action.blank:dynamic_dispatch",
            "server_action:action.blank:group_checks",
        }
        for e in analysis.evidence:
            assert e.value is None


class TestServerActionEvidenceCleanCode:
    """Code with no security-relevant pattern -- 4 explicit negative facts,
    same shape as empty code (not the same thing as 'no evidence at all')."""

    def test_clean_code_four_negative_facts(self):
        code = "for rec in records:\n    rec.write({'name': 'test'})"
        analysis = analyze_server_action_code(code, "action.clean")
        assert len(analysis.evidence) == 4
        assert all(e.confidence == "LOW" for e in analysis.evidence)
        sudo_ev = next(e for e in analysis.evidence if e.source == "server_action:action.clean:sudo")
        assert "does not call sudo()" in sudo_ev.claim
        assert sudo_ev.value is None


class TestServerActionEvidenceSudo:
    def test_sudo_positive_with_trigger_condition(self):
        code = (
            "if rec.partner_id.id in [42, 108, 231]:\n"
            "    rec.sudo().action_post()\n"
        )
        analysis = analyze_server_action_code(code, "action.sudo")
        sudo_ev = next(e for e in analysis.evidence if e.source == "server_action:action.sudo:sudo")
        assert "calls sudo()" in sudo_ev.claim
        assert "1 call" in sudo_ev.claim
        assert "conditioned by" in sudo_ev.claim
        assert sudo_ev.value == 1
        assert sudo_ev.confidence == "LOW"

    def test_sudo_call_count_reflects_multiple_calls(self):
        code = "rec.sudo().write({'a': 1})\nrec.sudo().write({'b': 2})\n"
        analysis = analyze_server_action_code(code, "action.multi_sudo")
        sudo_ev = next(e for e in analysis.evidence if e.source == "server_action:action.multi_sudo:sudo")
        assert sudo_ev.value == 2
        assert "2 call" in sudo_ev.claim


class TestServerActionEvidenceHardcodedIds:
    def test_one_evidence_per_hardcoded_list(self):
        code = (
            "GROUPE_A = [1, 2, 3]\n"
            "GROUPE_B = [4, 5]\n"
            "if rec.id in GROUPE_A or rec.id in GROUPE_B:\n"
            "    pass\n"
        )
        analysis = analyze_server_action_code(code, "action.two_lists")
        id_evs = [e for e in analysis.evidence if e.source == "server_action:action.two_lists:hardcoded_ids"]
        assert len(id_evs) == 2
        values = [e.value for e in id_evs]
        assert [1, 2, 3] in values
        assert [4, 5] in values
        assert all(e.confidence == "LOW" for e in id_evs)


class TestServerActionEvidenceDynamicDispatch:
    def test_one_evidence_per_pattern_type(self):
        code = "x = getattr(rec, name)\ny = eval(expr)\n"
        analysis = analyze_server_action_code(code, "action.dispatch")
        dd_evs = [
            e for e in analysis.evidence
            if e.source.startswith("server_action:action.dispatch:dynamic_dispatch:")
        ]
        assert len(dd_evs) == 2
        patterns = {e.value for e in dd_evs}
        assert patterns == {"getattr", "eval"}
        for e in dd_evs:
            assert "not statically classifiable" in e.claim
            assert e.confidence == "LOW"

    def test_no_dispatch_single_negative_fact(self):
        code = "rec.write({'a': 1})\n"
        analysis = analyze_server_action_code(code, "action.no_dispatch")
        dd_evs = [
            e for e in analysis.evidence
            if e.source.startswith("server_action:action.no_dispatch:dynamic_dispatch")
        ]
        assert len(dd_evs) == 1
        assert dd_evs[0].source == "server_action:action.no_dispatch:dynamic_dispatch"
        assert "uses no dynamic dispatch" in dd_evs[0].claim


class TestServerActionEvidenceGroupChecks:
    def test_positive_lists_groups(self):
        code = "if env.user.has_group('base.group_system'):\n    pass\n"
        analysis = analyze_server_action_code(code, "action.group")
        grp_ev = next(e for e in analysis.evidence if e.source == "server_action:action.group:group_checks")
        assert grp_ev.value == ["base.group_system"]
        assert "base.group_system" in grp_ev.claim
        assert grp_ev.confidence == "LOW"

    def test_negative_explicit(self):
        code = "rec.write({'a': 1})\n"
        analysis = analyze_server_action_code(code, "action.no_group")
        grp_ev = next(e for e in analysis.evidence if e.source == "server_action:action.no_group:group_checks")
        assert grp_ev.value is None
        assert "contains no has_group() check" in grp_ev.claim


class TestServerActionEvidenceScopeAndDeterminism:
    def test_scope_always_empty(self):
        code = "rec.sudo().action_post()"
        analysis = analyze_server_action_code(code, "action.scope")
        assert all(e.scope == {} for e in analysis.evidence)

    def test_evidence_id_deterministic(self):
        code = "FOURNISSEURS = [42, 108]\nif rec.partner_id.id in FOURNISSEURS:\n    rec.sudo().action_post()\n"
        a1 = analyze_server_action_code(code, "action.det")
        a2 = analyze_server_action_code(code, "action.det")
        ids1 = sorted(e.evidence_id for e in a1.evidence)
        ids2 = sorted(e.evidence_id for e in a2.evidence)
        assert ids1 == ids2


class TestServerActionEvidenceFullAdversarialQ51:
    """Same code as test_s2_3_server_actions.py's Q5.1 integration test --
    static confidence="low" (untouched) and llm_confidence stay exactly as
    before; only the new evidence field is asserted here."""

    def test_q5_1_evidence_shape(self):
        code = textwrap.dedent("""\
            # Regle non documentee ailleurs
            FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
            for rec in records:
                if rec.move_type == 'in_refund' and rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:
                    rec.sudo().action_post()
        """)
        analysis = analyze_server_action_code(code, "ir_action_server_avoir_fournisseur_privilegie")

        # Static confidence field untouched by this change
        assert analysis.confidence == "low"

        # 4 evidence: sudo(+), hardcoded_ids(+), dynamic_dispatch(-), group_checks(-)
        assert len(analysis.evidence) == 4
        assert all(e.confidence == "LOW" for e in analysis.evidence)

        sudo_ev = next(e for e in analysis.evidence if "sudo" in e.source and "dynamic_dispatch" not in e.source)
        assert "calls sudo()" in sudo_ev.claim
        assert "in_refund" in sudo_ev.claim

        ids_ev = next(e for e in analysis.evidence if "hardcoded_ids" in e.source)
        assert ids_ev.value == [42, 108, 231]

        dd_ev = next(e for e in analysis.evidence if "dynamic_dispatch" in e.source)
        assert "uses no dynamic dispatch" in dd_ev.claim

        grp_ev = next(e for e in analysis.evidence if "group_checks" in e.source)
        assert "contains no has_group() check" in grp_ev.claim
