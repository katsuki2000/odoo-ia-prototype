"""
Section 835 -- Option A regression test.

format_security_locks_summary previously attached only ONE file link, at the
block header, for the whole file. Once several files' blocks get concatenated
(assemble_security_lock_blocks, section 824), the LLM synthesizing a final
"Source" citation only had the first header link in view and attributed
every fact in the block to it -- confirmed root cause of section 834
(ACC-Q2 round 2 citing the wrong, unrelated file).

Fix: each has_group() finding and each exception message now carries its own
file:// link built from its own lineno, instead of relying on the block
header link alone.
"""

from code_intelligence.rules.security import PythonSecurityLockAnalysis
from code_intelligence.rules.security_evidence import format_security_locks_summary


def _fake_code(n_lines: int) -> str:
    return "\n".join(f"# line {i}" for i in range(1, n_lines + 1))


def test_gating_group_line_has_own_site_link_not_just_header():
    filepath = "/home/user/odoo-17.0/addons/account/models/account_move.py"
    analysis = PythonSecurityLockAnalysis(
        filepath=filepath,
        required_groups=["account.group_account_manager"],
        required_group_methods=["_check_fiscalyear_lock_date"],
        required_group_linenos=[643],
        required_group_is_gating=[True],
        confidence="high",
    )
    summary = format_security_locks_summary(analysis, _fake_code(700), filepath)

    site_link = f"account_move.py:L643-L643](file://{filepath}#L643-L643)"
    finding_line = next(
        line for line in summary.splitlines() if "_check_fiscalyear_lock_date" in line
    )
    assert site_link in finding_line, (
        "the has_group finding line must carry its own lineno-based link, "
        f"not just the block header link -- got: {finding_line}"
    )


def test_non_gating_group_line_has_own_site_link():
    filepath = "/home/user/odoo-17.0/addons/purchase/models/purchase_order.py"
    analysis = PythonSecurityLockAnalysis(
        filepath=filepath,
        required_groups=["purchase.group_purchase_manager"],
        required_group_methods=["button_confirm"],
        required_group_linenos=[210],
        required_group_is_gating=[False],
        confidence="high",
    )
    summary = format_security_locks_summary(analysis, _fake_code(300), filepath)
    finding_line = next(
        line for line in summary.splitlines() if "button_confirm" in line
    )
    assert f"file://{filepath}#L210" in finding_line


def test_exception_message_line_has_own_site_link():
    filepath = "/home/user/odoo-17.0/addons/stock/models/stock_move.py"
    analysis = PythonSecurityLockAnalysis(
        filepath=filepath,
        exception_messages=["You cannot validate a done move"],
        exception_conditions=[""],
        exception_guard_fields=[""],
        exception_linenos=[512],
        confidence="high",
    )
    summary = format_security_locks_summary(analysis, _fake_code(600), filepath)
    finding_line = next(
        line for line in summary.splitlines() if "You cannot validate a done move" in line
    )
    assert f"file://{filepath}#L512" in finding_line


def test_two_different_findings_get_two_different_site_links():
    """The core of section 834's bug: two facts in the same block must not
    collapse onto a single shared link once concatenated with other blocks."""
    filepath = "/home/user/odoo-17.0/addons/account/models/account_move.py"
    analysis = PythonSecurityLockAnalysis(
        filepath=filepath,
        required_groups=["account.group_account_manager"],
        required_group_methods=["_check_fiscalyear_lock_date"],
        required_group_linenos=[643],
        required_group_is_gating=[True],
        exception_messages=["Fiscal year is locked"],
        exception_conditions=[""],
        exception_guard_fields=[""],
        exception_linenos=[912],
        confidence="high",
    )
    summary = format_security_locks_summary(analysis, _fake_code(1000), filepath)

    group_line = next(l for l in summary.splitlines() if "_check_fiscalyear_lock_date" in l)
    exc_line = next(l for l in summary.splitlines() if "Fiscal year is locked" in l)

    assert "#L643" in group_line
    assert "#L912" in exc_line
    assert "#L643" not in exc_line
    assert "#L912" not in group_line
