"""Composition of method override chain analysis and evidence building."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from code_intelligence.utils import format_file_link
from code_intelligence.semgrep_locks_analyzer import (
    analyze_python_security_locks,
    extract_method_security_constraints,
)
from core.evidence import Evidence, EvidenceSourceType, make_evidence
from code_intelligence.override_types import (
    MethodOverrideSite,
    MethodOverrideChainResult,
    resolve_method_override_chain,
)
from code_intelligence.override_unguarded_super import detect_unguarded_super
from code_intelligence.override_relational_chains import detect_unchecked_relational_chain
from code_intelligence.override_llm_interpreter import (
    interpret_override_chain_with_llm,
    _LLM_CONFIDENCE_CLOSED_SET,
    _INTERPRETATION_SYSTEM_PROMPT,
)

_logger = logging.getLogger(__name__)


def _build_override_chain_evidence_no_sites(model_name: str, method_name: str) -> List[Evidence]:
    return [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Method '{model_name}.{method_name}' is not overridden across "
            f"multiple modules (single declaration, or method not found in "
            f"the graph)"
        ),
        source=f"override_chain:{model_name}:{method_name}:no_sites",
        value=0,
        confidence="HIGH",
        scope={},
    )]


def _build_override_chain_site_evidence(
    model_name: str, method_name: str, idx: int, total: int, site: MethodOverrideSite
) -> Evidence:
    scope: Dict[str, Any] = {}
    if site.lineno:
        scope["lineno"] = site.lineno
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Method '{model_name}.{method_name}' is overridden by module "
            f"'{site.module}' (execution order position {idx}/{total})"
        ),
        source=f"override_chain:{model_name}:{method_name}:site:{site.module}",
        value=site.module,
        confidence="HIGH",
        scope=scope,
    )


def _build_override_chain_check_evidence(
    model_name: str, method_name: str, site: MethodOverrideSite,
    check_name: str, warning: Optional[str],
) -> Evidence:
    scope: Dict[str, Any] = {}
    if site.lineno:
        scope["lineno"] = site.lineno
    if warning:
        return make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Module '{site.module}' override of "
                f"'{model_name}.{method_name}' has a {check_name} finding"
            ),
            source=f"override_chain:{model_name}:{method_name}:{check_name}:{site.module}",
            value=warning,
            confidence="LOW",
            scope=scope,
        )
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Module '{site.module}' override of "
            f"'{model_name}.{method_name}' has no {check_name} finding"
        ),
        source=f"override_chain:{model_name}:{method_name}:{check_name}:{site.module}",
        value=None,
        confidence="HIGH",
        scope=scope,
    )


def _compose_compute_methods_overview(
    G: nx.DiGraph, model_name: str, llm=None
) -> MethodOverrideChainResult:
    from collections import defaultdict

    methods_by_mod = defaultdict(list)
    line_model = f"{model_name}.line"
    evidence: List[Evidence] = []

    for _, d in G.nodes(data=True):
        if d.get("node_type") != "Method":
            continue
        m = d.get("model", "")
        name = d.get("name", "")
        if m in (model_name, line_model) and name.startswith("_compute_"):
            sites = d.get("override_sites", [])
            for s in sites:
                mod = s.get("module", "unknown")
                if mod not in ("base", "sale", "purchase", "account", "stock") or len(sites) > 1:
                    methods_by_mod[mod].append((m, name, s, sites))

    if not methods_by_mod:
        text = f"Aucune méthode calculée (_compute_*) surchargée trouvée pour '{model_name}'."
        return MethodOverrideChainResult(
            summary_text=text,
            evidence=_build_override_chain_evidence_no_sites(model_name, "compute"),
        )

    def _mod_sort_key(mod_name):
        items = methods_by_mod[mod_name]
        is_custom = any(
            "/addons/" not in s.get("filepath", "") or "oca" in s.get("filepath", "")
            for _, _, s, _ in items
        )
        return (0 if is_custom else 1, mod_name)

    sorted_mods = sorted(methods_by_mod.keys(), key=_mod_sort_key)
    lines = [f"Méthodes calculées (_compute_*) surchargées ou définies pour '{model_name}' :"]

    for mod in sorted_mods:
        items = methods_by_mod[mod]
        model_items = [item for item in items if item[0] == model_name]
        if model_items:
            lines_with_nos = [s.get("lineno", 0) for _, _, s, _ in model_items if s.get("lineno")]
            end_lines = [
                s.get("end_lineno", s.get("lineno", 0))
                for _, _, s, _ in model_items
                if s.get("end_lineno") or s.get("lineno")
            ]
            min_line = min(lines_with_nos) if lines_with_nos else 0
            max_line = max(end_lines) if end_lines else 0
            fp = model_items[0][2].get("filepath", "")
            if min_line and max_line and fp:
                span_link = format_file_link(fp, min_line, max_line)
                lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) -- Extrait principal : {span_link}")
            else:
                lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) :")
        else:
            lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) :")

        for m, name, s, all_sites in items:
            other_mods = [x.get("module") for x in all_sites if x.get("module") != mod]
            c_str = ", ".join(other_mods)
            cascade_info = f" (surcharge {c_str})" if other_mods else " (définition/conversion en calculée)"
            link = format_file_link(s.get("filepath", ""), s.get("lineno", 0), s.get("end_lineno", 0))
            prefix = f"[{m}] " if m != model_name else ""
            lines.append(f"  - {prefix}{name}{cascade_info} -- {link}")

            if m != model_name:
                p = Path(s.get("filepath", ""))
                if p.exists() and s.get("lineno"):
                    try:
                        code_lines = p.read_text(encoding="utf-8").splitlines()
                        sl = max(0, s["lineno"] - 1)
                        el = min(len(code_lines), (s.get("end_lineno") or s["lineno"]))
                        snippet = "\n    ".join(code_lines[sl:el])
                        lines.append(f"    Code {m}.{name}:\n    {snippet}")
                    except Exception:
                        pass

            site_obj = MethodOverrideSite(
                module=mod,
                filepath=s.get("filepath", ""),
                lineno=s.get("lineno", 0),
                end_lineno=s.get("end_lineno"),
            )
            evidence.append(
                _build_override_chain_site_evidence(m, name, 1, len(all_sites), site_obj)
            )

    return MethodOverrideChainResult(summary_text="\n".join(lines), evidence=evidence)


def _compose_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> MethodOverrideChainResult:
    if method_name.lower() in ("compute", "_compute", "_compute_*", "*", "all"):
        return _compose_compute_methods_overview(G, model_name, llm=llm)

    sites = resolve_method_override_chain(G, model_name, method_name)

    if not sites:
        text = (
            f"'{method_name}' n'est pas surchargée dans plusieurs modules pour "
            f"'{model_name}' (rien à composer -- une seule déclaration, ou méthode "
            f"introuvable dans le graphe)."
        )
        return MethodOverrideChainResult(
            summary_text=text,
            evidence=_build_override_chain_evidence_no_sites(model_name, method_name),
        )

    lines = [
        f"Cha\u00eene de surcharge de '{model_name}.{method_name}' "
        f"({len(sites)} modules, ordre d'ex\u00e9cution r\u00e9el, pas l'ordre de d\u00e9pendance):"
    ]

    warnings: List[str] = []
    snippets_for_llm: List[str] = []
    evidence: List[Evidence] = []

    for idx, site in enumerate(sites, start=1):
        link = format_file_link(site.filepath, site.lineno, site.end_lineno or site.lineno)
        lines.append(f"  {idx}. module '{site.module}' -- {link}")
        evidence.append(
            _build_override_chain_site_evidence(model_name, method_name, idx, len(sites), site)
        )

        p = Path(site.filepath)
        if not p.exists():
            continue
        source = p.read_text(encoding="utf-8")
        site_has_warning = False

        warning = detect_unguarded_super(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        evidence.append(_build_override_chain_check_evidence(
            model_name, method_name, site, "unguarded_super", warning
        ))
        if warning:
            warnings.append(warning)
            lines.append(f"     {warning}")
            site_has_warning = True

        relational_warning = detect_unchecked_relational_chain(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        evidence.append(_build_override_chain_check_evidence(
            model_name, method_name, site, "unchecked_relational_chain", relational_warning
        ))
        if relational_warning:
            warnings.append(relational_warning)
            lines.append(f"     {relational_warning}")
            site_has_warning = True

        security_analysis = analyze_python_security_locks(source, site.filepath)
        site_constraints = extract_method_security_constraints(
            security_analysis, site.lineno, site.end_lineno or site.lineno
        )
        for constraint in site_constraints:
            lines.append(f"     {constraint}")

        if not site_has_warning:
            lines.append(
                "     (aucun risque structurel d\u00e9tect\u00e9 par cette heuristique "
                "pour ce module -- pas de branche non garante ni de cha\u00eene "
                "relationnelle non v\u00e9rifi\u00e9e trouv\u00e9e)"
            )

        if site.end_lineno:
            snippet_lines = source.splitlines()[site.lineno - 1 : site.end_lineno]
            snippets_for_llm.append(
                f"# module '{site.module}' ({site.filepath}:L{site.lineno}-L{site.end_lineno})\n"
                + "\n".join(snippet_lines)
            )

    if warnings and llm is not None:
        interpretation = interpret_override_chain_with_llm(
            model_name, method_name, warnings, snippets_for_llm, llm
        )
        if interpretation:
            lines.append(
                f"  -> Interpr\u00e9tation LLM [confiance: {interpretation['confidence'].upper()}, "
                f"distincte de la confiance statique ci-dessus]: {interpretation['summary']}"
            )

    return MethodOverrideChainResult(summary_text="\n".join(lines), evidence=evidence)


def analyze_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> str:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm).summary_text


def analyze_method_override_chain_with_evidence(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> MethodOverrideChainResult:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm)
