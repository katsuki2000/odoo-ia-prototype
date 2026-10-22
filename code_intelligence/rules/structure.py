"""
code_intelligence/deterministic/field_impact.py

Multi-hop dependency and downstream impact analysis for computed fields in Odoo models.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import ast
import logging
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import parse_python_text, read_source_text
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence

logger = logging.getLogger(__name__)


@dataclass
class FieldImpactResult:
    field_name: str
    model_name: str
    upstream_triggers: List[str] = field(default_factory=list)
    upstream_trigger_paths: Dict[str, str] = field(default_factory=dict)
    downstream_computed_fields: List[str] = field(default_factory=list)
    propagation_depth: int = 0
    relational_target: Optional[str] = None
    compute_method: Optional[str] = None
    field_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)


def _field_to_short_name(field_node_id: str) -> str:
    """'field:hr.expense.risk_score' -> 'risk_score'."""
    raw = field_node_id.removeprefix("field:")
    return raw.rsplit(".", 1)[-1]


def _bfs_downstream(
    G: nx.DiGraph,
    start_field_node: str,
    max_depth: int = 10,
) -> Tuple[Set[str], int]:
    """
    Multi-hop BFS downstream propagation.
    From a field node, follows:
      in_edges DEPENDS_ON -> method node -> in_edges COMPUTED_BY -> computed field node
    then recurses from each discovered computed field.
    Returns (set_of_downstream_field_node_ids, max_depth_reached).
    """
    visited_fields: Set[str] = set()
    queue: deque = deque()
    queue.append((start_field_node, 0))
    visited_fields.add(start_field_node)
    max_depth_reached = 0

    while queue:
        current_field, depth = queue.popleft()
        if depth >= max_depth:
            continue

        for in_node, _, in_edge_data in G.in_edges(current_field, data=True):
            if in_edge_data.get("edge_type") != "DEPENDS_ON":
                continue
            method_node = in_node
            for comp_node, _, comp_edge_data in G.in_edges(method_node, data=True):
                if comp_edge_data.get("edge_type") != "COMPUTED_BY":
                    continue
                if comp_node not in visited_fields:
                    visited_fields.add(comp_node)
                    next_depth = depth + 1
                    if next_depth > max_depth_reached:
                        max_depth_reached = next_depth
                    queue.append((comp_node, next_depth))

    visited_fields.discard(start_field_node)
    return visited_fields, max_depth_reached


def _collect_upstream_triggers(
    G: nx.DiGraph,
    field_node: str,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Collect upstream trigger fields for a computed field.
    Returns (set_of_trigger_short_names, dict_of_trigger_short_name -> trigger_path).
    """
    upstream_triggers: Set[str] = set()
    trigger_paths: Dict[str, str] = {}

    for neighbor in G.neighbors(field_node):
        edge_data = G.get_edge_data(field_node, neighbor) or {}
        if edge_data.get("edge_type") != "COMPUTED_BY":
            continue
        method_node = neighbor
        for method_neighbor in G.neighbors(method_node):
            m_edge = G.get_edge_data(method_node, method_neighbor) or {}
            if m_edge.get("edge_type") != "DEPENDS_ON":
                continue
            trig_short = _field_to_short_name(method_neighbor)
            upstream_triggers.add(trig_short)
            trigger_path = m_edge.get("trigger_path")
            if trigger_path and trigger_path != trig_short:
                trigger_paths[trig_short] = trigger_path

    return upstream_triggers, trigger_paths


def _build_field_impact_evidence(
    model_name: str,
    field_name: str,
    upstream_triggers: Set[str],
    upstream_trigger_paths: Dict[str, str],
    downstream_field_nodes: Set[str],
) -> List[Evidence]:
    """
    one Evidence per upstream trigger dependency and one Evidence per downstream computed field.
    """
    evidence: List[Evidence] = []

    for trig in sorted(upstream_triggers):
        trigger_path = upstream_trigger_paths.get(trig, trig)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"'{model_name}.{field_name}' is recomputed when '{trigger_path}' changes",
            source=f"depends_on:{model_name}.{field_name}:{trig}",
            value=trigger_path,
            confidence="HIGH",
        ))

    for dn in sorted(downstream_field_nodes):
        short_name = _field_to_short_name(dn)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Changing '{model_name}.{field_name}' triggers recomputation of '{short_name}'",
            source=dn,
            value=short_name,
            confidence="HIGH",
        ))

    return evidence


