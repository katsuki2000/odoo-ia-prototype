import shutil
from pathlib import Path
R = Path("."); BK = R/".scratch"/"avant_1558"
E = {
"README.md": [
 ("All custom modules (`miro_ai` and the 14 `custom_*` business modules) are bundled inside this repository in `odoo_addons/`.",
  "All custom modules (`miro_ai`, `miro_ai_discuss`, the business modules and the bundled OCA modules) are bundled inside this repository in `odoo_addons/`, one folder per module. Business modules deliberately use different name prefixes (`miro_`, `acme_`, `ext_` or none): nothing in the code depends on a prefix."),
 ("# Install all custom business modules\n\n",
  "# Install maintenance, the business modules and the OCA modules that have all their dependencies here\n"
  "# (list: scripts/odoo_modules_to_install.txt ; external Python packages first:\n"
  "#  pip install cryptography mako odoo_test_helper odoorpc openupgradelib 'paramiko<4.0.0' pygount pysftp 'sentry_sdk<=1.9.0')\n"
  "python3 odoo-bin -c odoo.conf -d odoo-dev -i \"$(paste -sd, ~/odoo-ia-prototype/scripts/odoo_modules_to_install.txt)\" --stop-after-init\n```\n\n"),
],
"tests/custom_b9_question_bank.json": [("(odoo_addons/custom_*)", "(odoo_addons/)")],
"code_intelligence/tests/test_j36_sprint_d_expense_risk_replay.py": [("sur le corpus custom_expense_risk_* :", "sur le corpus acme_expense_risk_* :"), ("from the 3 custom_expense_risk_* modules", "from the 3 acme_expense_risk_* modules")],
"code_intelligence/tests/test_f08_j36_graph_dependency_loading.py": [
 ("the 3 custom_expense_risk_* modules", "the 3 acme_expense_risk_* modules"),
 ("rag/graph.py::get_code_intelligence_graph(): custom_* modules that", "rag/graph.py::get_code_intelligence_graph(): custom modules that"),
 ("    custom_* module. Before the fix", "    custom module. Before the fix"),
 ("not invented by any custom_* module.", "not invented by any custom module."),
],
"code_intelligence/tests/test_mixed_corpus_load_order.py": [("only ever loaded the three custom_* modules", "only ever loaded the three custom modules")],
"scripts/check_native_odoo_out_of_scope.py": [
 ("that no custom_* module touches", "that no custom module touches"),
 ("picked after checking every custom_*", "picked after checking every custom"),
 ("regardless of any custom_* dependency", "regardless of any custom dependency"),
 ("miro_ai, any custom_* module, or a custom_* module's direct dependency", "miro_ai, any custom module, or a custom module's direct dependency"),
 ("see every custom_*/__manifest__.py depends list", "see every custom module's __manifest__.py depends list"),
],
"scripts/check_bloc9_05_asset_loan_e2e.py": [
 ("itself already a `custom_*`-prefixed module the", "itself already a custom module the"),
 ("non-`custom_*` deps like", "non-custom deps like"),
],
"scripts/check_bloc9_06_automation_traps_e2e.py": [("not a custom_* module)", "not a custom module)")],
"scripts/run_adversarial_benchmark.py": [
 ("ce graphe de 9 modules custom_* avec", "ce graphe de 9 modules custom avec"),
 ("# + custom_*, ~3775", "# + modules custom, ~3775"),
],
"scripts/extract_modules.py": [
 ("--prefix custom_\n", "--prefix miro_\n"),
 ("(e.g. 'custom_')", "(e.g. 'miro_')"),
],
}
bad = []; plan = {}
for rel, edits in E.items():
    t = (R/rel).read_text(encoding="utf-8"); n = t
    for old, new in edits:
        c = n.count(old)
        if c != 1: bad.append(f"{c}x {rel}: {old[:50]!r}")
        else: n = n.replace(old, new)
    plan[rel] = (t, n)
for b in bad: print("PROBLEM", b)
if bad: raise SystemExit("ABORT")
for rel, (t, n) in plan.items():
    d = BK/rel; d.parent.mkdir(parents=True, exist_ok=True)
    if not d.exists(): shutil.copy2(R/rel, d)
    (R/rel).write_text(n, encoding="utf-8"); print("OK", rel)
