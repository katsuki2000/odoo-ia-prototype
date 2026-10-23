import re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(".")
BK = ROOT / ".scratch" / "avant_1558"
MAP = {
 "custom_credit_note_approval_regional": "miro_credit_note_approval_regional",
 "custom_credit_note_approval_vip": "miro_credit_note_approval_vip",
 "custom_credit_note_approval": "miro_credit_note_approval",
 "custom_credit_note_visibility_rules": "miro_credit_note_visibility_rules",
 "custom_hr_leave_workflow": "miro_hr_leave_workflow",
 "custom_automation_traps": "miro_automation_traps",
 "custom_expense_reimbursement_indirect": "miro_expense_reimbursement_indirect",
 "custom_expense_risk_base": "acme_expense_risk_base",
 "custom_expense_risk_alert": "acme_expense_risk_alert",
 "custom_expense_risk_score": "acme_expense_risk_score",
 "custom_purchase_request": "ext_purchase_request",
 "custom_asset_loan": "asset_loan",
 "custom_deep_inheritance_security": "deep_inheritance_security",
}
EXCLUDE = ("active_graph.json", "active_graph.json.previous", "ingestion.log", ".pytest_cache", "__pycache__", "todo/", ".venv/", ".scratch/", "captures/", ".git/")
apply = "--apply" in sys.argv

# preconditions
existing = {p.name for p in (ROOT / "odoo_addons").iterdir() if p.is_dir()}
assert set(MAP) <= existing, set(MAP) - existing
known = {p.name for base in ("/home/user/odoo-17.0/addons", "/home/user/odoo-17.0/odoo/addons") for p in Path(base).iterdir()}
known |= {p.parent.name for p in (ROOT / "odoo_addons" / "oca_sample").glob("*/*/__manifest__.py")}
clash = [n for n in MAP.values() if n in known or n in existing]
assert not clash, f"collision de nom: {clash}"
assert len(set(MAP.values())) == len(MAP)

pat = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(sorted(map(re.escape, MAP), key=len, reverse=True)) + r")(?![A-Za-z0-9_])")
files = [l.strip().lstrip("./") if l.startswith("./") else l.strip() for l in open("/tmp/rename_files.txt") if l.strip()]
files = [f for f in files if not any(f == e or f.startswith(e) or ("/" + e) in "/" + f for e in EXCLUDE)]
plan = {}
for f in files:
    p = ROOT / f
    if not p.is_file(): continue
    try: t = p.read_text(encoding="utf-8")
    except UnicodeDecodeError: print("SKIP binaire", f); continue
    n, c = pat.subn(lambda m: MAP[m.group(1)], t)
    if c: plan[f] = (t, n, c)
tot = sum(c for _, _, c in plan.values())
print(f"{len(plan)} fichiers, {tot} remplacements")
for f, (_, _, c) in sorted(plan.items()): print(f"  {c:4d} {f}")
if not apply:
    print("DRY RUN"); sys.exit(0)

BK.mkdir(parents=True, exist_ok=True)
with open(BK / "rename_map.tsv", "w") as fh:
    for o, n in MAP.items(): fh.write(f"{o}\t{n}\n")
for f, (t, n, c) in plan.items():
    dst = BK / f; dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists(): shutil.copy2(ROOT / f, dst)
    (ROOT / f).write_text(n, encoding="utf-8")
for o, n in MAP.items():
    subprocess.run(["git", "mv", f"odoo_addons/{o}", f"odoo_addons/{n}"], check=True)
print("APPLIED:", len(plan), "fichiers modifies,", len(MAP), "dossiers renommes")
