"""ORM tools for sales queries (total, count, average, details)."""

from typing import List, Tuple

from langchain_core.tools import tool

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence_collector import record_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
    normalize_client_name, is_all_clients, client_label,
    build_sale_domain, resolve_statut,
)
from erp_data._odoo_helpers import parse_period


def get_total_sales_raw(client: str = "", periode: str = "", statut: str = "toutes") -> Tuple[str, Evidence]:
    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    label = client_label(client)

    results = connector.read_group(
        uid=uid, model="sale.order", domain=domain,
        fields=["amount_total:sum"], groupby=[],
    )

    if not results or not results[0].get("amount_total"):
        text = f"Aucune vente trouvée{label}.\nScope : {scope_label}"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches client={client or 'all'}, period={periode or 'all'}, statut={statut}",
            source="sale.order:read_group(amount_total:sum)",
            value=None, scope=scope,
        )
        return text, evidence

    total = results[0]["amount_total"]
    text = (
        f"Total des ventes{label}\n"
        f"Scope : {scope_label}\n"
        f"Total : {total:.2f} Ar\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total sales amount for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
        source="sale.order:read_group(amount_total:sum)",
        value=total, scope=scope,
    )
    return text, evidence


@tool
def get_total_sales(client: str = "", periode: str = "", statut: str = "toutes") -> str:
    """Get total sales amount filtered by client, period, and status.

    Args:
        client: Client name. Leave empty or "tous" for all clients.
        periode: Time period filter (e.g. 'ce mois', '2025'). Leave empty for all time.
        statut: Order status ('confirmees', 'brouillon', 'annulees', 'toutes'). Default: 'toutes'.
    """
    text, evidence = get_total_sales_raw(client, periode, statut)
    record_evidence(evidence)
    return text


def get_order_count_raw(client: str = "", periode: str = "", statut: str = "toutes") -> Tuple[str, Evidence]:
    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    label = client_label(client)

    results = connector.read_group(
        uid=uid, model="sale.order", domain=domain,
        fields=[], groupby=[],
    )
    count = results[0].get("__count", 0) if results else 0

    text = (
        f"Nombre de commandes{label}\n"
        f"Scope : {scope_label}\n"
        f"Nombre : {count}\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Order count for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
        source="sale.order:read_group(__count)",
        value=count, scope=scope,
    )
    return text, evidence


@tool
def get_order_count(client: str = "", periode: str = "", statut: str = "toutes") -> str:
    """Get the number of sales orders filtered by client, period, and status.

    Args:
        client: Client name. Leave empty or "tous" for all clients.
        periode: Time period filter. Leave empty for all time.
        statut: Order status ('confirmees', 'brouillon', 'annulees', 'toutes'). Default: 'toutes'.
    """
    try:
        text, evidence = get_order_count_raw(client, periode, statut)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors du comptage des commandes : {str(e)}"


def get_average_sales_raw(client: str = "", periode: str = "toutes", statut: str = "toutes") -> Tuple[str, Evidence]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)

    results = connector.read_group(
        uid=uid, model="sale.order", domain=domain,
        fields=["amount_total:avg"],
        groupby=["partner_id"] if not is_all_clients(client) else [],
    )

    if not results:
        text = f"Aucune vente trouvée pour calculer la moyenne.\nScope : {scope_label}"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches to compute average for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
            source="sale.order:read_group(amount_total:avg)",
            value=None, scope=scope,
        )
        return text, evidence

    moyenne = results[0].get("amount_total", 0.0)
    count = results[0].get("__count", 0)
    if is_all_clients(client):
        label = "Moyenne des ventes"
    else:
        client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
        label = f"Moyenne des ventes pour {client_name}"

    text = (
        f"{label}\n"
        f"Scope : {scope_label}\n"
        f"Nombre : {count}\n"
        f"Moyenne : {moyenne:.2f} Ar\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Average sale amount for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
        source="sale.order:read_group(amount_total:avg)",
        value=moyenne, scope=scope,
    )
    return text, evidence


@tool
def get_average_sales(client: str = "", periode: str = "toutes", statut: str = "toutes") -> str:
    """Get average sale amount for a client or overall.

    Args:
        client: Client name (Optional).
        periode: Time period (Optional).
        statut: Order status ('confirmees', 'brouillon', 'annulees', 'toutes'). Default: 'toutes'.
    """
    try:
        text, evidence = get_average_sales_raw(client, periode, statut)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors du calcul de la moyenne : {str(e)}"


