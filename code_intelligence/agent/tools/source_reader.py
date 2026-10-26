"""Bounded reading of Odoo source files with path and evidence safeguards."""

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def _allowed_source_roots() -> list:
    from code_intelligence.agent.tools.helpers import get_graph_ref
    from config.settings import CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS
    graph = get_graph_ref()
    graphRoots = graph.graph.get("addon_roots_ordered", ()) if graph is not None else ()
    configured = (
        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS, *graphRoots,
    )
    return [Path(root).resolve() for root in dict.fromkeys(configured) if root and Path(root).exists()]


def read_precise_source_code(
    filepath_str: str, line_start: int, line_end: int, max_lines: int = 200,
    include_citation: bool = False,
) -> str:
    """Targeted source reader restricted to configured and active-graph addon roots."""
    from code_intelligence.agent.tools.source_boundary import validate_source_range
    rangeError = validate_source_range(line_start, line_end, max_lines)
    if rangeError:
        return rangeError
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    from code_intelligence.rules.server_actions import _SUDO_PATTERN, _HARDCODED_ID_LIST_PATTERN
    from code_intelligence.rules.security import _EMAIL_PATTERN
    from code_intelligence.agent.tools.helpers import get_graph_ref
    graph = get_graph_ref()
    path = Path(filepath_str)
    target_model_resolved = None
    if not path.exists() and Path("/" + filepath_str).exists():
        path = Path("/" + filepath_str)
    if not path.exists():
        import re
        from config.settings import _ROOT, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS
        candidates = [
            *(Path(custom_root) / filepath_str
              for custom_root in dict.fromkeys((CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS)) if custom_root),
            Path(CORE_ADDONS_PATH) / filepath_str if CORE_ADDONS_PATH else None,
            _ROOT / filepath_str,
        ]
        matched = next((c for c in candidates if c and c.exists()), None)
        if matched:
            path = matched
        else:
            if graph is not None:
                if graph.has_node(f"model:{filepath_str}"):
                    target_model_resolved = filepath_str
                else:
                    stem = Path(filepath_str).stem.replace("_", ".")
                    if graph.has_node(f"model:{stem}"):
                        target_model_resolved = stem
                    else:
                        for _, d in graph.nodes(data=True):
                            if d.get("node_type") == "Model":
                                m_name = d.get("name", "")
                                if m_name and m_name.replace(".", "_") == Path(filepath_str).stem:
                                    target_model_resolved = m_name
                                    break
                if target_model_resolved:
                    m_fps = graph.nodes[f"model:{target_model_resolved}"].get("filepaths", [])
                    for fp in m_fps:
                        p_candidate = Path(fp)
                        if p_candidate.exists() and not any(part in ("tests", "test", ".git", ".venv") for part in p_candidate.parts):
                            path = p_candidate
                            break
            if not path.exists():
                corpus_roots = [p for p in [
                    Path(CORE_ADDONS_PATH) if CORE_ADDONS_PATH else None,
                    *(Path(custom_root) for custom_root in dict.fromkeys((CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS)) if custom_root),
                ] if p and p.exists()]
                norm = filepath_str.lstrip("/").replace("\\", "/")
                parts = norm.split("/")
                tail_pattern = f"**/{norm}"
                short_pattern = f"**/{'/'.join(parts[-2:])}" if len(parts) >= 2 else None
                for root in corpus_roots:
                    matches = [f for f in root.glob(tail_pattern)
                               if not any(part in ("tests", "test", ".git", ".venv", "__pycache__") for part in f.parts)]
                    if not matches and short_pattern:
                        matches = [f for f in root.glob(short_pattern)
                                   if not any(part in ("tests", "test", ".git", ".venv", "__pycache__") for part in f.parts)]
                    if matches:
                        path = matches[0]
                        break
            if not path.exists():
                return f"Error: File '{filepath_str}' does not exist."
    allowed_roots = _allowed_source_roots()
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        return f"Error: Source file '{filepath_str}' could not be resolved."
    supported_source_suffixes = {".py", ".xml", ".csv", ".js", ".po", ".sql", ".css", ".scss", ".html"}
    is_allowed = any(resolved_path == root or root in resolved_path.parents for root in allowed_roots)
    if not is_allowed or not resolved_path.is_file() or resolved_path.suffix.lower() not in supported_source_suffixes:
        return "Error: Source file is outside configured addon roots or is not a supported source file."
    path = resolved_path
    if target_model_resolved and path.exists() and line_start <= 1:
        try:
            import re
            text = path.read_text(encoding="utf-8")
            pos = re.search(r"(?:_name|_inherit)\s*=\s*['\"]" + re.escape(target_model_resolved) + r"['\"]", text)
            if pos:
                before = text[:pos.start()]
                class_matches = list(re.finditer(r"class\s+\w+", before))
                if class_matches:
                    class_pos = class_matches[-1].start()
                    class_lineno = text[:class_pos].count("\n") + 1
                    line_start = class_lineno
                    line_end = class_lineno + min(max_lines - 1, 150)
        except (OSError, UnicodeDecodeError) as err:
            _logger.warning("Cannot read %s to locate model %s: %s", path, target_model_resolved, err)
    requested_lines = line_end - line_start + 1
    if requested_lines > max_lines:
        return f"Error: Line range ({requested_lines} lines) exceeds maximum safeguard limit of {max_lines} lines."
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        total_lines = len(lines)
        start_idx = max(0, line_start - 1)
        end_idx = min(total_lines, line_end)
        selected_lines = lines[start_idx:end_idx]
        snippet = []
        for i, line in enumerate(selected_lines, start=start_idx + 1):
            tag = ""
            if _SUDO_PATTERN.search(line) or _HARDCODED_ID_LIST_PATTERN.search(line) or _EMAIL_PATTERN.search(line):
                tag = f"  {SENSITIVE_BYPASS_MARKER} Contenu source sensible detecte sur cette ligne (lecture brute)"
            snippet.append(f"{i:4d} | {line}{tag}")
        body = "\n".join(snippet)
        from code_intelligence.rules.source_callees import inspect_noop_hook_method, format_noop_hook_note
        hook_info = inspect_noop_hook_method("\n".join(selected_lines))
        if hook_info:
            func_name, noop_desc = hook_info
            body += "\n\n" + format_noop_hook_note(func_name, noop_desc)
        if include_citation:
            from code_intelligence.utils import format_file_link
            shown_start, shown_end = start_idx + 1, end_idx
            citation = format_file_link(str(path), shown_start, shown_end)
            body = f"Source: {citation}\n{body}"
        return body
    except (OSError, UnicodeDecodeError) as e:
        _logger.error("Error reading file %s: %s", filepath_str, e)
        return f"Error reading file '{filepath_str}': {str(e)}"
