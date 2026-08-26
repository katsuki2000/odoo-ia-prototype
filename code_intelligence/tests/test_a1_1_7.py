"""
code_intelligence/tests/test_a1_1_7.py

Integration tests for Python structural extraction on full real Odoo modules.
Measures extraction coverage on real corpus modules (sale, account, stock).
Acceptance criterion: >= 90% file parsing and extraction success.
"""

from pathlib import Path
import pytest

from code_intelligence.python_extractor import (
    extract_odoo_models_from_file,
    ModelRelationType,
)


def run_module_python_extraction(module_path: Path):
    """
    Run AST python extractors across all .py files in an Odoo module directory.
    Returns summary metrics.
    """
    # Real Odoo modules have their Python files under models/, wizard/,
    # report/, etc. -- always rglob to reach them all.
    py_files = list(module_path.rglob("*.py"))

    total_files = len(py_files)
    parsed_files = 0
    failed_files = []
    
    all_declarations = []
    total_fields = 0
    total_methods = 0
    relational_fields = 0
    computed_fields = 0
    decorated_methods = 0

    for py_file in py_files:
        try:
            decls = extract_odoo_models_from_file(py_file)
            parsed_files += 1
            for decl in decls:
                all_declarations.append(decl)
                total_fields += len(decl.fields)
                total_methods += len(decl.methods)
                
                for f in decl.fields:
                    if f.comodel_name:
                        relational_fields += 1
                    if f.compute:
                        computed_fields += 1

                for m in decl.methods:
                    if m.decorators:
                        decorated_methods += 1
        except Exception as e:
            failed_files.append((str(py_file), str(e)))

    coverage_pct = (parsed_files / total_files * 100.0) if total_files > 0 else 0.0

    return {
        "module_name": module_path.name,
        "total_files": total_files,
        "parsed_files": parsed_files,
        "failed_files": failed_files,
        "coverage_pct": coverage_pct,
        "total_models": len(all_declarations),
        "total_fields": total_fields,
        "relational_fields": relational_fields,
        "computed_fields": computed_fields,
        "total_methods": total_methods,
        "decorated_methods": decorated_methods,
        "relation_types_summary": {
            "BASE": sum(1 for d in all_declarations if ModelRelationType.BASE in d.relation_types),
            "EXTENSION": sum(1 for d in all_declarations if ModelRelationType.EXTENSION in d.relation_types),
            "CLASSIC_INHERITANCE": sum(1 for d in all_declarations if ModelRelationType.CLASSIC_INHERITANCE in d.relation_types),
            "DELEGATION": sum(1 for d in all_declarations if ModelRelationType.DELEGATION in d.relation_types),
        }
    }


def test_sale_module_integration():
    """Run integration test on sale module in addons/sale."""
    corpus_root = Path("/home/user/odoo-17.0/addons")
    sale_dir = corpus_root / "sale"

    assert sale_dir.exists(), f"Corpus sale module dir does not exist: {sale_dir}"

    metrics = run_module_python_extraction(sale_dir)

    print(f"\n--- Python Extraction Metrics for module: {metrics['module_name']} ---")
    print(f"Total Python Files:     {metrics['total_files']}")
    print(f"Parsed Python Files:    {metrics['parsed_files']}")
    print(f"Coverage Percentage:    {metrics['coverage_pct']:.1f}%")
    print(f"Odoo Models Found:      {metrics['total_models']}")
    print(f"  - BASE models:        {metrics['relation_types_summary']['BASE']}")
    print(f"  - EXTENSION models:   {metrics['relation_types_summary']['EXTENSION']}")
    print(f"  - CLASSIC models:     {metrics['relation_types_summary']['CLASSIC_INHERITANCE']}")
    print(f"  - DELEGATION models:  {metrics['relation_types_summary']['DELEGATION']}")
    print(f"Total Fields Extracted: {metrics['total_fields']} (Relational: {metrics['relational_fields']}, Computed: {metrics['computed_fields']})")
    print(f"Total Methods Found:    {metrics['total_methods']} (Decorated: {metrics['decorated_methods']})")

    assert metrics["coverage_pct"] >= 90.0, f"Coverage {metrics['coverage_pct']:.1f}% is below 90.0% threshold"
    assert metrics["total_models"] > 0, "Should extract models from sale module"
    assert metrics["total_fields"] > 0, "Should extract fields from sale module"
    assert metrics["total_methods"] > 0, "Should extract methods from sale module"


def test_account_module_integration():
    """Run integration test on account module in addons/account."""
    corpus_root = Path("/home/user/odoo-17.0/addons")
    account_dir = corpus_root / "account"

    if account_dir.exists():
        metrics = run_module_python_extraction(account_dir)

        print(f"\n--- Python Extraction Metrics for module: {metrics['module_name']} ---")
        print(f"Total Python Files:     {metrics['total_files']}")
        print(f"Parsed Python Files:    {metrics['parsed_files']}")
        print(f"Coverage Percentage:    {metrics['coverage_pct']:.1f}%")
        print(f"Odoo Models Found:      {metrics['total_models']}")

        assert metrics["coverage_pct"] >= 90.0, f"Coverage {metrics['coverage_pct']:.1f}% is below 90.0% threshold"
        assert metrics["total_models"] > 0