_STATE_LABELS = {
    "draft": "Devis en cours", "sent": "Devis envoyé",
    "sale": "Vente confirmée", "done": "Vente confirmée",
    "cancel": "Commande annulée",
}


def get_sale_details_raw(client: str = "", statut: str = "toutes", limite: int = 0) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    effective_limit = 0 if limite <= 1 else limite
    fields = ["name", "partner_id", "date_order", "amount_total", "state", "order_line"]
    order_source = "sale.order:search_read(name,state,partner_id,amount_total)"

    if statut.lower() in ["brouillon", "en cours"]:
        domain = [("state", "in", ["draft", "sent"])]
    elif statut.lower() in ["confirmé", "confirmees", "confirmées"]:
        domain = [("state", "in", ["sale", "done"])]
    elif statut.lower() in ["annulé", "annule", "cancel"]:
        domain = [("state", "=", "cancel")]
    else:
        domain = [("state", "!=", "cancel")]

    if not is_all_clients(client):
        domain.append(("partner_id.name", "ilike", normalize_client_name(client)))

    primary_source = f"{order_source}[domaine=statut]"
    records = connector.search_read(
        uid=uid, model="sale.order", domain=domain,
        fields=fields, limit=effective_limit,
    )
    used_source = primary_source

    fallback_attempted = False
    fallback_source = None
    if not records and statut.lower() != "toutes":
        fallback_attempted = True
        fb_domain = [("state", "!=", "cancel")]
        if not is_all_clients(client):
            fb_domain.append(("partner_id.name", "ilike", normalize_client_name(client)))
        fallback_source = f"{order_source}[domaine=state!=cancel (repli)]"
        records = connector.search_read(
            uid=uid, model="sale.order", domain=fb_domain,
            fields=fields, limit=effective_limit,
        )
        used_source = fallback_source

    if not records:
        neg_source = f"{primary_source} [empty] ; {fallback_source} [empty]" if fallback_attempted else f"{primary_source} [empty]"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches client={client or 'all'}, statut={statut}",
            source=neg_source, value=None, scope=scope,
        )
        return f"Aucune vente trouvée pour {client or 'tous les clients'}.", [evidence]

    total_sum = sum(r.get("amount_total", 0.0) for r in records)
    total_fmt = f"{total_sum:,.2f}".replace(",", " ")
    result_lines = [
        f"Détails des commandes / devis pour {client or 'tous les clients'} (Total: {total_fmt} Ar, {len(records)} commande(s)) :"
    ]
    evidences = []
    for r in records:
        client_name = r["partner_id"][1] if r.get("partner_id") else "Inconnu"
        amount = r.get("amount_total", 0.0)
        amount_fmt = f"{amount:,.2f}".replace(",", " ")
        state_raw = r.get("state", "inconnu")
        state_fr = _STATE_LABELS.get(state_raw, state_raw)
        name = r.get("name", "inconnu")

        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Order details for name={name}",
            source=used_source,
            value={"state": state_raw, "partner": client_name, "amount": amount},
            scope=scope,
        ))

        line_ids = r.get("order_line", [])
        produits = []
        if line_ids:
            lines = connector.search_read(
                uid=uid, model="sale.order.line",
                domain=[("id", "in", line_ids)], fields=["product_id"],
            )
            produits = [ln["product_id"][1] for ln in lines if ln.get("product_id")]
            products_source = "sale.order.line:search_read(product_id)"
        else:
            products_source = "sale.order:search_read(order_line)"

        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Products for order name={name}",
            source=products_source, value=produits, scope=scope,
        ))
        prod_str = ", ".join(produits) if produits else "Aucun produit"
        result_lines.append(f"- Commande {name} ({state_fr}) pour {client_name} : {amount_fmt} Ar. Produits : {prod_str}")

    result_lines.append("[Source: Odoo ERP - Module Ventes (sale.order)]")
    return "\n".join(result_lines), evidences


@tool
def get_sale_details(client: str = "", statut: str = "toutes", limite: int = 0) -> str:
    """Get sale order details (products, amounts) for a client.

    Args:
        client: Client name.
        statut: Order status ('confirme', 'brouillon', 'toutes'). Default: 'toutes'.
        limite: Max orders to return (0 for all). Default: 0.
    """
    try:
        text, evidence = get_sale_details_raw(client, statut, limite)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des détails : {str(e)}"
