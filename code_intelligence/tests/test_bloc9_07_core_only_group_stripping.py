"""
miro-rag/code_intelligence/tests/test_bloc9_07_core_only_group_stripping.py

Regression, module 9/8 (check_bloc9_01_credit_note_cascade_e2e.py, 2026-08-27):
`_grounded_core_only_groups` / `_strip_core_only_group_mentions` (ci_helpers.py)
were stripping `account.group_account_manager` from every answer about the
"normal client / no custom override applies" case, because the group's only
has_group() grounding lives in a core Odoo file (account/models/account_move.py),
never a custom_* module. The heuristic treated "grounded only in core" as
inherently unreliable, but for these questions the core group IS the correct
and only answer -- there is no competing custom-module rule to prefer instead.

Two bugs fixed together here:
  1. Logic bug: _grounded_core_only_groups must only flag a core-only group
     when a COMPETING custom-module group also exists in the same scoped tool
     output (i.e. an override that should take precedence). No custom group
     at all => nothing to strip.
  2. Mechanical bug: the old removal was a clause-level regex
     ('[^.\\n]*<xmlid>[^.\\n]*\\.?') that stopped at the FIRST period in either
     direction -- including periods inside file paths like 'account_move.py'
     or citation line ranges -- producing answers truncated mid-sentence with
     orphaned closing parentheses (confirmed live in the check script output).
     Fixed by removing at whole-paragraph granularity (split on blank lines),
     which cannot cut a sentence or citation in half.

No mocks: exercises the real functions directly against realistic raw
tool-output text, same convention as the rest of the test suite (see
test_bloc9_05_link_guard_backfill.py).

Portability: _block_is_custom_module_file() classifies a file:// link by
resolving it against config.settings.CORE_ADDONS_PATH/CUSTOM_ADDONS_PATH --
both machine-dependent (todo/rules.md: no hardcoded absolute path may drive
test behavior). The module-level _patch_addons_paths autouse fixture pins
both to fixed dummy roots for this file's tests, so the fixtures below
classify deterministically regardless of which machine runs them.
"""

import pytest

from core.graph.graph import (
    _grounded_core_only_groups,
    _strip_core_only_group_mentions,
    _extract_required_groups,
)


@pytest.fixture(autouse=True)
def _patch_addons_paths(monkeypatch):
    """Pin CORE_ADDONS_PATH/CUSTOM_ADDONS_PATH so the fixtures below (fixed
    file:// links under /fake/...) classify deterministically via the real
    config-driven branch of _block_is_custom_module_file(), not its
    machine-dependent fallback heuristic."""
    monkeypatch.setattr("config.settings.CORE_ADDONS_PATH", "/fake/odoo-17.0/addons")
    monkeypatch.setattr("config.settings.CUSTOM_ADDONS_PATH", "/fake/odoo_addons")
    monkeypatch.setattr("config.settings.CORE_FRAMEWORK_ADDONS_PATH", "/fake/odoo-17.0/odoo/addons")


# Core-only grounding: account.group_account_manager's has_group() lives in a
# core Odoo file, no custom_* module is involved at all.
_RAW_CORE_ONLY = """\
Analyse des verrous Python ([account_move.py:L1-L5238](file:///fake/odoo-17.0/addons/account/models/account_move.py#L1-L5238)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): account.group_account_manager
"""

# Same core group, PLUS a competing custom-module group for the same turn --
# the custom override should take precedence in the synthesized answer.
_RAW_CORE_AND_CUSTOM = """\
Analyse des verrous Python ([account_move.py:L1-L5238](file:///fake/odoo-17.0/addons/account/models/account_move.py#L1-L5238)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): account.group_account_manager

Analyse des verrous Python ([account_move.py:L13-L22](file:///fake/odoo_addons/custom_credit_note_approval/models/account_move.py#L13-L22)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): custom_credit_note_approval.group_approval_regional
"""


