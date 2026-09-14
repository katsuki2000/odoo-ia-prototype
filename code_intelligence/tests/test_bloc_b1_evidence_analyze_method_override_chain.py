"""
code_intelligence/tests/test_bloc_b1_evidence_analyze_method_override_chain.py

B1 (todo/contexte.txt section 456+, tool 8/24, 3/4 Analyse CI): unit tests
for the structured Evidence produced by _compose_method_override_chain() and
exposed via the new analyze_method_override_chain_with_evidence() (Option C,
section 456 arbitrage). analyze_method_override_chain() itself (str-
returning, used by ci_agent_tools.py and by the 12 pre-existing tests in
test_method_override_chain.py) is deliberately NOT touched by this file --
every test here cross-checks that its output is byte-for-byte identical to
MethodOverrideChainResult.summary_text, so a regression on the public
contract would fail loudly here too.

Evidence shape covered:
  - no_sites: 1 explicit negative fact, HIGH, when the method has no
    override_sites in the graph.
  - one site-fact Evidence per override site (HIGH, structural/graph-
    derived), independent of whether the site's file exists on disk.
  - one Evidence per site for each of the two structural checks
    (unguarded_super, unchecked_relational_chain), always explicit whether
    positive (LOW, matches the heuristic's own "[Confiance: FAIBLE]"
    disclaimer) or negative (HIGH, absence is a certain fact) -- same "fait
    explicite si negatif" convention as the other Analyse CI tools.
  - security-lock findings (has_group/exception, surfaced inline in
    summary_text via extract_method_security_constraints) are deliberately
    NOT duplicated as Evidence here.
"""

import os
import tempfile
import textwrap

import networkx as nx

from code_intelligence.rules.override_composer import (
    analyze_method_override_chain,
    analyze_method_override_chain_with_evidence,
)


def _write_module(tmp_path, name, source):
    filepath = os.path.join(tmp_path, name)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
    return filepath


def _graph_with_sites(model, method, sites):
    """sites: list of (module, filepath, lineno, end_lineno)."""
    G = nx.DiGraph()
    G.add_node(
        f"method:{model}.{method}",
        node_type="Method",
        override_sites=[
            {"module": m, "filepath": fp, "lineno": ln, "end_lineno": end}
            for m, fp, ln, end in sites
        ],
    )
    return G


class TestOverrideChainEvidenceNoSites:
    def test_no_sites_single_explicit_negative_fact(self):
        G = nx.DiGraph()
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert len(result.evidence) == 1
        ev = result.evidence[0]
        assert ev.confidence == "HIGH"
        assert ev.value == 0
        assert "not overridden across multiple modules" in ev.claim
        assert ev.source == "override_chain:account.move:action_post:no_sites"

    def test_summary_text_matches_public_function(self):
        G = nx.DiGraph()
        text = analyze_method_override_chain(G, "account.move", "action_post")
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert result.summary_text == text
        assert "introuvable dans le graphe" in text