def field_change_impact(
    G: nx.DiGraph,
    field_name: str,
    model_name: str,
    max_depth: int = 10,
) -> FieldImpactResult:
    """
    Analyzes upstream dependencies and downstream impact of modifying a field.
    Traces COMPUTED_BY, DEPENDS_ON, and RELATES_TO edges on the Knowledge Graph.
    """
    field_node = f"field:{model_name}.{field_name}"

    if field_node not in G:
        return FieldImpactResult(
            field_name=field_name,
            model_name=model_name,
            summary_text=f"Field '{field_name}' on model '{model_name}' {NOT_FOUND_MARKER}."
        )

    f_data = G.nodes[field_node]
    compute_method = f_data.get("compute")
    relational_target = f_data.get("comodel_name")

    upstream_triggers, trigger_paths = _collect_upstream_triggers(G, field_node)
    downstream_field_nodes, depth_reached = _bfs_downstream(G, field_node, max_depth=max_depth)
    downstream_computed_fields: Set[str] = set()
    for dn in downstream_field_nodes:
        downstream_computed_fields.add(_field_to_short_name(dn))

    downstream_str = ", ".join(sorted(downstream_computed_fields)) if downstream_computed_fields else "None"

    upstream_parts: List[str] = []
    for trig in sorted(upstream_triggers):
        if trig in trigger_paths:
            upstream_parts.append(f"{trig} (via {trigger_paths[trig]})")
        else:
            upstream_parts.append(trig)
    upstream_str = ", ".join(upstream_parts) if upstream_parts else "None"

    summary = (
        f"Field '{field_name}' on '{model_name}': "
        f"Triggers recomputation of [{downstream_str}]. "
        f"Depends on [{upstream_str}]."
    )

    return FieldImpactResult(
        field_name=field_name,
        model_name=model_name,
        upstream_triggers=sorted(list(upstream_triggers)),
        upstream_trigger_paths=trigger_paths,
        downstream_computed_fields=sorted(list(downstream_computed_fields)),
        propagation_depth=depth_reached,
        relational_target=relational_target,
        compute_method=compute_method,
        field_tags=tags_for_node_attrs(f_data),
        summary_text=summary,
        evidence=_build_field_impact_evidence(
            model_name, field_name, upstream_triggers, trigger_paths, downstream_field_nodes
        ),
    )

# ── Inheritance Chain ────────────────────────────────────────────────────

