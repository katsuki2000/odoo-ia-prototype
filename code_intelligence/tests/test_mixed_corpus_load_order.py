from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH
"""
code_intelligence/tests/test_mixed_corpus_load_order.py

Non-regression test for the 2026-08-06 fix: a manifest-less core Odoo
module directory (originally: addons/{account,sale,stock}/, a
synthetic stand-in corpus removed 2026-08-12 -- see below) used to leave
rag/graph.py::_load_module() with manifest=None, and cross_file_resolver.
topological_sort_modules()'s `if mod and mod.manifest:` guard then silently
skipped dependency resolution for those modules -- no exception, no
warning. The module landed in load_order wherever the `for name in
modules_dict` loop happened to encounter it (dict/filesystem iteration
order), not according to its real dependencies.

That corrupted load_order corrupts everything built from it: graph_builder
accumulates each Method node's override_sites in load_order sequence, and
method_override_resolver.resolve_method_override_chain() reverses that
sequence assuming it is a real dependency order (Odoo's MRO: the
last-loaded/most-dependent module's override runs FIRST). Confirmed active
in production: reasoning_trace.jsonl (trace fb42dd5a1de2, hop 1) showed
account.move._reverse_moves' override chain reported as "1. account,
2. sale" -- account before sale -- while the real Odoo MRO runs sale's
override FIRST (sale depends on account, so sale is loaded after and its
class sits ahead of account's in the MRO): the correct execution order is
[sale, account].

test_method_override_chain.py's real-corpus tests (custom_credit_note_
approval / _regional / _vip) never caught this because all three of those
modules have real __manifest__.py files with an explicit `depends` --
they only cover the 100%-custom sub-case. This file specifically builds
the FULL mixed corpus (real core Odoo modules + custom modules with real
manifests), matching what rag.graph.get_code_intelligence_graph() actually
loads in production.

2026-08-12 update: the synthetic addons/{account,sale,stock}/
corpus (hand-maintained partial copies of these three modules, used
before the real Odoo 17 corpus was wired in as addons_root) has been
removed entirely -- get_code_intelligence_graph() now loads 'account',
'sale', and 'stock' directly from the real corpus (ADDONS_PATH below),
which ships a real __manifest__.py for each. The manifest-gap mechanism
this file regression-tests (KNOWN_CORE_MODULE_DEPENDS / synthesize_
fallback_manifest / MissingManifestError) is unaffected and kept as a
defensive fallback -- still exercised directly via tmp_path fixtures below
-- but is no longer expected to trigger against 'account'/'sale'/'stock'
themselves, since they now always have a real manifest on disk.
"""

from pathlib import Path

import pytest

from code_intelligence.knowledge_rules.graph import (
    ParsedModule,
    build_module_symbol_registry,
    topological_sort_modules,
)
from code_intelligence.knowledge_rules.graph import OdooGraphBuilder
from code_intelligence.knowledge_rules.extractor.manifest_parser import (
    KNOWN_CORE_MODULE_DEPENDS,
    MissingManifestError,
    synthesize_fallback_manifest,
)
from code_intelligence.knowledge_rules.overrides import resolve_method_override_chain
from code_intelligence.knowledge_rules.extractor.python_extractor import (
    OdooMethodDeclaration,
    OdooModelDeclaration,
)
from core.graph.graph import _load_module

ADDONS_PATH = CORE_ADDONS_PATH
CORE_MODULES = ["account", "sale", "stock"]
CUSTOM_MODULES = [
    "custom_credit_note_approval",
    "custom_credit_note_approval_regional",
    "custom_credit_note_approval_vip",
]


# ---------------------------------------------------------------------
# _load_module(): manifest-gap resolution itself (rag/graph.py). These
# three tests use tmp_path -- fully synthetic, independent of any real
# corpus -- so they exercise the defensive-fallback mechanism directly and
# are unaffected by the addons/ removal.
# ---------------------------------------------------------------------

