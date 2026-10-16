"""Report (ir.actions.report), MailTemplate (mail.template) and HttpRoute (@http.route) nodes and their edges."""

from dataclasses import replace
from typing import Dict

import networkx as nx

from code_intelligence.utils import qualify_xml_id

from .nodes import ParsedModule, ResolvedSymbolRegistry


def _merge(existing, new):
    """A later record overriding the same id keeps its non-empty values; list values are unioned."""
    values = {}
    for name, value in vars(new).items():
        old = getattr(existing, name)
        if isinstance(value, list):
            values[name] = list(dict.fromkeys([*old, *value]))
        elif isinstance(value, bool):
            values[name] = old and value  # a bare override cannot re-enable: only an explicit disable is kept
        elif value not in ("", None):
            values[name] = value
        else:
            values[name] = old
    return replace(existing, **values)


def _collect(modules_dict: Dict[str, ParsedModule], attribute: str) -> dict:
    merged: dict = {}
    for module_name, module in modules_dict.items():
        for record in getattr(module, attribute):
            full_id = qualify_xml_id(record.xml_id, module_name)
            merged[full_id] = _merge(merged[full_id], record) if full_id in merged else record
    return merged


def add_http_route_nodes(G: nx.DiGraph, modules_dict: Dict[str, ParsedModule]) -> None:
    for module_name, module in modules_dict.items():
        for route in module.http_routes:
            node_id = f"route:{module_name}.{route.controller}.{route.method_name}"
            if node_id in G:
                continue
            G.add_node(
                node_id,
                node_type="HttpRoute",
                module=module_name,
                controller=route.controller,
                method_name=route.method_name,
                paths=list(route.paths),
                route_type=route.route_type,
                auth=route.auth,
                methods=list(route.methods),
                website=route.website,
                csrf=route.csrf,
                overrides_parent=route.overrides_parent,
                filepath=route.filepath,
                lineno=route.lineno,
                behavioral_tags=[],
                technical_tags=[],
            )


def add_report_and_template_nodes(G: nx.DiGraph, registry: ResolvedSymbolRegistry, modules_dict: Dict[str, ParsedModule]) -> None:
    reports = _collect(modules_dict, "reports")
    for full_id, report in reports.items():
        module = full_id.split(".", 1)[0]
        binding = (
            registry.resolve_model_ref_or_record(report.binding_model_id, module, report.filepath)
            if report.binding_model_id else None
        )
        target = report.model if report.model in registry.models else binding
        node_id = f"report:{full_id}"
        G.add_node(
            node_id,
            node_type="Report",
            xml_id=full_id,
            name=report.name,
            model=report.model,
            target_model=target or "",
            binding_model=binding or "",
            report_type=report.report_type,
            report_name=report.report_name,
            print_report_name=report.print_report_name,
            filepath=report.filepath,
            lineno=report.lineno,
            behavioral_tags=[],
            technical_tags=[],
        )
        if target is not None:
            G.add_edge(node_id, f"model:{target}", edge_type="REPORTS_ON")
        for group_ref in report.groups_id:
            G.add_edge(node_id, f"group:{qualify_xml_id(group_ref, module)}", edge_type="APPLIES_TO_GROUP")

    for full_id, template in _collect(modules_dict, "mail_templates").items():
        module = full_id.split(".", 1)[0]
        target = registry.resolve_model_ref_or_record(template.model_id, module, template.filepath) if template.model_id else None
        node_id = f"mail_template:{full_id}"
        G.add_node(
            node_id,
            node_type="MailTemplate",
            xml_id=full_id,
            name=template.name,
            model_id=template.model_id,
            target_model=target or "",
            subject=template.subject,
            template_description=template.description,
            email_from=template.email_from,
            email_to=template.email_to,
            partner_to=template.partner_to,
            lang=template.lang,
            active=template.active,
            filepath=template.filepath,
            lineno=template.lineno,
            behavioral_tags=[],
            technical_tags=[],
        )
        if target is not None:
            G.add_edge(node_id, f"model:{target}", edge_type="TEMPLATE_FOR")
        for report_ref in template.report_template_ids:
            report_id = qualify_xml_id(report_ref, module)
            if report_id in reports:
                G.add_edge(node_id, f"report:{report_id}", edge_type="ATTACHES_REPORT")
