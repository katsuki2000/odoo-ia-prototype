import shutil, sys
from pathlib import Path

ROOT = Path(".")
BACKUP = ROOT / ".scratch" / "avant_1548_suite"

EDITS = {
 "code_intelligence/agent/rpc_client.py": [
  ("across machines (todo/rules.md).", "across machines."),
 ],
 "code_intelligence/rules/navigation.py": [
  ('"comment faire pour X"\n    (Bloc 17, Etage 1): which menu', '"comment faire pour X":\n    which menu'),
  ('(the "aucun chemin UI" verdict from todo/bloc17_jour1_perimetre.md --', '(the "aucun chemin UI" verdict --'),
 ],
 "code_intelligence/rules/security.py": [
  ("from the analysis (contexte 816).", "from the analysis."),
 ],
 "code_intelligence/semgrep_rules/raw_sql_constraints.yaml": [
  ("any @api.constrains method -- see todo/contexte.txt section 811/812.", "any @api.constrains method."),
 ],
 "core/evaluation/expected_models.py": [
  ("d'une resolution (journal D-14).", "d'une resolution."),
 ],
 "core/llm/server_fingerprint.py": [
  ("a l'autre (journal 1467) ; une", "a l'autre ; une"),
 ],
 "scripts/check_bloc9_02_credit_note_visibility_e2e.py": [
  ("Bug 1 fix, todo/contexte.txt section 490) as", "Bug 1 fix) as"),
  ("# Bug B2(a),  section 99 (2026-08-21): both", "# Bug B2(a) (2026-08-21): both"),
  ("synthesis bug (see section 99's full\n# Kleene recomputation) -- it is", "synthesis bug -- it is"),
  ("the full rationale,  section 78). Generalized", "the full rationale). Generalized"),
 ],
 "scripts/check_bloc9_04_purchase_request_e2e.py": [
  ("# gap (2026-08-26, section 183/186): the previous", "# gap (2026-08-26): the previous"),
  ("the exact wrong answer diagnosed in section 178 (", "the exact wrong answer previously observed ("),
  ("the full rationale,  section 78). Generalized", "the full rationale). Generalized"),
 ],
 "scripts/check_bloc9_05_asset_loan_e2e.py": [
  ("(not the J36 real-core-Odoo-dependency gap,", "(not the real-core-Odoo-dependency gap,"),
  ("the full rationale,  section 78). Generalized", "the full rationale). Generalized"),
 ],
 "scripts/check_bloc9_06_automation_traps_e2e.py": [
  ("the full rationale,  section 78). Generalized", "the full rationale). Generalized"),
 ],
 "scripts/run_adversarial_benchmark.py": [
  ("fragile/slow (cf. todo/contexte.txt Section 714) and re-running", "fragile/slow, and re-running"),
  ("lifecycle (Section 704,\n            # todo/contexte.txt) -- this script", "lifecycle -- this script"),
  ("# Diagnostic instrumentation (Section 706, todo/contexte.txt) -- scoped to", "# Diagnostic instrumentation -- scoped to"),
  ("truncation reported in\n    # Section 695 -- confirms or refutes", "truncation -- confirms or refutes"),
  ("ne rejoue que ces questions (todo/contexte.txt Section 715) ; sans", "ne rejoue que ces questions ; sans"),
 ],
 "scripts/run_scalability_test.py": [
  ("Recalibrated (todo/contexte.txt section 669/670) after 2 permanent, unrelated\n"
   "decisions invalidated the original ~2500-chunk/code-duplication design:\n"
   "- Section 363: fake_data/ removed, replaced by document_rag/documents/.\n"
   "- Section 347-353: RAG scope permanently restricted to documents only, code\n"
   "  ingestion removed (SUPPORTED_EXTENSIONS in incremental.py no longer includes\n"
   "  .py) -- duplicating Odoo addon code no longer contributes any chunk, so it\n"
   "  is no longer duplicated here.\n",
   "Calibrated for the documents-only RAG scope: fake_data/ was replaced by\n"
   "document_rag/documents/, and code ingestion was removed (SUPPORTED_EXTENSIONS in\n"
   "incremental.py no longer includes .py), so duplicating Odoo addon code no longer\n"
   "contributes any chunk and is not duplicated here.\n"),
 ],
}

apply = "--apply" in sys.argv
problems = []
plan = {}
for rel, edits in EDITS.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    new = text
    for old, repl in edits:
        n = new.count(old)
        if n == 0:
            problems.append(f"ABSENT  {rel}: {old[:60]!r}")
        elif rel.endswith("check_bloc9_02_credit_note_visibility_e2e.py") and "section 78" in old:
            new = new.replace(old, repl)
        elif n > 1:
            problems.append(f"MULTI({n}) {rel}: {old[:60]!r}")
        else:
            new = new.replace(old, repl)
    plan[rel] = (text, new)

for p in problems:
    print(p)
if problems:
    print("ABORT: nothing written")
    sys.exit(1)

for rel, (old, new) in plan.items():
    changed = old != new
    print(("CHANGE " if changed else "same   ") + rel)
    if apply and changed:
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
        (ROOT / rel).write_text(new, encoding="utf-8")
print("APPLIED" if apply else "DRY RUN (add --apply)")
