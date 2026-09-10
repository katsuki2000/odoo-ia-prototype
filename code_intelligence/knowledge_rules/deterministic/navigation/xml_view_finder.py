"""
code_intelligence/deterministic/xml_view_finder.py

XML form view inspection for field definitions, labels, and UI constraints
(readonly, invisible, required, groups).
"""

from pathlib import Path
import re
from typing import List, Optional
import xml.etree.ElementTree as ET
import networkx as nx

from code_intelligence.knowledge_rules.deterministic.navigation.button_path_models import ButtonExecutionPathResult
from code_intelligence.utils import format_file_link, format_xml_id_citations


def _find_field_in_xml_views(
    G: nx.DiGraph,
    model_name: str,
    field_identifier: str,
    user_groups: Optional[List[str]] = None,
) -> Optional[ButtonExecutionPathResult]:
    """Search XML form views for field definitions matching field_identifier (name or label)
    and extract UI constraints (readonly, invisible, required, groups)."""
    clean_id = field_identifier.strip().lower()
    matched_field_name = None
    matched_field_label = None

    model_node = f"model:{model_name}"
    if model_node in G:
        for _, v, d in G.out_edges(model_node, data=True):
            if d.get("edge_type") == "HAS_FIELD":
                fnode = G.nodes.get(v, {})
                fname = fnode.get("name", "")
                flabel = fnode.get("label", "")
                if clean_id in (fname.lower(), flabel.lower()):
                    matched_field_name = fname
                    matched_field_label = flabel or fname
                    break

    if not matched_field_name and model_node in G:
        FR_EN = {
            "nom": "name", "personnalise": "custom", "personnalisé": "custom",
            "section": "section", "facture": "invoice", "factures": "invoice",
            "vente": "sale", "commande": "order", "type": "type",
            "statut": "state", "etat": "state", "état": "state",
            "date": "date", "montant": "amount", "prix": "price",
            "societe": "company", "société": "company", "partenaire": "partner",
            "ligne": "line", "lignes": "line", "champ": "field",
        }
        words = set(re.findall(r"\w+", clean_id.lower()))
        en_words = {FR_EN.get(w, w) for w in words} | words
        candidates = []
        for _, v, d in G.out_edges(model_node, data=True):
            if d.get("edge_type") == "HAS_FIELD":
                fnode = G.nodes.get(v, {})
                fname = fnode.get("name", "")
                flabel = fnode.get("label", "")
                ftokens = set(re.findall(r"\w+", fname.lower())) | set(re.findall(r"\w+", flabel.lower()))
                score = len(en_words & ftokens)
                if score > 1:
                    candidates.append((score, fname, flabel))
        if candidates:
            candidates.sort(reverse=True, key=lambda c: c[0])
            matched_field_name = candidates[0][1]
            matched_field_label = candidates[0][2] or matched_field_name

    if not matched_field_name:
        if clean_id.replace("_", "").isalnum():
            matched_field_name = clean_id
            matched_field_label = field_identifier

    if not matched_field_name:
        return None

    candidate_dirs = set()
    for m_node, m_data in G.nodes(data=True):
        if m_data.get("node_type") == "Module":
            mfp = m_data.get("filepath")
            if mfp:
                vdir = Path(mfp).parent / "views"
                if vdir.exists():
                    candidate_dirs.add(vdir)

    view_matches = []
    for vdir in candidate_dirs:
        for xml_file in vdir.glob("*.xml"):
            try:
                content = xml_file.read_text(encoding="utf-8")
                if f'name="{matched_field_name}"' not in content and f"name='{matched_field_name}'" not in content:
                    continue
                root = ET.fromstring(content)
                for rec in root.findall(".//record"):
                    if rec.attrib.get("model") != "ir.ui.view":
                        continue
                    rec_id = rec.attrib.get("id", "")
                    parent_map = {c: p for p in rec.iter() for c in p}
                    for fld in rec.findall(f'.//field[@name="{matched_field_name}"]'):
                        attrs = dict(fld.attrib)
                        curr = fld
                        ancestor_with_constraints = None
                        while curr in parent_map:
                            curr = parent_map[curr]
                            for k in ("groups", "invisible", "readonly", "required"):
                                if k in curr.attrib and k not in attrs:
                                    attrs[k] = curr.attrib[k]
                                    if not ancestor_with_constraints:
                                        ancestor_with_constraints = curr
                        if "readonly" in attrs or "invisible" in attrs or "required" in attrs or "groups" in attrs:
                            lines = content.splitlines()
                            ln = 1
                            ancestor_name = ancestor_with_constraints.attrib.get("name", "") if ancestor_with_constraints is not None else ""
                            for idx, l in enumerate(lines, 1):
                                if ancestor_name and f'name="{ancestor_name}"' in l:
                                    ln = idx
                                    break
                                if f'name="{matched_field_name}"' in l or f"name='{matched_field_name}'" in l:
                                    ln = idx
                                    break
                            link = format_file_link(str(xml_file), ln, min(len(lines), ln + 6))
                            view_matches.append((rec_id, str(xml_file), ln, attrs, link))
            except Exception:
                continue

    if not view_matches:
        return None

    view_matches.sort(key=lambda x: (0 if ("/addons/" not in x[1] or "oca" in x[1]) else 1, x[0]))
    rec_id, xml_file, ln, attrs, link = view_matches[0]

    readonly_cond = attrs.get("readonly", "")
    invisible_cond = attrs.get("invisible", "")
    required_cond = attrs.get("required", "")
    groups_cond = attrs.get("groups", "")

    steps = [
        f"1. UI Field Declaration: Champ '{matched_field_name}' ({matched_field_label}) dans la vue '{rec_id}' (modèle '{model_name}').",
        f"2. Source XML: Déclaré dans {link}.",
    ]
    if readonly_cond:
        steps.append(f"3. Condition Readonly: readonly=\"{readonly_cond}\" -- le champ devient non modifiable sous cette condition.")
    if required_cond:
        steps.append(f"4. Condition Required: required=\"{required_cond}\".")
    if invisible_cond:
        steps.append(f"5. Condition Invisible: invisible=\"{invisible_cond}\".")
    if groups_cond:
        _grp_citations = format_xml_id_citations([g.strip() for g in groups_cond.split(",") if g.strip()])
        steps.append(f"6. Groupes requis: groups=\"{groups_cond}\" ({_grp_citations}).")

    summary_parts = [
        f"Champ '{matched_field_name}' ({matched_field_label}) sur la vue '{rec_id}' ({link}) du modèle '{model_name}':"
    ]
    if readonly_cond:
        summary_parts.append(f"Non modifiable (readonly) lorsque: readonly=\"{readonly_cond}\".")
    if required_cond:
        summary_parts.append(f"Requis lorsque: required=\"{required_cond}\".")
    if invisible_cond:
        summary_parts.append(f"Invisible lorsque: invisible=\"{invisible_cond}\".")
    if groups_cond:
        _grp_citations = format_xml_id_citations([g.strip() for g in groups_cond.split(",") if g.strip()])
        summary_parts.append(f"Restreint aux groupes: [{groups_cond}] ({_grp_citations}).")
    else:
        summary_parts.append("Aucune restriction par groupe sur ce champ.")

    req_groups_list = [g.strip() for g in groups_cond.split(",") if g.strip()] if groups_cond else []
    return ButtonExecutionPathResult(
        button_identifier=field_identifier,
        model_name=model_name,
        method_name="",
        origin_states=[],
        target_state="",
        required_groups=req_groups_list,
        execution_steps=steps,
        summary_text=" ".join(summary_parts),
        evidence=[],
    )