"""
code_intelligence/deterministic/inheritance_chain.py

Traversal and classification of Odoo model inheritance (_inherit extension vs _inherits delegation).
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Set
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER, QueryStatus
from code_intelligence.rules.model_suggestions import model_not_found_message
from code_intelligence.rules.ontology import tags_for_node_attrs
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class InheritanceChainResult:
    model_name: str
    status: QueryStatus = QueryStatus.NOT_FOUND
    extension_parents: List[str] = field(default_factory=list)
    delegation_parents: Dict[str, str] = field(default_factory=dict)
    full_ancestors: List[str] = field(default_factory=list)
    # Bloc P2 Jour 4: queried model's own behavioral_tags/technical_tags
    model_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)
    # (filepath, lineno,
    # end_line) per declaration site, same custom-module-first order as the
    # file:// links folded into summary_text -- lets callers reuse this
    # structured data instead of re-parsing summary_text.
    declaration_sites: List[Tuple[str, int, int]] = field(default_factory=list)


def _build_inheritance_evidence(
    model_name: str,
    extension_parents: Set[str],
    delegation_parents: Dict[str, str],
) -> List[Evidence]:
    """
    B1: one Evidence per direct EXTENDS (_inherit) parent and one per direct DELEGATES_TO (_inherits) parent.
    """
    evidence: List[Evidence] = []

    for parent in sorted(extension_parents):
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' extends '{parent}' via _inherit",
            source=f"extends:{model_name}:{parent}",
            value=parent,
            confidence="HIGH",
        ))

    for parent, fk_field in sorted(delegation_parents.items()):
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Model '{model_name}' delegates to '{parent}' via _inherits "
                f"(foreign key '{fk_field}')"
            ),
            source=f"delegates_to:{model_name}:{parent}",
            value=fk_field,
            confidence="HIGH",
        ))

    if not extension_parents and not delegation_parents:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' does not inherit from any other model (no _inherit or _inherits)",
            source=f"inherits:{model_name}",
            value=None,
            confidence="HIGH",
        ))

    return evidence


def trace_full_inheritance(
    G: nx.DiGraph,
    model_name: str
) -> InheritanceChainResult:
    """
    Traverses full inheritance chain distinguishing _inherit extension vs _inherits delegation.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return InheritanceChainResult(
            model_name=model_name,
            status=QueryStatus.NOT_FOUND,
            summary_text=model_not_found_message(G, model_name)
        )

    extension_parents: Set[str] = set()
    delegation_parents: Dict[str, str] = {}
    full_ancestors: List[str] = []

    # BFS traversal for full ancestors
    visited: Set[str] = {model_name}
    queue: List[str] = [model_name]

    while queue:
        curr = queue.pop(0)
        curr_node = f"model:{curr}"

        if curr_node in G:
            for neighbor in G.neighbors(curr_node):
                edge_data = G.get_edge_data(curr_node, neighbor) or {}
                edge_type = edge_data.get("edge_type")

                if edge_type == "EXTENDS":
                    parent_m = neighbor.replace("model:", "")
                    if curr == model_name:
                        extension_parents.add(parent_m)
                    if parent_m not in visited:
                        visited.add(parent_m)
                        queue.append(parent_m)
                        full_ancestors.append(parent_m)

                elif edge_type == "DELEGATES_TO":
                    parent_m = neighbor.replace("model:", "")
                    fk_field = edge_data.get("fk_field", "")
                    if curr == model_name:
                        delegation_parents[parent_m] = fk_field
                    if parent_m not in visited:
                        visited.add(parent_m)
                        queue.append(parent_m)
                        full_ancestors.append(parent_m)

    model_tags = tags_for_node_attrs(G.nodes[model_node])

    if not extension_parents and not delegation_parents:
        if model_name.endswith(".mixin"):
            shared_fields = sorted(
                str(data.get("name"))
                for _, data in G.nodes(data=True)
                if data.get("node_type") == "Field" and data.get("model") == model_name and data.get("name")
            )
            shared_methods = sorted(
                str(data.get("name"))
                for _, data in G.nodes(data=True)
                if data.get("node_type") == "Method" and data.get("model") == model_name and data.get("name")
            )
            details = []
            if shared_fields:
                details.append("champs partagés : " + ", ".join(shared_fields))
            if shared_methods:
                details.append("méthodes de calcul : " + ", ".join(shared_methods))
            mixin_users = sorted(
                data.get("name", node_id.replace("model:", ""))
                for node_id, data in G.nodes(data=True)
                if data.get("node_type") == "Model"
                and data.get("name", node_id.replace("model:", "")) != model_name
                and (G.get_edge_data(node_id, model_node) or {}).get("edge_type") == "EXTENDS"
            )
            if mixin_users:
                details.append("réutilisé directement par : " + ", ".join(mixin_users))
            mixin_summary = f"Model '{model_name}' est un mixin réutilisable"
            if details:
                mixin_summary += " (" + "; ".join(details) + ")"
            return InheritanceChainResult(
                model_name=model_name,
                status=QueryStatus.FOUND,
                model_tags=model_tags,
                summary_text=mixin_summary + ".",
                evidence=_build_inheritance_evidence(model_name, extension_parents, delegation_parents),
            )
        return InheritanceChainResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            model_tags=model_tags,
            summary_text=f"Model '{model_name}' exists in the index but does not inherit from any other models.",
            evidence=_build_inheritance_evidence(model_name, extension_parents, delegation_parents),
        )

    ext_str = ", ".join(sorted(extension_parents)) if extension_parents else "None"
    del_str = ", ".join([f"{m} (via {fk})" for m, fk in delegation_parents.items()]) if delegation_parents else "None"

    mixins = [p for p in extension_parents if p.endswith(".mixin") or p in ("mail.thread", "mail.activity.mixin", "rating.mixin", "portal.mixin", "utm.mixin", "image.mixin", "avatar.mixin")]
    business_parents = [p for p in extension_parents if p not in mixins and p != model_name]
    nature_str = ""
    if extension_parents:
        if not business_parents:
            nature_str = f" Nature: Nouveau modèle déclarant son propre _name='{model_name}' avec mixins techniques uniquement ({', '.join(sorted(mixins))}), pas d'extension d'un modèle métier existant."
        else:
            nature_str = f" Nature: Extension de modèle(s) métier ({', '.join(sorted(business_parents))})."

    summary = (
        f"Inheritance Chain for '{model_name}': "
        f"Extensions (_inherit): [{ext_str}]. "
        f"Delegations (_inherits): [{del_str}]. "
        f"Full Ancestor Chain: [{', '.join(full_ancestors)}].{nature_str}"
    )

    mixin_users = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        candidate = data.get("name", node_id.replace("model:", ""))
        if candidate == model_name or not G.has_node(node_id):
            continue
        edge = G.get_edge_data(node_id, model_node) or {}
        if edge.get("edge_type") == "EXTENDS":
            mixin_users.append(candidate)
    if model_name.endswith(".mixin") and mixin_users:
        summary += f" Directement réutilisé par : {', '.join(sorted(mixin_users))}."

    filepaths = G.nodes[model_node].get("filepaths", [])
    declaration_sites: List[Tuple[str, int, int]] = []
    if filepaths:
        from code_intelligence.agent.tools.helpers import _is_custom_module_filepath

        def _build_file_link(fp: str) -> Tuple[str, int, int]:
            """Locate the _name/_inherit line for model_name in fp and
            return (markdown_link, lineno, end_line)."""
            p = Path(fp)
            lineno = 1
            line_count = 50
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8")
                    line_count = max(1, len(text.splitlines()))
                    pos = re.search(r"(?:_name|_inherit)\s*=\s*['\"]" + re.escape(model_name) + r"['\"]", text)
                    if pos:
                        before = text[:pos.start()]
                        class_matches = list(re.finditer(r"class\s+\w+", before))
                        if class_matches:
                            class_pos = class_matches[-1].start()
                            lineno = text[:class_pos].count("\n") + 1
                except (OSError, UnicodeDecodeError) as err:
                    logger.warning("Cannot read %s to locate model %s: %s", p, model_name, err)
            end_line = min(lineno + 80, line_count)
            link = f"[{p.name}:L{lineno}-L{end_line}](file://{fp}#L{lineno}-L{end_line})"
            return link, lineno, end_line

        # filepath_roles (graph/builder.py)
        # already knows, per FILE, whether that file declares (_name=, no
        # self-_inherit) or merely extends (_inherit=) the model -- computed
        # once at build time from the same per-declaration flag already
        # trusted for the module-level DEFINED_IN edges. Using it here means every file gets its own
        # correct label instead of the old behaviour, which slapped
        # "Declared in" on EVERY file matching a _name/_inherit regex
        # (declaration AND extension alike) and then relied on a
        # custom-first sort to put -- by pure luck, not correctness -- the
        # right one in front. A custom module extending the model would
        # match that regex too and could end up cited as if it declared the
        # model.
        filepath_roles: Dict[str, str] = G.nodes[model_node].get("filepath_roles", {})
        declares_files = [fp for fp in filepaths if filepath_roles.get(fp) == "declares"]
        extends_files = [fp for fp in filepaths if fp not in declares_files]

        if len(declares_files) == 1:
            # Clean case: exactly one file declares the model. Stable
            # (declaration order), no custom-first re-sort needed -- native
            # and custom extension files coexist under their own correct
            # label instead of competing for a single one.
            declared_link, d_lineno, d_end = _build_file_link(declares_files[0])
            declaration_sites.append((declares_files[0], d_lineno, d_end))
            summary += f" Declared in: {declared_link}."

            if extends_files:
                ext_links = []
                for fp in extends_files:
                    link, e_lineno, e_end = _build_file_link(fp)
                    ext_links.append(link)
                    declaration_sites.append((fp, e_lineno, e_end))
                summary += f" Extended in: {', '.join(ext_links)}."
        else:
            # Fallback: zero or several files claim the 'declares' role --
            # either no filepath_roles data at all (older/unrebuilt graph)
            # or a genuine re-declaration across files, both edge cases the
            # per-file role cannot resolve unambiguously. Use the custom-first sort with a
            # single undifferentiated 'Declared in' list rather than guess.
            logger.warning(
                "Node [code_intelligence_agent]: trace_full_inheritance('%s') "
                "found %d file(s) with role='declares' (expected exactly 1) -- "
                "falling back to the pre-853 undifferentiated 'Declared in' "
                "listing for all %d file(s).",
                model_name, len(declares_files), len(filepaths),
            )
            sorted_filepaths = sorted(filepaths, key=lambda f: not _is_custom_module_filepath(f))
            src_links = []
            for fp in sorted_filepaths:
                link, lineno, end_line = _build_file_link(fp)
                src_links.append(link)
                declaration_sites.append((fp, lineno, end_line))
            summary += f" Declared in: {', '.join(src_links)}."

    return InheritanceChainResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        extension_parents=sorted(list(extension_parents)),
        delegation_parents=delegation_parents,
        full_ancestors=full_ancestors,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_inheritance_evidence(model_name, extension_parents, delegation_parents),
        declaration_sites=declaration_sites,
    )


