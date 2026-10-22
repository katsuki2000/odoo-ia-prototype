"""Section 1527 (throwaway): remove retired post-processing stages, their exclusive helpers and their tests.

Usage: .venv/bin/python3 .scratch/remove_dead_1527.py [--apply]
Without --apply: dry run, prints what would be deleted.
"""

import ast
import sys
from pathlib import Path

APPLY = "--apply" in sys.argv

REMOVED_NAMES = {
    "_SENTENCE_SPLIT_RE", "_grounded_core_only_groups", "_strip_core_only_group_mentions",
    "_extract_required_groups_for_amount", "_BLOCK_FILE_LINK_RE", "_block_is_custom_module_file",
    "_restrict_blocks_to_custom_modules", "_backfill_missing_required_groups",
    "_SECURITY_LOCK_MESSAGES_MARKER", "_extract_security_lock_condition_amounts",
    "_backfill_missing_security_lock_amount", "_correct_security_lock_threshold_contradictions",
}

# file -> top-level definitions (functions, classes, constants) to delete
DELETIONS = {
    "code_intelligence/agent/access_guards.py": [
        "_SENTENCE_SPLIT_RE", "_grounded_core_only_groups", "_strip_core_only_group_mentions",
        "_extract_required_groups_for_amount", "_BLOCK_FILE_LINK_RE", "_block_is_custom_module_file",
        "_restrict_blocks_to_custom_modules", "_backfill_missing_required_groups",
    ],
    "code_intelligence/rules/security_locks.py": [
        "_SECURITY_LOCK_MESSAGES_MARKER", "_extract_security_lock_condition_amounts",
        "_backfill_missing_security_lock_amount", "_correct_security_lock_threshold_contradictions",
    ],
    "tests/test_graph.py": [
        "TestBackfillMissingSecurityLockAmount", "TestBackfillSecurityLockAmountNotMaskedByEchoedQuestionAmount",
        "TestExtractRequiredGroupsForAmount", "TestBlockIsCustomModuleFile", "TestRestrictBlocksToCustomModules",
        "TestBackfillMissingRequiredGroupsExcludesCoreOdooNoise", "TestGroundedCoreOnlyGroups",
        "TestStripCoreOnlyGroupMentions", "TestCorrectSecurityLockThresholdContradictions",
        "TestBackfillMissingSecurityLockAmountAmountAware",
    ],
    "tests/test_bloc9_02_backfill_can_view_amount_wiring.py": ["TestBackfillOrderingPreventsUnrelatedSeuilInjection"],
    "code_intelligence/tests/test_t5b_agent_and_storage_failures.py": ["test_block_custom_module_check_logs_an_unresolvable_path"],
    "code_intelligence/tests/test_bug3_residual_truncation_proximity_guard.py": [
        "test_security_lock_amount_rejected_when_adjacent_to_truncation_marker",
        "test_security_lock_amount_extracted_when_far_from_truncation_marker",
        "test_required_group_kept_unconditionally_when_condition_near_truncation",
        "test_required_group_filtered_normally_when_condition_far_from_truncation",
        "test_no_correction_applied_when_condition_line_near_truncation",
    ],
}
# files where only the imports of the removed names are dropped
IMPORT_ONLY = ["core/graph/graph_compat.py"]
WHOLE_FILES = ["code_intelligence/tests/test_bloc9_07_core_only_group_stripping.py"]


def definition_ranges(source, names):
    tree = ast.parse(source)
    lines = source.split("\n")
    found, ranges = set(), []
    for node in tree.body:
        name = None
        start = None
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, start = node.targets[0].id, node.lineno
        if name in names:
            found.add(name)
            while start >= 2 and lines[start - 2].lstrip().startswith("#"):
                start -= 1
            ranges.append((start, node.end_lineno, name))
    missing = set(names) - found
    if missing:
        raise SystemExit(f"definitions introuvables : {sorted(missing)}")
    return ranges


def delete_ranges(source, ranges):
    lines = source.split("\n")
    for start, end, _name in sorted(ranges, reverse=True):
        del lines[start - 1:end]
        index = start - 1
        before = index
        while before > 0 and lines[before - 1].strip() == "":
            before -= 1
        after = index
        while after < len(lines) and lines[after].strip() == "":
            after += 1
        if after >= len(lines):
            lines[before:] = [""]
        else:
            lines[before:after] = ["", ""] if before > 0 else []
    return "\n".join(lines)


def drop_imports(source, names):
    tree = ast.parse(source)
    lines = source.split("\n")
    edits = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and any(alias.name in names for alias in node.names):
            kept = [alias for alias in node.names if alias.name not in names]
            block = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if "#" in block:
                raise SystemExit(f"commentaire dans l'import L{node.lineno} : a traiter a la main")
            if not kept:
                edits.append((node.lineno, node.end_lineno, []))
                continue
            rendered = [f"{a.name} as {a.asname}" if a.asname else a.name for a in kept]
            module = "." * node.level + (node.module or "")
            if node.end_lineno > node.lineno:
                new = [f"from {module} import ("] + [f"    {r}," for r in rendered] + [")"]
            else:
                new = [f"from {module} import {', '.join(rendered)}"]
            edits.append((node.lineno, node.end_lineno, new))
    for start, end, new in sorted(edits, reverse=True):
        lines[start - 1:end] = new
    return "\n".join(lines)


def process(path, names, drop):
    source = Path(path).read_text(encoding="utf-8")
    new = source
    if names:
        ranges = definition_ranges(source, names)
        print(f"-- {path}")
        for start, end, name in sorted(ranges):
            print(f"   supprime {name:60} L{start}-{end} ({end - start + 1} lignes)")
            comment_lines = [l for l in source.split("\n")[start - 1:end] if l.lstrip().startswith("#")]
            attached = source.split("\n")[start - 1].lstrip().startswith("#")
            if attached:
                print(f"      commentaire attenant supprime : {source.split(chr(10))[start - 1].strip()[:100]}")
        new = delete_ranges(new, ranges)
    if drop:
        new = drop_imports(new, REMOVED_NAMES)
    ast.parse(new)
    if APPLY:
        Path(path).write_text(new, encoding="utf-8")


for file, names in DELETIONS.items():
    process(file, names, drop=file.startswith(("tests/", "code_intelligence/tests/")))
for file in IMPORT_ONLY:
    print(f"-- {file} (imports seulement)")
    process(file, [], drop=True)
for file in WHOLE_FILES:
    print(f"-- {file} : fichier supprime ({len(Path(file).read_text(encoding='utf-8').splitlines())} lignes)")
    if APPLY:
        Path(file).unlink()
print("APPLIQUE" if APPLY else "essai a blanc : rien d'ecrit")
