"""Load the versioned E1 configuration (digest for freeze detection)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"


def load_e1_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or CONFIG_PATH
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    data["_digest"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    data["_path"] = str(config_path)
    return data