# ── Cross-Domain Module Extensions ───────────────


@dataclass
class ModelExtensionInfo:
    model_name: str
    class_name: Optional[str] = None
    filepath: Optional[str] = None
    inherit: List[str] = field(default_factory=list)
    fields_added: List[str] = field(default_factory=list)
    methods_defined: List[str] = field(default_factory=list)
    is_core: bool = True
    degree: int = 0


def _is_technical_or_transient(model_name: str) -> bool:
    if any(model_name.startswith(p) for p in ("ir.", "res.config.", "onboarding.", "base.")):
        return True
    if any(s in model_name for s in ("wizard", "layout", "report", "populate")):
        return True
    return False


def _resolve_source_filepath(filepath_str: str) -> Optional[Path]:
    p = Path(filepath_str)
    if p.exists():
        return p
    if Path("/" + filepath_str).exists():
        return Path("/" + filepath_str)
    from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, _ROOT
    candidates = [
        Path(CUSTOM_ADDONS_PATH) / filepath_str if CUSTOM_ADDONS_PATH else None,
        Path(CORE_ADDONS_PATH) / filepath_str if CORE_ADDONS_PATH else None,
        _ROOT / filepath_str,
    ]
    try:
        return next((c for c in candidates if c and c.exists()), None)
    except OSError as err:
        logger.warning("Cannot resolve source file %s: %s", filepath_str, err)
        return None