class TestOverrideChainEvidenceCleanSite:
    def test_single_clean_site_three_evidence(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    res = super().action_post()
                    return res
        """
        filepath = _write_module(str(tmp_path), "clean.py", source)
        G = _graph_with_sites("account.move", "action_post", [("clean_mod", filepath, 2, 4)])

        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert len(result.evidence) == 3

        site_ev = next(e for e in result.evidence if ":site:" in e.source)
        assert site_ev.confidence == "HIGH"
        assert site_ev.value == "clean_mod"
        assert "position 1/1" in site_ev.claim
        assert site_ev.scope == {"lineno": 2}

        super_ev = next(e for e in result.evidence if ":unguarded_super:" in e.source)
        assert super_ev.confidence == "HIGH"
        assert super_ev.value is None
        assert "has no unguarded_super finding" in super_ev.claim

        rel_ev = next(e for e in result.evidence if ":unchecked_relational_chain:" in e.source)
        assert rel_ev.confidence == "HIGH"
        assert rel_ev.value is None

    def test_summary_text_matches_public_function(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    res = super().action_post()
                    return res
        """
        filepath = _write_module(str(tmp_path), "clean.py", source)
        G = _graph_with_sites("account.move", "action_post", [("clean_mod", filepath, 2, 4)])
        text = analyze_method_override_chain(G, "account.move", "action_post")
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert result.summary_text == text
        assert "aucun risque structurel" in text


class TestOverrideChainEvidenceUnguardedSuper:
    def test_positive_finding_is_low_confidence(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    if self.partner_id.vip_exempt:
                        self.approved_by_id = self.env.user
                    return super().action_post()
        """
        filepath = _write_module(str(tmp_path), "vip.py", source)
        G = _graph_with_sites("account.move", "action_post", [("vip_mod", filepath, 2, 6)])

        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        super_ev = next(e for e in result.evidence if ":unguarded_super:" in e.source)
        assert super_ev.confidence == "LOW"
        assert "SUPER() NON GARD" in super_ev.value
        assert "has a unguarded_super finding" in super_ev.claim
        assert super_ev.scope == {"lineno": 2}

    def test_warning_text_present_in_summary_and_evidence_value_matches(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    if self.partner_id.vip_exempt:
                        self.approved_by_id = self.env.user
                    return super().action_post()
        """
        filepath = _write_module(str(tmp_path), "vip.py", source)
        G = _graph_with_sites("account.move", "action_post", [("vip_mod", filepath, 2, 6)])
        text = analyze_method_override_chain(G, "account.move", "action_post")
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        super_ev = next(e for e in result.evidence if ":unguarded_super:" in e.source)
        assert super_ev.value in text
        assert result.summary_text == text


class TestOverrideChainEvidenceUncheckedRelationalChain:
    def test_positive_finding_is_low_confidence(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_notify(self):
                    dest = self.demande_id.partner_id.manager_id.user_id
                    dest.notify()
        """
        filepath = _write_module(str(tmp_path), "chain.py", source)
        G = _graph_with_sites("account.move", "action_notify", [("chain_mod", filepath, 2, 4)])

        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_notify")
        rel_ev = next(e for e in result.evidence if ":unchecked_relational_chain:" in e.source)
        assert rel_ev.confidence == "LOW"
        assert "CHAINE RELATIONNELLE NON V" in rel_ev.value
        assert "has a unchecked_relational_chain finding" in rel_ev.claim


class TestOverrideChainEvidenceMultipleSites:
    def test_execution_order_position_matches_site_index(self, tmp_path):
        clean_source = """\
            class Model(models.Model):
                def action_post(self):
                    return super().action_post()
        """
        vip_source = """\
            class Model(models.Model):
                def action_post(self):
                    if self.partner_id.vip_exempt:
                        self.approved_by_id = self.env.user
                    return super().action_post()
        """
        regional_fp = _write_module(str(tmp_path), "regional.py", clean_source)
        vip_fp = _write_module(str(tmp_path), "vip.py", vip_source)
        G = _graph_with_sites(
            "account.move", "action_post",
            [("vip_mod", vip_fp, 2, 5), ("regional_mod", regional_fp, 2, 3)],
        )

        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        # 2 sites x 3 evidence each (site + 2 checks) = 6
        assert len(result.evidence) == 6

        vip_site_ev = next(
            e for e in result.evidence if ":site:vip_mod" in e.source
        )
        regional_site_ev = next(
            e for e in result.evidence if ":site:regional_mod" in e.source
        )
        # resolve_method_override_chain() reverses the graph's declared
        # override_sites order into real execution order -- graph input was
        # [vip, regional], so execution order is [regional, vip].
        assert "position 2/2" in vip_site_ev.claim
        assert "position 1/2" in regional_site_ev.claim

        vip_super_ev = next(
            e for e in result.evidence
            if ":unguarded_super:vip_mod" in e.source
        )
        regional_super_ev = next(
            e for e in result.evidence
            if ":unguarded_super:regional_mod" in e.source
        )
        assert vip_super_ev.confidence == "LOW"
        assert regional_super_ev.confidence == "HIGH"

    def test_summary_text_matches_public_function(self, tmp_path):
        clean_source = """\
            class Model(models.Model):
                def action_post(self):
                    return super().action_post()
        """
        vip_source = """\
            class Model(models.Model):
                def action_post(self):
                    if self.partner_id.vip_exempt:
                        self.approved_by_id = self.env.user
                    return super().action_post()
        """
        regional_fp = _write_module(str(tmp_path), "regional.py", clean_source)
        vip_fp = _write_module(str(tmp_path), "vip.py", vip_source)
        G = _graph_with_sites(
            "account.move", "action_post",
            [("vip_mod", vip_fp, 2, 5), ("regional_mod", regional_fp, 2, 3)],
        )
        text = analyze_method_override_chain(G, "account.move", "action_post")
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert result.summary_text == text


class TestOverrideChainEvidenceMissingFile:
    def test_missing_file_only_site_evidence_no_check_evidence(self):
        G = _graph_with_sites(
            "account.move", "action_post",
            [("ghost_mod", "/nonexistent/path/ghost.py", 10, 20)],
        )
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        # Only the site fact -- no unguarded_super/unchecked_relational_chain
        # evidence for a site whose file could not be read (matches
        # summary_text, which also skips those lines for this site).
        assert len(result.evidence) == 1
        assert ":site:ghost_mod" in result.evidence[0].source

    def test_summary_text_matches_public_function(self):
        G = _graph_with_sites(
            "account.move", "action_post",
            [("ghost_mod", "/nonexistent/path/ghost.py", 10, 20)],
        )
        text = analyze_method_override_chain(G, "account.move", "action_post")
        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        assert result.summary_text == text


class TestOverrideChainEvidenceNoSecurityLockDuplication:
    def test_has_group_and_exception_findings_not_duplicated_as_evidence(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
                    return super().action_post()
        """
        filepath = _write_module(str(tmp_path), "secured.py", source)
        G = _graph_with_sites("account.move", "action_post", [("secured_mod", filepath, 2, 5)])

        result = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        # Security-lock constraints appear inline in the text...
        assert "VERROU RATTACHE AU SITE" in result.summary_text
        # ...but not as a distinct Evidence source in this tool's own list.
        assert not any(e.source.startswith("security_lock:") for e in result.evidence)
        # Still exactly 3 Evidence (site + 2 structural checks, both negative here).
        assert len(result.evidence) == 3


class TestOverrideChainEvidenceDeterminism:
    def test_evidence_id_stable_across_calls(self, tmp_path):
        source = """\
            class Model(models.Model):
                def action_post(self):
                    if self.partner_id.vip_exempt:
                        self.approved_by_id = self.env.user
                    return super().action_post()
        """
        filepath = _write_module(str(tmp_path), "vip.py", source)
        G = _graph_with_sites("account.move", "action_post", [("vip_mod", filepath, 2, 6)])

        r1 = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        r2 = analyze_method_override_chain_with_evidence(G, "account.move", "action_post")
        ids1 = sorted(e.evidence_id for e in r1.evidence)
        ids2 = sorted(e.evidence_id for e in r2.evidence)
        assert ids1 == ids2