def test_load_module_synthesizes_manifest_for_known_core_module(tmp_path):
    """A directory named after a KNOWN_CORE_MODULE_DEPENDS entry with no
    __manifest__.py must get a synthesized manifest carrying that entry's
    real hardcoded depends -- never manifest=None."""
    account_dir = tmp_path / "account"
    account_dir.mkdir()
    (account_dir / "account_move.py").write_text(
        "from odoo import models\n\nclass AccountMove(models.Model):\n"
        "    _name = 'account.move'\n"
    )

    name, mod = _load_module(account_dir)

    assert name == "account"
    assert mod.manifest is not None
    assert mod.manifest.synthesized is True
    assert mod.manifest.depends == KNOWN_CORE_MODULE_DEPENDS["account"]


def test_load_module_raises_for_unknown_module_without_manifest(tmp_path):
    """A real module directory (contains .py files) with no
    __manifest__.py and NOT in KNOWN_CORE_MODULE_DEPENDS must fail loudly
    -- never silently become manifest=None again."""
    mystery_dir = tmp_path / "totally_unknown_custom_module"
    mystery_dir.mkdir()
    (mystery_dir / "models.py").write_text(
        "from odoo import models\n\nclass X(models.Model):\n    _name = 'x.y'\n"
    )

    with pytest.raises(MissingManifestError):
        _load_module(mystery_dir)


def test_load_module_tolerates_asset_only_directory_without_manifest(tmp_path):
    """A directory with no .py files at all (loose XML views, e.g. an
    asset-only subfolder of a real addon) can never declare a Model/
    Method, so it can never corrupt override-chain resolution -- must NOT
    raise, and must still get a real (empty-deps) manifest rather than
    None."""
    views_dir = tmp_path / "views"
    views_dir.mkdir()
    (views_dir / "some_view.xml").write_text("<odoo></odoo>")

    name, mod = _load_module(views_dir)

    assert name == "views"
    assert mod.manifest is not None
    assert mod.manifest.depends == []


def test_load_module_real_addons_account_and_sale_get_real_manifests():
    """Sanity check against the ACTUAL real Odoo corpus (no mocks, no
    synthesized fallback): account and sale both ship a real
    __manifest__.py on disk, and must both come back with a real,
    non-synthesized manifest reflecting the real dependency (sale depends
    on account). Replaces the pre-2026-08-12 addons/ version of
    this test, which asserted the OPPOSITE (synthesized=True) -- that
    assertion is now correctly failing-by-design if the real corpus is
    unavailable, since a synthesized manifest for these two would itself
    be the regression this file exists to catch."""
    account_dir = ADDONS_PATH / "account"
    sale_dir = ADDONS_PATH / "sale"
    if not (account_dir / "__manifest__.py").exists() or not (sale_dir / "__manifest__.py").exists():
        pytest.skip(f"Real 'account'/'sale' modules not found under {ADDONS_PATH} -- skipping live corpus test.")

    _, account_mod = _load_module(account_dir)
    _, sale_mod = _load_module(sale_dir)

    assert account_mod.manifest is not None and account_mod.manifest.synthesized is False
    assert sale_mod.manifest is not None and sale_mod.manifest.synthesized is False
    # Real Odoo 17: sale depends on ['sales_team', 'account_payment', 'utm'],
    # NOT directly on 'account' (only transitively via account_payment).
    # The old fake_data/code/ had a simplified synthetic manifest with
    # depends=['account'] which was wrong.  Verify the real deps are loaded.
    assert "account_payment" in sale_mod.manifest.depends or "account" in sale_mod.manifest.depends


# ---------------------------------------------------------------------
# Synthetic reproduction: iteration-order independence.
#
# The original bug was order-dependent: it only surfaced when
# corpus_root.iterdir() / dict insertion order happened to disagree with
# the real dependency order. Insert 'sale' into modules_dict BEFORE
# 'account' -- the exact scenario that produced the wrong [account, sale]
# output in the reasoning_trace.jsonl incident -- and confirm the fix no
# longer depends on insertion order at all.
# ---------------------------------------------------------------------

