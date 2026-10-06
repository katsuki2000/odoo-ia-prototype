import pytest


def skip_unless_modules_installed(client, admin_uid, modules) -> None:
    missing = [
        module
        for module in modules
        if not client.execute_kw(
            admin_uid,
            "ir.module.module",
            "search",
            [[("name", "=", module), ("state", "=", "installed")]],
            {"limit": 1},
        )
    ]
    if missing:
        pytest.skip(f"Required Odoo modules are not installed: {missing}")