def _extract_ast_class_info(filepath_str: str, target_model: str) -> Optional[dict]:
    p = _resolve_source_filepath(filepath_str)
    if not p:
        return None
    source = read_source_text(p)
    if source is None:
        return None
    tree = parse_python_text(source, p)
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            c_name = node.name
            _name = None
            _inherit: List[str] = []
            fields: List[str] = []
            methods: List[str] = []
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            if target.id == "_name":
                                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                    _name = stmt.value.value
                            elif target.id == "_inherit":
                                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                    _inherit = [stmt.value.value]
                                elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                                    _inherit = [
                                        el.value for el in stmt.value.elts
                                        if isinstance(el, ast.Constant) and isinstance(el.value, str)
                                    ]
                            elif isinstance(stmt.value, ast.Call):
                                func = stmt.value.func
                                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "fields":
                                    fields.append(target.id)
                elif isinstance(stmt, ast.AnnAssign):
                    if isinstance(stmt.target, ast.Name):
                        if stmt.target.id == "_name" and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            _name = stmt.value.value
                        elif stmt.target.id == "_inherit":
                            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                _inherit = [stmt.value.value]
                            elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                                _inherit = [
                                    el.value for el in stmt.value.elts
                                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                                ]
                        elif stmt.value and isinstance(stmt.value, ast.Call):
                            func = stmt.value.func
                            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "fields":
                                fields.append(stmt.target.id)
                elif isinstance(stmt, ast.FunctionDef):
                    methods.append(stmt.name)
            if _name == target_model or target_model in _inherit:
                return {
                    "class_name": c_name,
                    "inherit": _inherit,
                    "fields": fields,
                    "methods": methods,
                }
    return None


