import ast
import builtins
import logging
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet

from config.settings import ODOO_SOURCE_PATH

logger = logging.getLogger(__name__)

BUILTIN_NAMES: FrozenSet[str] = frozenset(dir(builtins))


def load_base_model_methods(models_source: Path) -> FrozenSet[str]:
    try:
        tree = ast.parse(Path(models_source).read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        logger.warning("Base model methods unavailable (%s): %s", models_source, error)
        return frozenset()
    return frozenset(
        member.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Model")
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


@lru_cache(maxsize=1)
def default_base_model_methods() -> FrozenSet[str]:
    return load_base_model_methods(Path(ODOO_SOURCE_PATH) / "odoo" / "models.py")
