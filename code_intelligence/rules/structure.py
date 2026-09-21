"""
code_intelligence/deterministic/field_impact.py

Multi-hop dependency and downstream impact analysis for computed fields in Odoo models.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import logging
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.ontology import tags_for_node_attrs
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
    # todo/contexte.txt section 831 (Famille 1, site 4/5): (filepath, lineno,
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
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
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
    business_parents = [p for p in extension_parents if p not in mixins]
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

    filepaths = G.nodes[model_node].get("filepaths", [])
    declaration_sites: List[Tuple[str, int, int]] = []
    if filepaths:
        from code_intelligence.agent.tool_helpers import _is_custom_module_filepath

        def _build_file_link(fp: str) -> Tuple[str, int, int]:
            """Locate the _name/_inherit line for model_name in fp and
            return (markdown_link, lineno, end_line). Unchanged logic from
            before section 853 -- only which files get labelled 'Declared
            in' vs 'Extended in' changed, not how a single file's link is
            built."""
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
                except Exception:
                    pass
            end_line = min(lineno + 80, line_count)
            link = f"[{p.name}:L{lineno}-L{end_line}](file://{fp}#L{lineno}-L{end_line})"
            return link, lineno, end_line

        # Section 822/853 (todo/contexte.txt): filepath_roles (graph/builder.py)
        # already knows, per FILE, whether that file declares (_name=, no
        # self-_inherit) or merely extends (_inherit=) the model -- computed
        # once at build time from the same per-declaration flag already
        # trusted for the module-level DEFINED_IN edges (verified clean in
        # section 822/823). Using it here means every file gets its own
        # correct label instead of the old behaviour, which slapped
        # "Declared in" on EVERY file matching a _name/_inherit regex
        # (declaration AND extension alike) and then relied on a
        # custom-first sort to put -- by pure luck, not correctness -- the
        # right one in front. A custom module extending the model would
        # match that regex too and could end up cited as if it declared the
        # model (confirmed on account.move, section 822).
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
            # Fallback (todo/contexte.txt section 853, point 1 of pmm's
            # mandate): zero or several files claim the 'declares' role --
            # either no filepath_roles data at all (older/unrebuilt graph)
            # or a genuine re-declaration across files, both edge cases the
            # per-file role cannot resolve unambiguously. Revert to the
            # pre-853 behaviour (custom-first sort, single undifferentiated
            # 'Declared in' list) rather than guess.
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


# ── Module-Extension Negation Guard (Section 838, point 4) ──────────────

# Ground-truth models a module EXTENDS (not declares), pulled from
# list_involved_modules' module-mode sentence: "Module 'X' defines or
# extends the following models: modelA (declares), modelB (extends), ...".
# Captures to end-of-line (not up to a closing '.') because this list can
# be long enough to hit the tool's own observation truncation cap before
# ever reaching the sentence's final period -- requiring that period would
# silently drop every entry, including the ones that arrived intact before
# the cut (verified directly on 'account', whose full list runs well past
# 3000 chars: the truncated observation never contains a trailing '.').
_MODULE_DEFINES_EXTENDS_RE = re.compile(
    r"Module '([\w.]+)' defines or extends the following models: (.+)"
)

# Sentence-level denial that a module extends anything outside its own
# perimeter (todo/contexte.txt sections 809-836, recurring on ACC-Q3/STK-Q3:
# "n'etend pas ... hors de son perimetre", "pas ... extension ... hors de").
# Operates on accent-folded, lowercased text -- same convention as
# overrides._OVERRIDE_COUNT_DENIAL_RE.
# Section 840: NO unbounded [^.\n]* prefix -- a model name like
# "account.move" contains a literal '.', so an open-ended prefix greedily
# anchored on the first '.' it finds would swallow whatever UNRELATED
# correct text sits between that '.' and the actual denial phrase later in
# the same sentence (reproduced directly: garbled "En resume,
# **account.En realite..." when the response's first clause -- correct --
# and its negation clause -- wrong -- share one comma-joined sentence).
# Section 842: this core regex only needs to reliably LOCATE the negation
# (bounded trailing windows are enough for that -- they don't need to reach
# the true sentence end); _neutralize_module_extension_denial below expands
# the located match out to real sentence boundaries via
# common.expand_to_sentence_bounds() before replacing, which is what fixes
# section 841's dangling-verb-stem problem without reintroducing 840's
# dotted-identifier problem (see the long comment in common.py for why
# neither an unbounded prefix nor a fixed-width window alone can satisfy
# both constraints at once).
# Section 856 (ACC-Q3, x3 rejeu post-853): the reflexive-only "ne s'etend
# pas" alternative missed the non-reflexive, decoration-wrapped variant
# "ne « étend » pas" -- observed verbatim in a Conclusion-section restatement
# of the same denial the guard had already fixed earlier in the SAME
# answer, left uncorrected and directly contradicting the fixed sentence.
# New alternative tolerates optional markdown/quote decoration and an
# optional reflexive "s'" between "ne" and "etend" and between "etend" and
# "pas".
_MODULE_EXTENSION_DENIAL_DECOR = r"[\s\u00ab\u00bb\"'*_]*"
_MODULE_EXTENSION_DENIAL_RE = re.compile(
    r"(?:n['\u2019]\s*etend\s+pas|ne\s+s['\u2019]?\s*etend\s+pas|ne\s+modifie\s+pas|"
    r"pas[^.\n]{0,20}extension|"
    rf"ne{_MODULE_EXTENSION_DENIAL_DECOR}s?['\u2019]?{_MODULE_EXTENSION_DENIAL_DECOR}etend"
    rf"{_MODULE_EXTENSION_DENIAL_DECOR}pas)[^.\n]{{0,80}}(?:perimetre|hors\s+de|en\s+dehors\s+de)[^.\n]{{0,40}}"
)


def _extract_module_extended_models(raw_tool_output: str, module_name: str = "") -> List[str]:
    """Models a module EXTENDS (role 'extends', not 'declares'), read from
    list_involved_modules' module-mode output. Optionally scoped to one
    module when several module-mode calls appear in the same turn."""
    extended: List[str] = []
    for mod, entries_str in _MODULE_DEFINES_EXTENDS_RE.findall(raw_tool_output):
        if module_name and mod != module_name:
            continue
        for entry in entries_str.rstrip(".").split(","):
            entry = entry.strip()
            if entry.endswith("(extends)"):
                model = entry[: -len("(extends)")].strip()
                if model and model not in extended:
                    extended.append(model)
    return extended


def _answer_denies_module_extension(final_answer: str) -> bool:
    """True if final_answer explicitly claims the module extends nothing
    outside its own perimeter."""
    from code_intelligence.rules.group_resolver import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_MODULE_EXTENSION_DENIAL_RE.search(folded))


def _answer_lacks_extension_coverage(final_answer: str, extended_models: List[str], threshold: float = 0.3) -> bool:
    """True if final_answer mentions fewer than `threshold` of the real
    extended_models list -- a GENERIC, wording-independent signal
    (todo/contexte.txt section 858) of the same underlying defect
    _answer_denies_module_extension targets (the synthesis denies or omits
    that this module extends models outside its own perimeter), but based
    on fact COVERAGE rather than matching a fixed, ever-growing list of
    negation verbs/synonyms -- which section 840's fix, then 841, 842/843,
    844, 856 and 857 each extended and each was outrun by yet another
    phrasing the LLM produced ("n'etend pas", "ne s'etend pas", "il ne
    s'agit pas d'une extension", "ne depend pas", ...). A synthesis that
    correctly states the fact will naturally cite most or all of the real
    model names (the guard's own replacement text does, verbatim); one
    that denies OR silently omits the fact will cite few or none of them,
    regardless of which words it used to do so -- closing the loop that
    kept reopening on wording, and incidentally covering the STK-Q3
    omission variant (section 821, point 4) this project's guard family
    never targeted before. Coverage is computed on accent-folded,
    lowercased text, same convention as the rest of this guard family."""
    if not extended_models:
        return False
    from code_intelligence.rules.group_resolver import _fold_accents
    folded_answer = _fold_accents(final_answer.lower())
    mentioned = sum(1 for m in extended_models if _fold_accents(m.lower()) in folded_answer)
    return (mentioned / len(extended_models)) < threshold


def _neutralize_module_extension_denial(final_answer: str, extended_models: List[str]) -> str:
    """Replace EVERY sentence containing the out-of-perimeter denial with the
    real extended-model list -- expanding each match out to real sentence
    boundaries (see common.expand_to_sentence_bounds) rather than replacing
    just the matched negation fragment, so no dangling verb/subject stem
    (e.g. "il ne s'agit ") is ever left immediately before the replacement
    (todo/contexte.txt section 841).

    Section 856: a structured answer (Nature/Héritage/Conclusion-style)
    frequently restates the same wrong denial in more than one section --
    fixing only the FIRST occurrence (the old behavior) leaves a later
    restatement directly contradicting the sentence this function just
    corrected, producing a self-contradictory final answer. All matches in
    the same turn are now replaced, not just the first.
    """
    from code_intelligence.rules.group_resolver import _fold_accents
    from code_intelligence.rules.common import expand_to_sentence_bounds
    folded = _fold_accents(final_answer.lower())
    matches = list(_MODULE_EXTENSION_DENIAL_RE.finditer(folded))
    if not matches:
        return final_answer

    models_list = ", ".join(f"'{m}'" for m in extended_models)
    replacement = (
        f"En réalité, ce module étend bien {len(extended_models)} modèle(s) "
        f"hors de son propre périmètre : {models_list}."
    )

    # Expand every match to real sentence bounds, then merge any spans that
    # end up overlapping/adjacent (two matches landing in the same sentence)
    # so that sentence is replaced exactly once, not twice back-to-back.
    spans = sorted(expand_to_sentence_bounds(folded, *m.span()) for m in matches)
    merged: List[List[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    # Replace from the last span to the first so earlier offsets stay valid.
    out = final_answer
    for start, end in reversed(merged):
        out = out[:start] + replacement + out[end:]
    return out


def _correct_module_extension_contradiction(final_answer: str, raw_tool_output: str, question: str = "") -> str:
    """Section 838 (point 4, ACC-Q3/STK-Q3 negation pattern documented in
    todo/contexte.txt sections 809-836): mirrors
    overrides._correct_override_cascade_contradictions. Prompt instructions
    alone were repeatedly shown not to prevent this exact pattern (section
    825) -- only a post-hoc mechanical correction against
    list_involved_modules' own structured (extends) findings reliably
    catches it."""
    if question:
        from code_intelligence.agent.context_extractors import _question_is_inheritance_related
        if not _question_is_inheritance_related(question):
            return final_answer

    extended = _extract_module_extended_models(raw_tool_output)
    if not extended:
        return final_answer

    if _answer_denies_module_extension(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis denied that the "
            "module extends any model outside its own perimeter while "
            "list_involved_modules reported %d such extension(s) -- "
            "replacing the denial sentence with the real module list: %s",
            len(extended), extended,
        )
        final_answer = _neutralize_module_extension_denial(final_answer, extended)

    return final_answer