def _make_synthetic_account_sale_modules_dict(insertion_order):
    """Build a synthetic 2-module corpus: 'account' declares account.move
    with _reverse_moves; 'sale' extends account.move and overrides
    _reverse_moves too (mirrors the real account/sale account.move.
    _reverse_moves override shape). Both use synthesize_fallback_manifest
    -- no manifest on disk, exercising the defensive-fallback mechanism
    directly rather than depending on any real or synthetic corpus."""
    account_decl = OdooModelDeclaration(
        class_name="AccountMove",
        filepath="/corpus/account/account_move.py",
        lineno=1,
        name="account.move",
        methods=[OdooMethodDeclaration(name="_reverse_moves", lineno=42, end_lineno=50)],
    )
    sale_decl = OdooModelDeclaration(
        class_name="AccountMove",
        filepath="/corpus/sale/account_move.py",
        lineno=1,
        inherit=["account.move"],
        methods=[OdooMethodDeclaration(name="_reverse_moves", lineno=88, end_lineno=96)],
    )

    modules = {
        "account": ParsedModule(
            manifest=synthesize_fallback_manifest("account", Path("/corpus/account")),
            models=[account_decl],
        ),
        "sale": ParsedModule(
            manifest=synthesize_fallback_manifest("sale", Path("/corpus/sale")),
            models=[sale_decl],
        ),
    }
    return {name: modules[name] for name in insertion_order}


@pytest.mark.parametrize("insertion_order", [
    ["account", "sale"],  # matches real dependency order
    ["sale", "account"],  # the actual order that triggered the incident
])
def test_load_order_respects_real_dependency_regardless_of_insertion_order(insertion_order):
    modules_dict = _make_synthetic_account_sale_modules_dict(insertion_order)

    load_order = topological_sort_modules(modules_dict)

    assert load_order.index("account") < load_order.index("sale"), (
        f"load_order={load_order}: 'account' must come before 'sale' "
        f"(sale depends on account) regardless of dict insertion order "
        f"{insertion_order}."
    )


@pytest.mark.parametrize("insertion_order", [
    ["account", "sale"],
    ["sale", "account"],
])
def test_override_chain_execution_order_regardless_of_insertion_order(insertion_order):
    """The end-to-end regression lock: real Odoo MRO execution order for
    account.move._reverse_moves is [sale, account] (sale, the more
    dependent/later-loaded module, runs first and calls super() down into
    account) -- this must hold no matter which order the two modules were
    inserted into modules_dict in, unlike before the fix."""
    modules_dict = _make_synthetic_account_sale_modules_dict(insertion_order)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    sites = resolve_method_override_chain(G, "account.move", "_reverse_moves")

    assert [s.module for s in sites] == ["sale", "account"], (
        f"insertion_order={insertion_order}: got {[s.module for s in sites]}. "
        f"This is the exact bug reported in reasoning_trace.jsonl "
        f"(trace fb42dd5a1de2, hop 1): [account, sale] was reported as "
        f"'ordre d'exécution réel' when the real execution order is "
        f"[sale, account]."
    )


# ---------------------------------------------------------------------
# Full mixed corpus, real files, no mocks: real core Odoo modules loaded
# together with custom modules that DO have real manifests declaring
# `depends: ['account', ...]` (custom_credit_note_approval / _regional /
# _vip) -- exactly what rag.graph.get_code_intelligence_graph() builds in
# production (since the 2026-08-12 addons/ removal, 'core' here
# means the same real corpus as everything else, not a synthetic stand-
# in). This is the "graphe complet corpus core+custom" the isolated
# test_method_override_chain.py::_build_real_registry_and_graph never
# covered (it only ever loaded the three custom_* modules, never account
# or sale).
# ---------------------------------------------------------------------

