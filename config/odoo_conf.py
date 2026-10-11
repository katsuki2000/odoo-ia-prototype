"""Addon paths deduced from the target Odoo's own odoo.conf (pure functions, no import of settings).

Priority applied by `resolve_addon_paths`: explicit environment variable > odoo.conf > built-in default.
The core/custom split is structural (what a directory contains), never a folder-name rule.
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


def _normalize(raw: str) -> Optional[Path]:
    text = raw.strip()
    if not text:
        return None
    return Path(os.path.expandvars(os.path.expanduser(text))).resolve()


def read_addons_path(conf_path) -> list[Path]:
    """Roots declared by `[options] addons_path`, in Odoo's order; [] when unreadable or unset."""
    conf_file = Path(conf_path).expanduser() if conf_path else None
    if not conf_file or not conf_file.is_file():
        return []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with conf_file.open(encoding="utf-8") as stream:
            parser.read_file(stream)
        raw = parser.get("options", "addons_path", fallback="")
    except (OSError, configparser.Error) as error:
        logger.warning("Could not read Odoo configuration '%s' (%s).", conf_file, error)
        return []
    roots = (_normalize(part) for part in raw.replace("\n", ",").split(","))
    return list(dict.fromkeys(root for root in roots if root))


def is_framework_root(root: Path) -> bool:
    """Directory holding the `base` module (Odoo's `odoo/addons`)."""
    return (root / "base" / "__manifest__.py").is_file()


def is_core_addons_root(root: Path) -> bool:
    """Official `addons` directory: it sits beside the `odoo` package / `odoo-bin` of an Odoo source tree."""
    if is_framework_root(root):
        return False
    parent = root.parent
    return (parent / "odoo-bin").is_file() or is_framework_root(parent / "odoo" / "addons")


@dataclass(frozen=True)
class AddonPaths:
    core: str
    framework: str
    custom: tuple = ()
    sources: dict = field(default_factory=dict)


def classify_addon_roots(roots: Sequence[Path]):
    """(core addons root | None, framework root | None, custom roots) from the roots of addons_path."""
    framework = next((r for r in roots if is_framework_root(r)), None)
    core = next((r for r in roots if is_core_addons_root(r)), None)
    if core is None and framework is not None:
        core = framework  # packaged Odoo: a single directory holds base and the official addons
    if framework is None and core is not None:
        candidate = core.parent / "odoo" / "addons"
        framework = candidate.resolve() if is_framework_root(candidate) else None
    official = {r for r in (core, framework) if r}
    custom = tuple(r for r in roots if r not in official and r.is_dir())
    return core, framework, custom


def resolve_addon_paths(
    conf_path, environ: Mapping[str, str], default_odoo_root: Path, project_root: Path,
) -> AddonPaths:
    """Core, framework and custom addon paths: environment override > odoo.conf > default."""
    default_core = default_odoo_root / "addons"
    default_custom = project_root / "odoo_addons"
    conf_core, conf_framework, conf_custom = classify_addon_roots(read_addons_path(conf_path))

    sources: dict = {}

    def pick(name: str, conf_value, default_value) -> str:
        explicit = environ.get(name)
        if explicit:
            sources[name] = "env"
            return explicit
        if conf_value:
            sources[name] = "odoo.conf"
            return str(conf_value)
        sources[name] = "default"
        return str(default_value)

    core = pick("CORE_ADDONS_PATH", conf_core, default_core)
    framework = pick(
        "CORE_FRAMEWORK_ADDONS_PATH", conf_framework, Path(core).parent / "odoo" / "addons"
    )

    preferred = next((r for r in conf_custom if r == default_custom.resolve()), None)
    first_custom = preferred or (conf_custom[0] if conf_custom else None)
    custom_main = pick("CUSTOM_ADDONS_PATH", first_custom, default_custom)

    if environ.get("CUSTOM_ADDONS_PATH") or not conf_custom:
        custom_all = (custom_main,)
    else:
        custom_all = tuple(dict.fromkeys([custom_main, *(str(r) for r in conf_custom)]))
    return AddonPaths(core=core, framework=framework, custom=custom_all, sources=sources)


def read_option(conf_path, key: str) -> Optional[str]:
    """Raw `[options]` value of `key`, or None when the conf is unreadable or the key is unset."""
    conf_file = Path(conf_path).expanduser() if conf_path else None
    if not conf_file or not conf_file.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with conf_file.open(encoding="utf-8") as stream:
            parser.read_file(stream)
        value = parser.get("options", key, fallback="").strip()
    except (OSError, configparser.Error):
        return None
    return value or None


DEFAULT_DATABASE = "odoo-dev"
DEFAULT_ODOO_URL = "http://localhost:8069"


def resolve_database(conf_path, environ: Mapping[str, str]):
    """(database, source): ODOO_DB > the single `db_name` of odoo.conf > default.

    `db_name = False`, empty, or a comma-separated list designate no single database: not deduced.
    """
    explicit = environ.get("ODOO_DB")
    if explicit:
        return explicit, "env"
    configured = read_option(conf_path, "db_name")
    if configured and configured.lower() != "false" and "," not in configured:
        return configured, "odoo.conf"
    return DEFAULT_DATABASE, "default"


def resolve_odoo_url(conf_path, environ: Mapping[str, str]):
    """(url, source): ODOO_URL > http://localhost:<http_port of odoo.conf> > default."""
    explicit = environ.get("ODOO_URL")
    if explicit:
        return explicit, "env"
    port = read_option(conf_path, "http_port")
    if port and port.isdigit() and 0 < int(port) < 65536:
        return f"http://localhost:{int(port)}", "odoo.conf"
    return DEFAULT_ODOO_URL, "default"