class TestGroundedCoreOnlyGroups:
    def test_no_flag_when_no_competing_custom_group_exists(self):
        """Regression core: a group grounded ONLY in core Odoo files, with no
        custom-module rule competing for the same question, must NOT be
        flagged -- it is the correct default-behavior answer (e.g. normal/
        non-VIP client, no override applies)."""
        answer = "Le groupe requis est `account.group_account_manager`."
        assert _grounded_core_only_groups(answer, _RAW_CORE_ONLY) == []

    def test_flags_core_group_when_competing_custom_group_present(self):
        """When a custom-module override ALSO exists in this turn's output,
        the core-only group is superseded and should be flagged for removal
        so the custom rule is what the reader sees."""
        answer = (
            "Le groupe `account.group_account_manager` peut valider.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "est requis pour la surcharge régionale."
        )
        flagged = _grounded_core_only_groups(answer, _RAW_CORE_AND_CUSTOM)
        assert flagged == ["account.group_account_manager"]
        # the custom group itself must never be flagged
        assert "custom_credit_note_approval.group_approval_regional" not in flagged

    def test_empty_when_no_groups_grounded_at_all(self):
        assert _grounded_core_only_groups("réponse quelconque", "aucune donnée pertinente") == []

    def test_empty_when_answer_mentions_no_group(self):
        assert _grounded_core_only_groups("Réponse sans groupe cité.", _RAW_CORE_AND_CUSTOM) == []


class TestStripCoreOnlyGroupMentions:
    def test_noop_when_only_core_group_grounded(self):
        """Core regression: this is the exact real-world case (question
        about a normal/non-VIP client) -- must be a strict no-op."""
        answer = (
            "Toutes les personnes ayant les droits d'approbation d'un "
            "account.move peuvent valider cet avoir.\n\n"
            "Le groupe requis est `account.group_account_manager` "
            "(has_group détecté dans account_move.py:L1-L5238)."
        )
        result = _strip_core_only_group_mentions(answer, _RAW_CORE_ONLY)
        assert result == answer
        assert "account.group_account_manager" in result

    def test_removes_only_the_core_only_paragraph_when_custom_competes(self):
        answer = (
            "**Conclusion**\n\n"
            "Le groupe `account.group_account_manager` (requis par write()/"
            "post() pour les modifications) a le droit d'approuver.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "est requis pour la surcharge régionale spécifique à cet avoir."
        )
        result = _strip_core_only_group_mentions(answer, _RAW_CORE_AND_CUSTOM)
        assert "account.group_account_manager" not in result
        assert "custom_credit_note_approval.group_approval_regional" in result
        # the untouched paragraphs must survive completely intact
        assert "**Conclusion**" in result
        assert "est requis pour la surcharge régionale spécifique à cet avoir." in result

    def test_never_leaves_a_truncated_sentence_or_orphaned_parenthesis(self):
        """Mechanical regression: the old clause-level regex stopped at the
        first '.' inside a file path (e.g. 'account_move.py') and produced
        text like 'group_account_manager` pour les modifications) a le '
        droit d'approuver**' -- broken mid-sentence with an orphaned ')'.
        Paragraph-level removal must never do this: any paragraph kept is
        either fully present or fully absent, never partially cut."""
        answer = (
            "**Les groupes requis**\n\n"
            "La méthode `_post()` de `account.py:L1-L5238` et la méthode "
            "`write()` de `account.py:L1-L5238` exigent le groupe "
            "`account.group_account_manager` pour les modifications.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "gouverne la surcharge régionale."
        )
        result = _strip_core_only_group_mentions(answer, _RAW_CORE_AND_CUSTOM)
        # no dangling/orphaned parenthesis introduced by a partial cut
        assert result.count("(") == result.count(")")
        # the surviving paragraph is complete, not a fragment of the removed one
        assert "gouverne la surcharge régionale." in result
        assert "pour les modifications" not in result

    def test_dedup_removes_group_mentioned_in_multiple_paragraphs(self):
        answer = (
            "Premier rappel : `account.group_account_manager` est requis.\n\n"
            "Deuxième rappel, redondant : `account.group_account_manager` "
            "est également requis ici.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "s'applique en plus."
        )
        result = _strip_core_only_group_mentions(answer, _RAW_CORE_AND_CUSTOM)
        assert "account.group_account_manager" not in result
        assert "custom_credit_note_approval.group_approval_regional" in result

    def test_noop_when_no_groups_at_all_in_raw_output(self):
        answer = "Réponse sans aucun groupe cité."
        assert _strip_core_only_group_mentions(answer, "aucune donnée") == answer


