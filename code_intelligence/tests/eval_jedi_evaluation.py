#!/usr/bin/env python3
"""
A1.1.1 — jedi integration test on real Odoo corpus.

Purpose: Evaluate what jedi CAN and CANNOT resolve on Odoo code patterns.
This script systematically tests jedi on:
  1. Standard Python: imports, class definitions, function definitions → EXPECTED: works
  2. Odoo-specific patterns → EXPECTED: mostly fails
     - _inherit / _name resolution
     - self.env['model.name'] → model resolution
     - fields.Many2one('comodel_name') → comodel resolution
     - @api.depends('field_name') → field reference resolution
     - super() calls in _inherit context

Output: Structured report documenting exactly what jedi handles vs. what needs
        the custom AST visitor (tasks A1.1.2 through A1.1.6).
"""

import os
import sys
import json
from pathlib import Path

import jedi

# ── Configuration ─────────────────────────────────────────────────────────────

CORPUS_ROOT = Path("/home/user/odoo-17.0/addons")

# Representative files for each pattern category
TEST_FILES = {
    "sale_order": CORPUS_ROOT / "sale" / "models" / "sale_order.py",
    "res_partner_sale": CORPUS_ROOT / "sale" / "models" / "res_partner.py",
    "account_move": CORPUS_ROOT / "account" / "models" / "account_move.py",
    "stock_picking": CORPUS_ROOT / "stock" / "models" / "stock_picking.py",
    "product_product": CORPUS_ROOT / "sale" / "models" / "product_product.py",
    "sale_order_line": CORPUS_ROOT / "sale" / "models" / "sale_order_line.py",
}


def separator(title: str) -> str:
    return f"\n{'='*80}\n {title}\n{'='*80}\n"


def test_result(test_name: str, success: bool, details: str) -> dict:
    status = " PASS" if success else " FAIL"
    print(f"  {status}  {test_name}")
    if details:
        for line in details.strip().split("\n"):
            print(f"         {line}")
    return {"test": test_name, "success": success, "details": details}


# ── Test 1: Standard Python — imports and definitions ─────────────────────────

def test_standard_python_imports(results: list):
    """Test that jedi can resolve standard Python imports in Odoo files."""
    print(separator("TEST 1: Standard Python imports"))

    source = TEST_FILES["sale_order"].read_text()

    # Test: can jedi find the definition of 'defaultdict' from collections?
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Line 2: from collections import defaultdict
    # Try to get definitions of 'defaultdict' on line 2
    try:
        names = script.get_names(all_scopes=False)
        import_names = [n for n in names if n.type == 'module' or n.description.startswith('module')]
        results.append(test_result(
            "Standard imports detected",
            len(names) > 0,
            f"Found {len(names)} top-level names"
        ))
    except Exception as e:
        results.append(test_result("Standard imports detected", False, str(e)))

    # Test: can jedi resolve 'timedelta' from datetime?
    try:
        # Line 3: from datetime import timedelta
        completions = script.goto(3, 30)  # 'timedelta' position
        results.append(test_result(
            "Resolve 'timedelta' import",
            len(completions) > 0,
            f"Got {len(completions)} definition(s): {[c.full_name for c in completions]}"
        ))
    except Exception as e:
        results.append(test_result("Resolve 'timedelta' import", False, str(e)))


# ── Test 2: Class definition resolution ───────────────────────────────────────