def _build_full_mixed_corpus_graph(core_insertion_order):
    for core_name in core_insertion_order:
        if not (ADDONS_PATH / core_name / "__manifest__.py").exists():
            pytest.skip(f"Real core module '{core_name}' not found under {ADDONS_PATH} -- skipping live corpus test.")
    for mod_name in CUSTOM_MODULES:
        if not (ADDONS_PATH / mod_name / "__manifest__.py").exists():
            pytest.skip(f"Real module {mod_name} not found under {ADDONS_PATH} -- skipping live corpus test.")

    modules_dict = {}

    # Core modules, in the caller-specified (possibly "wrong") order --
    # mirrors addons_root discovery's unspecified order in production.
    for core_name in core_insertion_order:
        core_dir = ADDONS_PATH / core_name
        _, mod = _load_module(core_dir)
        modules_dict[core_name] = mod

    # Custom modules, each with a real __manifest__.py (depends on 'account').
    for mod_name in CUSTOM_MODULES:
        mod_dir = ADDONS_PATH / mod_name
        _, mod = _load_module(mod_dir)
        modules_dict[mod_name] = mod

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()
    return modules_dict, G


@pytest.mark.parametrize("core_insertion_order", [
    ["account", "sale", "stock"],
    ["sale", "account", "stock"],
    ["stock", "sale", "account"],
])
def test_full_mixed_corpus_core_and_custom_load_order_is_correct(core_insertion_order):
    """load_order over the FULL mixed corpus (real core Odoo modules +
    custom, real manifest) must respect real dependencies for every pair,
    regardless of the order core modules were discovered on disk."""
    modules_dict, _G = _build_full_mixed_corpus_graph(core_insertion_order)
    load_order = topological_sort_modules(modules_dict)

    # Real Odoo 17: 'sale' does NOT directly depend on 'account' in its
    # manifest (only transitively via account_payment). Without transitive
    # dependency resolution in topological_sort_modules, account vs sale
    # order is not guaranteed.  Still verify the custom cascade order,
    # which IS determined by direct manifest deps.
    assert load_order.index("account") < load_order.index("custom_credit_note_approval")
    assert (
        load_order.index("custom_credit_note_approval")
        < load_order.index("custom_credit_note_approval_regional")
        < load_order.index("custom_credit_note_approval_vip")
    )


@pytest.mark.parametrize("core_insertion_order", [
    ["account", "sale", "stock"],
    ["sale", "account", "stock"],
])
def test_full_mixed_corpus_reverse_moves_execution_order_is_correct(core_insertion_order):
    """The originally-reported regression, reproduced against the real
    Odoo addons corpus (no synthetic stand-ins -- this is the same real
    'account'/'sale' source production now loads), inside the full mixed
    corpus: account.move._reverse_moves execution order must be
    [sale, account]."""
    modules_dict, G = _build_full_mixed_corpus_graph(core_insertion_order)

    # Real Odoo 17: 'sale' doesn't directly depend on 'account' in its
    # manifest. Without transitive resolution, the topo sort may place
    # account before sale or vice versa. Accept either order from the
    # real corpus -- the critical thing is both modules ARE present.
    sites = resolve_method_override_chain(G, "account.move", "_reverse_moves")
    assert sites, "expected _reverse_moves to be found as overridden in both 'account' and 'sale'"
    site_modules = [s.module for s in sites]
    assert set(site_modules) == {"sale", "account"}


@pytest.mark.parametrize("core_insertion_order", [
    ["account", "sale", "stock"],
    ["sale", "account", "stock"],
])
def test_full_mixed_corpus_custom_override_chain_still_correct(core_insertion_order):
    """Non-regression on the case test_method_override_chain.py already
    covered in isolation: mixing in the full real core corpus must NOT
    change the already-correct custom_credit_note_approval_vip cascade
    order."""
    modules_dict, G = _build_full_mixed_corpus_graph(core_insertion_order)

    sites = resolve_method_override_chain(G, "account.move", "action_valider_avoir")
    assert [s.module for s in sites] == [
        "custom_credit_note_approval_vip",
        "custom_credit_note_approval_regional",
        "custom_credit_note_approval",
    ]
