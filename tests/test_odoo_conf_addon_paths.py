"""Section 1249: addon paths deduced from odoo.conf (structure-based, env override first)."""
from pathlib import Path

from config.odoo_conf import (
    classify_addon_roots,
    read_addons_path,
    resolve_addon_paths,
)


def _odoo_tree(tmp_path: Path):
    root = tmp_path / "odoo-17.0"
    (root / "odoo" / "addons" / "base").mkdir(parents=True)
    (root / "odoo" / "addons" / "base" / "__manifest__.py").write_text("{}")
    (root / "odoo-bin").write_text("")
    (root / "addons" / "sale").mkdir(parents=True)
    (root / "custom_addons").mkdir()
    project = tmp_path / "project"
    (project / "odoo_addons").mkdir(parents=True)
    return root, project


def _conf(tmp_path: Path, addons_path: str) -> Path:
    conf = tmp_path / "odoo.conf"
    conf.write_text(f"[options]\naddons_path = {addons_path}\ndb_name = x\n")
    return conf


def test_read_addons_path_keeps_order_and_ignores_blanks(tmp_path):
    conf = _conf(tmp_path, f"{tmp_path}/a, {tmp_path}/b,\n  {tmp_path}/a")
    assert read_addons_path(conf) == [(tmp_path / "a").resolve(), (tmp_path / "b").resolve()]
    assert read_addons_path(tmp_path / "missing.conf") == []
    assert read_addons_path(None) == []


def test_structural_classification_without_folder_names(tmp_path):
    root, project = _odoo_tree(tmp_path)
    # custom roots named like core ones must stay custom: only structure decides
    sneaky = tmp_path / "addons"
    sneaky.mkdir()
    roots = [root / "odoo" / "addons", root / "addons", root / "custom_addons", sneaky, project / "odoo_addons"]
    core, framework, custom = classify_addon_roots([r.resolve() for r in roots])
    assert core == (root / "addons").resolve()
    assert framework == (root / "odoo" / "addons").resolve()
    assert custom == tuple(r.resolve() for r in (root / "custom_addons", sneaky, project / "odoo_addons"))


def test_framework_deduced_when_only_the_core_addons_dir_is_listed(tmp_path):
    root, project = _odoo_tree(tmp_path)
    core, framework, custom = classify_addon_roots([(root / "addons").resolve(), (project / "odoo_addons").resolve()])
    assert framework == (root / "odoo" / "addons").resolve()
    assert custom == ((project / "odoo_addons").resolve(),)


def _link_base_into_core_addons(root: Path):
    (root / "addons" / "base").symlink_to(root / "odoo" / "addons" / "base")


def test_core_addons_dir_linking_to_base_is_not_the_framework_root(tmp_path):
    root, project = _odoo_tree(tmp_path)
    _link_base_into_core_addons(root)
    core, framework, custom = classify_addon_roots([(root / "addons").resolve(), (project / "odoo_addons").resolve()])
    assert core == (root / "addons").resolve()
    assert framework == (root / "odoo" / "addons").resolve()
    assert custom == ((project / "odoo_addons").resolve(),)


def test_framework_root_listed_beside_a_core_dir_linking_to_base(tmp_path):
    root, project = _odoo_tree(tmp_path)
    _link_base_into_core_addons(root)
    roots = [root / "addons", root / "odoo" / "addons", project / "odoo_addons"]
    core, framework, custom = classify_addon_roots([r.resolve() for r in roots])
    assert core == (root / "addons").resolve()
    assert framework == (root / "odoo" / "addons").resolve()
    assert custom == ((project / "odoo_addons").resolve(),)


def test_packaged_odoo_single_directory_is_core_and_framework(tmp_path):
    pkg = tmp_path / "dist-packages" / "odoo" / "addons"
    (pkg / "base").mkdir(parents=True)
    (pkg / "base" / "__manifest__.py").write_text("{}")
    core, framework, custom = classify_addon_roots([pkg.resolve()])
    assert core == framework == pkg.resolve()
    assert custom == ()


def test_nonexistent_custom_root_is_dropped(tmp_path):
    root, _ = _odoo_tree(tmp_path)
    _, _, custom = classify_addon_roots([(root / "addons").resolve(), (tmp_path / "ghost").resolve()])
    assert custom == ()


