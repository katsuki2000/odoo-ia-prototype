from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (path, old[:70])
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")


p = Path("config/settings.py")
text = p.read_text(encoding="utf-8")
start = text.index("_explicit_core = os.getenv('CORE_ADDONS_PATH')")
end = text.index("RAG_DOCS_PATH = ")
new_block = (
    "CORE_ADDONS_PATH = os.getenv('CORE_ADDONS_PATH') or str(_ROOT.parent / 'odoo-17.0' / 'addons')\n"
    "CUSTOM_ADDONS_PATH = os.getenv('CUSTOM_ADDONS_PATH') or str(_ROOT / 'odoo_addons')\n"
    "ODOO_URL_DEFAULT = 'http://localhost:8069'\n"
    "ODOO_DB_DEFAULT = 'odoo-dev'\n"
)
p.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
edit("config/settings.py", [
    ("from config.odoo_conf import resolve_addon_paths, resolve_database, resolve_odoo_url\n\n", "\n"),
])
edit("README.md", [
    ("| `ODOO_URL` | No | `http://localhost:<http_port of odoo.conf>`, else `http://localhost:8069` | Odoo XML-RPC server URL (overrides odoo.conf) |\n"
     "| `ODOO_DB` | No | `db_name` of odoo.conf when it names a single database, else `odoo-dev` | Odoo database name (overrides odoo.conf) |\n",
     "| `ODOO_URL` | No | `http://localhost:8069` | Odoo XML-RPC server URL |\n"
     "| `ODOO_DB` | No | `odoo-dev` | Odoo database name |\n"),
])