# Section 849: several DISTINCT core-only groups grounded at once (ACC-Q1 --
# an ACL write group and an unrelated approval-workflow group), alongside one
# competing custom-module group. These are independent facts, not a 1-for-1
# override, so nothing should be stripped.
_RAW_MULTIPLE_CORE_ONLY = """\
Analyse des verrous Python ([account_move.py:L1-L5238](file:///fake/odoo-17.0/addons/account/models/account_move.py#L1-L5238)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): account.group_account_invoice, base.group_portal

Analyse des verrous Python ([account_move.py:L13-L22](file:///fake/odoo_addons/custom_credit_note_approval/models/account_move.py#L13-L22)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): custom_credit_note_approval.group_approval_regional
"""


class TestMultipleCoreOnlyGroupsSection849:
    def test_grounded_core_only_groups_bails_out_when_several_distinct(self):
        answer = (
            "Le groupe `account.group_account_invoice` porte l'ACL d'écriture. "
            "Le groupe `base.group_portal` est également mentionné. "
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "gouverne la surcharge régionale."
        )
        assert _grounded_core_only_groups(answer, _RAW_MULTIPLE_CORE_ONLY) == []

    def test_strip_is_noop_when_several_distinct_core_only_groups(self):
        answer = (
            "Le groupe `account.group_account_invoice` porte l'ACL d'écriture "
            "(finding indépendant, non concurrent).\n\n"
            "Le groupe `base.group_portal` est également mentionné.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "gouverne la surcharge régionale."
        )
        result = _strip_core_only_group_mentions(answer, _RAW_MULTIPLE_CORE_ONLY)
        assert result == answer
        assert "account.group_account_invoice" in result
        assert "base.group_portal" in result

    def test_single_core_only_still_stripped_when_only_one(self):
        """Regression: the pre-849 clean 1-vs-1 scenario must be untouched --
        this section only adds a bail-out for the MULTIPLE case."""
        result = _strip_core_only_group_mentions(
            "Le groupe `account.group_account_manager` peut valider.\n\n"
            "Le groupe `custom_credit_note_approval.group_approval_regional` "
            "est requis pour la surcharge régionale.",
            _RAW_CORE_AND_CUSTOM,
        )
        assert "account.group_account_manager" not in result
        assert "custom_credit_note_approval.group_approval_regional" in result

    def test_bail_out_uses_full_evidence_not_just_mentioned_subset(self):
        """Section 850 fix-of-a-fix, regression from a real ACC-Q1 replay
        (4/4 still stripped after the first 850 fix): a write-focused answer
        naturally mentions only ONE of the several core-only groups grounded
        in the evidence (account.group_account_invoice), never the other two
        unrelated ones (base.group_portal, base.group_public) -- counting on
        `mentioned` alone undercounts to 1 and fails to bail out. The count
        must be taken over the FULL grounded core-only set, independent of
        what the answer happens to cite."""
        answer = (
            "Le groupe `account.group_account_invoice` porte le droit WRITE "
            "via implied_ids."
        )
        assert _grounded_core_only_groups(answer, _RAW_MULTIPLE_CORE_ONLY) == []
        result = _strip_core_only_group_mentions(answer, _RAW_MULTIPLE_CORE_ONLY)
        assert result == answer
        assert "account.group_account_invoice" in result