def test_conf_alone_gives_every_path_with_the_project_root_first(tmp_path):
    root, project = _odoo_tree(tmp_path)
    conf = _conf(tmp_path, ",".join(str(p) for p in (
        root / "odoo" / "addons", root / "addons", root / "custom_addons", project / "odoo_addons")))
    paths = resolve_addon_paths(conf, {}, root, project)
    assert paths.core == str((root / "addons").resolve())
    assert paths.framework == str((root / "odoo" / "addons").resolve())
    assert paths.custom[0] == str((project / "odoo_addons").resolve())
    assert set(paths.custom) == {str((project / "odoo_addons").resolve()), str((root / "custom_addons").resolve())}
    assert set(paths.sources.values()) == {"odoo.conf"}


def test_environment_variable_beats_conf_and_replaces_custom_roots(tmp_path):
    root, project = _odoo_tree(tmp_path)
    conf = _conf(tmp_path, f"{root / 'addons'},{root / 'custom_addons'}")
    env = {"CUSTOM_ADDONS_PATH": "/explicit/custom", "CORE_ADDONS_PATH": "/explicit/core"}
    paths = resolve_addon_paths(conf, env, root, project)
    assert paths.core == "/explicit/core" and paths.sources["CORE_ADDONS_PATH"] == "env"
    assert paths.custom == ("/explicit/custom",)


def test_without_conf_the_historical_defaults_apply(tmp_path):
    root, project = _odoo_tree(tmp_path)
    paths = resolve_addon_paths(None, {}, root, project)
    assert paths.core == str(root / "addons")
    assert paths.framework == str(root / "odoo" / "addons")
    assert paths.custom == (str(project / "odoo_addons"),)
    assert set(paths.sources.values()) == {"default"}


# --- Section 1250: database and URL ---------------------------------------

from config.odoo_conf import resolve_database, resolve_odoo_url  # noqa: E402


def _conf_with(tmp_path: Path, body: str) -> Path:
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\n" + body)
    return conf


def test_database_priority_env_then_conf_then_default(tmp_path):
    conf = _conf_with(tmp_path, "db_name = prod_db\n")
    assert resolve_database(conf, {"ODOO_DB": "forced"}) == ("forced", "env")
    assert resolve_database(conf, {}) == ("prod_db", "odoo.conf")
    assert resolve_database(None, {}) == ("odoo-dev", "default")


def test_database_not_deduced_when_conf_names_no_single_database(tmp_path):
    for body in ("db_name = False\n", "db_name = a,b\n", "db_name =\n", "http_port = 8070\n"):
        assert resolve_database(_conf_with(tmp_path, body), {}) == ("odoo-dev", "default")


def test_empty_environment_value_falls_back_to_conf(tmp_path):
    conf = _conf_with(tmp_path, "db_name = prod_db\nhttp_port = 8070\n")
    assert resolve_database(conf, {"ODOO_DB": ""}) == ("prod_db", "odoo.conf")
    assert resolve_odoo_url(conf, {"ODOO_URL": ""}) == ("http://localhost:8070", "odoo.conf")


def test_url_priority_and_validation(tmp_path):
    assert resolve_odoo_url(_conf_with(tmp_path, "http_port = 8070\n"), {"ODOO_URL": "https://erp"}) == ("https://erp", "env")
    for body in ("http_port = abc\n", "http_port = 0\n", "http_port = 70000\n", "db_name = x\n"):
        assert resolve_odoo_url(_conf_with(tmp_path, body), {}) == ("http://localhost:8069", "default")


def test_connector_and_rpc_client_use_the_conf_defaults(monkeypatch):
    import erp_data.odoo_connector as connector
    import code_intelligence.agent.rpc_client as rpc
    monkeypatch.delenv("ODOO_URL", raising=False)
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.setattr(connector, "ODOO_URL_DEFAULT", "http://localhost:8070")
    monkeypatch.setattr(connector, "ODOO_DB_DEFAULT", "prod_db")
    monkeypatch.setattr(rpc._settings, "ODOO_URL_DEFAULT", "http://localhost:8070")
    monkeypatch.setattr(rpc._settings, "ODOO_DB_DEFAULT", "prod_db")
    c = connector.OdooConnector(technical=True)
    assert (c.url, c.db) == ("http://localhost:8070", "prod_db")
    monkeypatch.setenv("ODOO_DB", "")
    assert connector.OdooConnector(technical=True).db == "prod_db"
    client = rpc.OdooRpcClient()
    assert (client.url, client.db) == ("http://localhost:8070", "prod_db")