def test_class_definitions(results: list):
    """Test jedi's ability to find class definitions."""
    print(separator("TEST 2: Class definitions"))

    source = TEST_FILES["sale_order"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Find the SaleOrder class definition
    try:
        names = script.get_names(all_scopes=True)
        class_names = [n for n in names if n.type == 'class']
        results.append(test_result(
            "Find class definitions",
            len(class_names) > 0,
            f"Classes found: {[c.name for c in class_names]}"
        ))
    except Exception as e:
        results.append(test_result("Find class definitions", False, str(e)))

    # Find methods within SaleOrder
    try:
        method_names = [n for n in names if n.type == 'function']
        results.append(test_result(
            "Find method definitions",
            len(method_names) > 0,
            f"Found {len(method_names)} methods (showing first 10): {[m.name for m in method_names[:10]]}"
        ))
    except Exception as e:
        results.append(test_result("Find method definitions", False, str(e)))


# ── Test 3: Odoo _inherit resolution ──────────────────────────────────────────

def test_odoo_inherit(results: list):
    """Test if jedi can resolve _inherit references to the parent model."""
    print(separator("TEST 3: Odoo _inherit resolution"))

    # res_partner.py has: _inherit = 'res.partner' (extension pattern, no _name)
    source = TEST_FILES["res_partner_sale"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["res_partner_sale"]))

    # Can jedi resolve _inherit = 'res.partner' to the base res.partner model?
    try:
        # Line 9: _inherit = 'res.partner'
        refs = script.goto(9, 16)  # position of 'res.partner' string
        results.append(test_result(
            "Resolve _inherit = 'res.partner'",
            len(refs) > 0 and any('res.partner' in str(r.full_name or '') for r in refs),
            f"Got {len(refs)} result(s): {[(r.full_name, r.type) for r in refs]}" if refs else "No results — jedi doesn't understand _inherit"
        ))
    except Exception as e:
        results.append(test_result("Resolve _inherit = 'res.partner'", False, str(e)))

    # sale_order.py has: _name = 'sale.order', _inherit = ['portal.mixin', ...]
    source2 = TEST_FILES["sale_order"].read_text()
    script2 = jedi.Script(source2, path=str(TEST_FILES["sale_order"]))

    try:
        # Line 32: _inherit = ['portal.mixin', 'product.catalog.mixin', ...]
        refs2 = script2.goto(32, 20)
        results.append(test_result(
            "Resolve _inherit = ['portal.mixin', ...] (list form)",
            len(refs2) > 0 and any('portal' in str(r.full_name or '') for r in refs2),
            f"Got {len(refs2)} result(s): {[(r.full_name, r.type) for r in refs2]}" if refs2 else "No results — jedi treats this as a plain string/list, not a model ref"
        ))
    except Exception as e:
        results.append(test_result("Resolve _inherit list form", False, str(e)))


# ── Test 4: self.env['model.name'] resolution ────────────────────────────────

def test_self_env(results: list):
    """Test if jedi can resolve self.env['model.name'] to the model class."""
    print(separator("TEST 4: self.env['model.name'] resolution"))

    # res_partner.py line 26: self.env['sale.order']._read_group(...)
    source = TEST_FILES["res_partner_sale"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["res_partner_sale"]))

    try:
        # Line 26: self.env['sale.order']._read_group(
        refs = script.goto(26, 35)  # position on 'sale.order' string
        results.append(test_result(
            "Resolve self.env['sale.order']",
            len(refs) > 0 and any('sale' in str(r.full_name or '') for r in refs),
            f"Got {len(refs)} result(s): {[(r.full_name, r.type) for r in refs]}" if refs else "No results — self.env[] is Odoo metaclass magic, opaque to jedi"
        ))
    except Exception as e:
        results.append(test_result("Resolve self.env['sale.order']", False, str(e)))

    # Try completions after self.env['sale.order'].
    try:
        completions = script.complete(26, 41)  # after '].'
        has_read_group = any(c.name == '_read_group' for c in completions)
        results.append(test_result(
            "Complete self.env['sale.order'].<methods>",
            has_read_group,
            f"Got {len(completions)} completions, _read_group found: {has_read_group}" + 
            (f" (first 5: {[c.name for c in completions[:5]]})" if completions else "")
        ))
    except Exception as e:
        results.append(test_result("Complete self.env[] methods", False, str(e)))


# ── Test 5: fields.Many2one('comodel_name') resolution ───────────────────────

