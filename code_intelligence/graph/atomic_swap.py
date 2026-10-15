import json
import os
import uuid
from pathlib import Path
from typing import Dict, Any
import logging

_logger = logging.getLogger(__name__)


def atomic_write_json(data: Dict[str, Any], target_filepath: Path) -> Path:
    """
    Atomically write a JSON dictionary to target_filepath using fsync + os.replace.
    """
    target_filepath = Path(target_filepath).resolve()
    target_dir = target_filepath.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Unique temporary file in the same directory (same filesystem required for atomic replace)
    tmp_filename = f"{target_filepath.name}.tmp.{uuid.uuid4().hex}"
    tmp_filepath = target_dir / tmp_filename

    try:
        with open(tmp_filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        # Kernel-level atomic swap
        os.replace(tmp_filepath, target_filepath)
        _logger.info("Atomic graph swap completed -> %s", target_filepath)
        return target_filepath

    except Exception as e:
        _logger.error("Atomic swap failed for %s: %s", target_filepath, e)
        if tmp_filepath.exists():
            try:
                tmp_filepath.unlink()
            except OSError:
                pass
        raise e


def atomic_read_json(target_filepath: Path) -> Dict[str, Any]:
    """
    Safely read JSON data from target_filepath.
    Guaranteed not to fail due to partial writes when using atomic_write_json.
    """
    target_filepath = Path(target_filepath).resolve()
    if not target_filepath.exists():
        raise FileNotFoundError(f"Graph file not found: {target_filepath}")

    with open(target_filepath, "r", encoding="utf-8") as f:
        return json.load(f)