def inspect_module_cross_domain_extensions(G: nx.DiGraph, module_name: str) -> List[ModelExtensionInfo]:
    mod_node = f"module:{module_name}"
    if not G.has_node(mod_node):
        return []
    mod_prefix = module_name.split("_")[0]
    extensions: List[ModelExtensionInfo] = []

    for pred in sorted(G.predecessors(mod_node)):
        if not pred.startswith("model:"):
            continue
        edge = G.get_edge_data(pred, mod_node) or {}
        if edge.get("role") != "extends":
            continue
        m_name = pred.replace("model:", "")
        model_prefix = m_name.split(".")[0]
        if model_prefix == mod_prefix:
            continue

        node_data = G.nodes.get(pred, {})
        fp_roles = node_data.get("filepath_roles", {})
        target_fps = [fp for fp, r in fp_roles.items() if f"/{module_name}/" in fp and r == "extends"]
        if not target_fps:
            target_fps = [fp for fp in node_data.get("filepaths", []) if f"/{module_name}/" in fp]

        ext_info = ModelExtensionInfo(
            model_name=m_name,
            is_core=not _is_technical_or_transient(m_name),
            degree=G.degree(pred) if pred in G else 0,
        )
        if target_fps:
            fp = target_fps[0]
            ext_info.filepath = fp
            ast_data = _extract_ast_class_info(fp, m_name)
            if ast_data:
                ext_info.class_name = ast_data["class_name"]
                ext_info.inherit = ast_data["inherit"]
                ext_info.fields_added = ast_data["fields"]
                ext_info.methods_defined = ast_data["methods"]
        extensions.append(ext_info)

    # Sort core models first, then non-res business models first, then by node degree descending, then model name
    extensions.sort(key=lambda x: (not x.is_core, x.model_name.startswith("res."), -x.degree, x.model_name))
    return extensions


def format_module_cross_domain_extensions(extensions: List[ModelExtensionInfo], module_name: str) -> str:
    core_exts = [e for e in extensions if e.is_core]
    header = "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]"
    if not core_exts:
        tech_note = ""
        if extensions:
            tech_models = ", ".join(f"'{e.model_name}'" for e in extensions)
            tech_note = f" (il étend uniquement des modèles techniques/configuration : {tech_models})"
        return f"{header}\nLe module '{module_name}' n'étend aucun modèle métier natif hors de son propre périmètre{tech_note}."

    lines = [header, f"Le module '{module_name}' étend directement les modèles natifs suivants hors de son propre périmètre :"]
    for e in core_exts[:5]:
        rel_fp = e.filepath.split(f"/{module_name}/")[-1] if e.filepath and f"/{module_name}/" in e.filepath else (e.filepath or "inconnu")
        cls_str = f" (classe Python : `{e.class_name}` dans {rel_fp})" if e.class_name else ""
        lines.append(f"- Modèle '{e.model_name}'{cls_str} :")
        if e.inherit:
            lines.append(f"  * Héritage : _inherit = {e.inherit}")
        if e.fields_added:
            f_sorted = list(e.fields_added)
            f_sorted.sort(key=lambda f: (not ("available" in f or "qty" in f or "count" in f), f))
            f_preview = ", ".join(f_sorted[:6])
            lines.append(f"  * Champs ajoutés : {f_preview}")
        if e.methods_defined:
            m_sorted = list(e.methods_defined)
            m_sorted.sort(key=lambda m: (not (m in ("create", "write", "unlink") or "compute" in m), m))
            m_preview = ", ".join(m_sorted[:6])
            lines.append(f"  * Méthodes définies/surchargées : {m_preview}")
    return "\n".join(lines)
