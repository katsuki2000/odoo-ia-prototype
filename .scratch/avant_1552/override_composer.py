"""
code_intelligence/overrides/prompts.py

System prompts and prompt builders for LLM interpretation of method override findings.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de code Odoo. Un premier passage automatique (analyse AST) a "
    "repéré un appel `super()` inconditionnel après une branche conditionnelle qui "
    "ne se termine pas directement par un `return`/`raise` à son dernier statement -- "
    "CECI EST UN INDICE BRUT, PAS UN FAIT CONFIRMÉ. Cette heuristique statique ne "
    "vérifie ni si la branche modifie réellement un champ de l'enregistrement, ni si "
    "un `raise`/`return` imbriqué plus loin dans la branche couvre déjà tous les cas -- "
    "elle peut donc se tromper. AVANT de résumer une conséquence, VERIFIE toi-même sur "
    "le code fourni : (1) la branche écrit-elle vraiment un champ de l'enregistrement "
    "(`rec.champ = ...`, `.write(...)`, etc.) sur au moins un chemin qui NE se termine PAS "
    "par un `return`/`raise` ? Si NON (ex: la branche ne fait que lever une exception ou ne "
    "rien faire), il n'y a RIEN que le `super()` puisse écraser -- dis-le explicitement, "
    "n'invente aucune conséquence négative, et mets confidence à 'low'. (2) Si la "
    "prémisse tient réellement, résume en une phrase la conséquence métier concrète "
    "(quel comportement l'utilisateur observera réellement). Ta réponse doit toujours "
    "être cohérente avec tout message d'erreur (UserError/ValidationError) visible dans "
    "le même extrait de code -- si un `raise` bloque explicitement un cas, ne dis JAMAIS "
    "que ce cas est approuvé ou que la restriction est annulée. Réponds STRICTEMENT en "
    "JSON, sans aucun texte avant ou après, au format exact: "
    '{"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def build_override_interpretation_prompt(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
) -> str:
    """Build the bounded user prompt for method override chain interpretation."""
    detected = "\n".join(f"- {w}" for w in warnings)
    code_block = "\n\n".join(snippets)
    return (
        f"Méthode '{model_name}.{method_name}', chaîne de surcharge "
        f"(ordre d'exécution réel):\n```python\n{code_block}\n```\n\n"
        f"Indice brut de l'analyse statique (AST) -- à vérifier, pas à prendre pour "
        f"acquis:\n{detected}\n\n"
        "Vérifie d'abord si cet indice tient reellement (la branche mute-t-elle un champ "
        "de l'enregistrement sans que ce chemin ne se termine par return/raise ?), puis "
        "résume en une phrase claire le comportement métier réellement observé (pas le "
        "code), et indique ta confiance."
    )


def build_override_interpretation_messages(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
) -> List[BaseMessage]:
    """Construct the full message list for method override LLM interpretation."""
    return [
        SystemMessage(content=_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=build_override_interpretation_prompt(model_name, method_name, warnings, snippets)),
    ]


__all__ = [
    "_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT",
    "build_override_interpretation_prompt",
    "build_override_interpretation_messages",
]

# ── Override Composer ────────────────────────────────────────────────────

"""Composition of method override chain analysis and evidence building."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from code_intelligence.utils import format_file_link, read_source_text
from code_intelligence.rules.security import (
    analyze_python_security_locks,
    extract_method_security_constraints,
)
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from code_intelligence.rules.override_unguarded import (
    MethodOverrideSite,
    MethodOverrideChainResult,
    resolve_method_override_chain,
)
from code_intelligence.rules.override_unguarded import detect_unguarded_super
from code_intelligence.rules.overrides import detect_unchecked_relational_chain
from code_intelligence.rules.override_unguarded import interpret_override_chain_with_llm

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
        is_custom = any("/addons/" not in s.get("filepath", "") for _, _, s, _ in items)
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
                source = read_source_text(p) if p.exists() and s.get("lineno") else None
                if source is not None:
                    code_lines = source.splitlines()
                    sl = max(0, s["lineno"] - 1)
                    el = min(len(code_lines), (s.get("end_lineno") or s["lineno"]))
                    snippet = "\n    ".join(code_lines[sl:el])
                    lines.append(f"    Code {m}.{name}:\n    {snippet}")

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

    site_blocks: List[str] = []
    warnings: List[str] = []
    snippets_for_llm: List[str] = []
    evidence: List[Evidence] = []

    for idx, site in enumerate(sites, start=1):
        site_lines: List[str] = []
        link = format_file_link(site.filepath, site.lineno, site.end_lineno or site.lineno)
        site_lines.append(f"  {idx}. module '{site.module}' -- {link}")
        evidence.append(
            _build_override_chain_site_evidence(model_name, method_name, idx, len(sites), site)
        )

        p = Path(site.filepath)
        if not p.exists():
            site_blocks.append("\n".join(site_lines))
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
            site_lines.append(f"     {warning}")
            site_has_warning = True

        relational_warning = detect_unchecked_relational_chain(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        evidence.append(_build_override_chain_check_evidence(
            model_name, method_name, site, "unchecked_relational_chain", relational_warning
        ))
        if relational_warning:
            warnings.append(relational_warning)
            site_lines.append(f"     {relational_warning}")
            site_has_warning = True

        security_analysis = analyze_python_security_locks(source, site.filepath)
        site_constraints = extract_method_security_constraints(
            security_analysis, site.lineno, site.end_lineno or site.lineno
        )
        for constraint in site_constraints:
            site_lines.append(f"     {constraint}")

        if not site_has_warning:
            site_lines.append(
                "     (aucun risque structurel détecté par cette heuristique "
                "pour ce module -- pas de branche non garante ni de chaîne "
                "relationnelle non vérifiée trouvée)"
            )

        if site.end_lineno:
            snippet_lines = source.splitlines()[site.lineno - 1 : site.end_lineno]
            snippets_for_llm.append(
                f"# module '{site.module}' ({site.filepath}:L{site.lineno}-L{site.end_lineno})\n"
                + "\n".join(snippet_lines)
            )
        site_blocks.append("\n".join(site_lines))

    trailing_lines: List[str] = []
    if warnings and llm is not None:
        interpretation = interpret_override_chain_with_llm(
            model_name, method_name, warnings, snippets_for_llm, llm
        )
        if interpretation:
            trailing_lines.append(
                f"  -> Interprétation LLM [confiance: {interpretation['confidence'].upper()}, "
                f"distincte de la confiance statique ci-dessus]: {interpretation['summary']}"
            )

    header_text = (
        f"Chaîne de surcharge de '{model_name}.{method_name}' "
        f"({len(sites)} modules, ordre d'exécution réel, pas l'ordre de dépendance):"
    )

    from code_intelligence.rules.relevance_budget import assemble_relevance_ranked_blocks
    from code_intelligence.agent.context import PER_TOOL_OBSERVATION_CAPS
    from code_intelligence.agent.tools.helpers import get_current_question

    trailing_str = ("\n" + "\n".join(trailing_lines)) if trailing_lines else ""
    overhead = len(header_text) + 1 + len(trailing_str)
    body_budget = max(0, PER_TOOL_OBSERVATION_CAPS.get("analyze_method_override_chain", 2200) - overhead)
    body = assemble_relevance_ranked_blocks(
        site_blocks, body_budget, question=get_current_question(), separator="\n",
    )
    summary_text = f"{header_text}\n{body}{trailing_str}" if body else f"{header_text}{trailing_str}"

    return MethodOverrideChainResult(summary_text=summary_text, evidence=evidence)


def analyze_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> str:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm).summary_text


def analyze_method_override_chain_with_evidence(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> MethodOverrideChainResult:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm)