def test_field_comodel(results: list):
    """Test if jedi can resolve the comodel_name in fields.Many2one('res.company')."""
    print(separator("TEST 5: fields.Many2one comodel resolution"))

    source = TEST_FILES["sale_order"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Line 58: comodel_name='res.company',
    try:
        refs = script.goto(58, 25)  # position on 'res.company' string
        results.append(test_result(
            "Resolve fields.Many2one(comodel_name='res.company')",
            len(refs) > 0 and any('company' in str(r.full_name or '').lower() for r in refs),
            f"Got {len(refs)} result(s): {[(r.full_name, r.type) for r in refs]}" if refs else "No results — comodel_name is a string arg, not a Python reference"
        ))
    except Exception as e:
        results.append(test_result("Resolve comodel_name", False, str(e)))

    # Line 206-210: order_line = fields.One2many(comodel_name='sale.order.line', inverse_name='order_id')
    try:
        refs2 = script.goto(207, 25)
        results.append(test_result(
            "Resolve fields.One2many(comodel_name='sale.order.line')",
            len(refs2) > 0 and any('order.line' in str(r.full_name or '').lower() for r in refs2),
            f"Got {len(refs2)} result(s): {[(r.full_name, r.type) for r in refs2]}" if refs2 else "No results — same issue, string-based model reference"
        ))
    except Exception as e:
        results.append(test_result("Resolve One2many comodel", False, str(e)))


# ── Test 6: @api.depends resolution ──────────────────────────────────────────

def test_api_depends(results: list):
    """Test if jedi can understand @api.depends('field_name') references."""
    print(separator("TEST 6: @api.depends field reference resolution"))

    source = TEST_FILES["sale_order"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Find a @api.depends line
    lines = source.split('\n')
    depends_lines = [(i+1, line) for i, line in enumerate(lines) if '@api.depends' in line]

    if depends_lines:
        lineno, line_content = depends_lines[0]
        print(f"  Found @api.depends at line {lineno}: {line_content.strip()}")

        try:
            # Try to resolve the field name string inside @api.depends(...)
            # Find the first quoted string position
            quote_pos = line_content.find("'")
            if quote_pos >= 0:
                refs = script.goto(lineno, quote_pos + 2)  # inside the string
                results.append(test_result(
                    f"Resolve @api.depends field reference (line {lineno})",
                    len(refs) > 0,
                    f"Got {len(refs)} result(s): {[(r.full_name, r.type) for r in refs]}" if refs else "No results — field names in @api.depends are strings, not Python symbols"
                ))
        except Exception as e:
            results.append(test_result("Resolve @api.depends", False, str(e)))
    else:
        results.append(test_result("Resolve @api.depends", False, "No @api.depends found in file"))


# ── Test 7: super() resolution in _inherit context ───────────────────────────

def test_super_in_inherit(results: list):
    """Test if jedi can resolve super() calls when class uses _inherit."""
    print(separator("TEST 7: super() resolution in _inherit context"))

    # res_partner.py line 54: return super()._can_edit_name() and ...
    source = TEST_FILES["res_partner_sale"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["res_partner_sale"]))

    try:
        # Line 54: super()._can_edit_name()
        refs = script.goto(54, 22)  # position on '_can_edit_name'
        has_real_base = any(
            r.full_name and 'res_partner' in str(r.module_path or '')
            for r in refs
        ) if refs else False
        results.append(test_result(
            "Resolve super()._can_edit_name() in _inherit class",
            len(refs) > 0,
            f"Got {len(refs)} result(s): {[(r.full_name, r.type, str(r.module_path)) for r in refs]}" if refs 
            else "No results — super() in _inherit context goes to models.Model, not the actual parent"
        ))
    except Exception as e:
        results.append(test_result("Resolve super() in _inherit", False, str(e)))


# ── Test 8: fields.Selection with external constant ──────────────────────────

def test_fields_selection_external(results: list):
    """Test if jedi can resolve Selection field referencing an external constant."""
    print(separator("TEST 8: fields.Selection with external constant"))

    source = TEST_FILES["sale_order"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Line 68: state = fields.Selection(selection=SALE_ORDER_STATE, ...)
    # SALE_ORDER_STATE is defined at line 22 in the same file
    try:
        refs = script.goto(68, 30)  # position on SALE_ORDER_STATE
        found_definition = any(
            r.line == 22 or 'SALE_ORDER_STATE' in str(r.full_name or '')
            for r in refs
        ) if refs else False
        results.append(test_result(
            "Resolve SALE_ORDER_STATE constant in fields.Selection()",
            found_definition,
            f"Got {len(refs)} result(s): {[(r.full_name, r.line, r.type) for r in refs]}" if refs
            else "No results"
        ))
    except Exception as e:
        results.append(test_result("Resolve Selection constant", False, str(e)))


# ── Test 9: jedi.Script.get_references (find all usages) ─────────────────────

def test_find_references(results: list):
    """Test jedi's find-references capability on Odoo code."""
    print(separator("TEST 9: Find references (all usages of a symbol)"))

    source = TEST_FILES["sale_order"].read_text()
    script = jedi.Script(source, path=str(TEST_FILES["sale_order"]))

    # Find all references to the SaleOrder class
    try:
        # Line 30: class SaleOrder(models.Model):
        refs = script.get_references(30, 10)  # position on 'SaleOrder'
        results.append(test_result(
            "Find all references to 'SaleOrder' class",
            len(refs) > 0,
            f"Got {len(refs)} reference(s) (showing first 5): {[(r.full_name, r.line) for r in refs[:5]]}"
        ))
    except Exception as e:
        results.append(test_result("Find references to class", False, str(e)))


# ── Test 10: Cross-file resolution (jedi project) ────────────────────────────

def test_cross_file_project(results: list):
    """Test if jedi can resolve cross-file references using a Project."""
    print(separator("TEST 10: Cross-file resolution with jedi.Project"))

    try:
        project = jedi.Project(path=str(CORPUS_ROOT))

        # In sale/res_partner.py, try to find definition of SaleOrder used via self.env
        source = TEST_FILES["res_partner_sale"].read_text()
        script = jedi.Script(source, path=str(TEST_FILES["res_partner_sale"]), project=project)

        # Try to find cross-file references
        names = script.get_names(all_scopes=True)
        results.append(test_result(
            "jedi.Project cross-file setup",
            True,
            f"Project created at {CORPUS_ROOT}. Script has {len(names)} names."
        ))

        # Try completions for self.env
        # Line 41: self.env['sale.order'].sudo().search(
        completions = script.complete(41, 17)  # after 'self.env'
        results.append(test_result(
            "Cross-file: complete after self.env",
            len(completions) > 0,
            f"Got {len(completions)} completions: {[c.name for c in completions[:10]]}" if completions
            else "No completions — self.env is Odoo registry magic, invisible to jedi even with Project"
        ))

    except Exception as e:
        results.append(test_result("Cross-file resolution", False, str(e)))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print(" A1.1.1 — jedi Integration Test on Odoo Corpus")
    print(f" jedi version: {jedi.__version__}")
    print(f" Corpus root: {CORPUS_ROOT}")
    print("=" * 80)

    # Verify corpus exists
    for name, path in TEST_FILES.items():
        if not path.exists():
            print(f"  ⚠ Missing: {name} → {path}")
        else:
            print(f"   Found: {name} ({path.stat().st_size:,} bytes)")

    results = []

    # Run all test suites
    test_standard_python_imports(results)
    test_class_definitions(results)
    test_odoo_inherit(results)
    test_self_env(results)
    test_field_comodel(results)
    test_api_depends(results)
    test_super_in_inherit(results)
    test_fields_selection_external(results)
    test_find_references(results)
    test_cross_file_project(results)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(separator("SUMMARY"))

    passed = sum(1 for r in results if r["success"])
    failed = sum(1 for r in results if not r["success"])
    total = len(results)

    print(f"  Total tests: {total}")
    print(f"  Passed:      {passed}")
    print(f"  Failed:      {failed}")
    print()

    # Categorize: what jedi handles vs what needs AST visitor
    print("  ── What jedi handles (standard Python): ──")
    for r in results:
        if r["success"]:
            print(f"      {r['test']}")

    print()
    print("  ── What jedi CANNOT handle (needs custom AST visitor): ──")
    for r in results:
        if not r["success"]:
            print(f"      {r['test']}")

    # Save structured results
    output_path = Path(__file__).parent / "jedi_evaluation_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "jedi_version": jedi.__version__,
            "corpus_root": str(CORPUS_ROOT),
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
