"""ORM tools for sales queries (total, count, average, details)."""

from typing import List, Tuple

from langchain_core.tools import tool

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import record_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
    normalize_client_name, is_all_clients, client_label,
    build_sale_domain, resolve_statut, parse_period,
    narrow_to_one_entity, ambiguity_text,
)
from erp_data.monetary import (
    averages_by_currency,
    currency_code,
    format_amount,
    format_totals,
    totals_by_currency,
)


def get_total_sales_raw(client: str = "", periode: str = "", statut: str = "toutes") -> Tuple[str, List[Evidence]]:
    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    label = client_label(client)

    results = connector.read_group(
        uid=uid, model="sale.order", domain=domain,
        fields=["amount_total:sum"], groupby=["currency_id"],
    )

    if not results:
        text = f"Aucune vente trouvée{label}.\nScope : {scope_label}"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches client={client or 'all'}, period={periode or 'all'}, statut={statut}",
            source="sale.order:read_group(amount_total:sum, groupby=currency_id)",
            value=None, scope=scope,
        )
        return text, [evidence]

    totals = totals_by_currency(results, "amount_total")
    total_text = format_totals(totals)
    text = (
        f"Total des ventes{label}\n"
        f"Scope : {scope_label}\n"
        f"Total : {total_text}\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=(
                f"Total sales amount for currency={currency or 'unspecified'}, "
                f"client={client or 'all'}, period={periode or 'all'}, statut={statut}"
            ),
            source="sale.order:read_group(amount_total:sum, groupby=currency_id)",
            value={"currency": currency, "amount": amount}, scope=scope,
        )
        for currency, amount in totals
    ]
    return text, evidences


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
    from erp_data.runtime.read_tools import orm_search_count
    from erp_data.tools._runtime import runtime_scope

    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)
    label = client_label(client)

    counted = orm_search_count("sale.order", domain=domain)
    scope = runtime_scope(counted)
    count = counted.evidence[0].value if counted.evidence else 0

    text = (
        f"Nombre de commandes{label}\n"
        f"Scope : {scope_label}\n"
        f"Nombre : {count}\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Order count for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
        source="sale.order:search_count",
        value=count,
        scope=scope,
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


def get_average_sales_raw(client: str = "", periode: str = "toutes", statut: str = "toutes") -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    states, scope_label = resolve_statut(statut)
    domain = build_sale_domain(client, periode, states)
    groupby = ["partner_id", "currency_id"] if not is_all_clients(client) else ["currency_id"]
    source = f"sale.order:read_group(amount_total:sum, groupby={','.join(groupby)})"

    results = connector.read_group(
        uid=uid, model="sale.order", domain=domain,
        fields=["amount_total:sum"],
        groupby=groupby,
        lazy=False,
    )

    if not results:
        text = f"Aucune vente trouvée pour calculer la moyenne.\nScope : {scope_label}"
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches to compute average for client={client or 'all'}, period={periode or 'all'}, statut={statut}",
            source=source,
            value=None, scope=scope,
        )
        return text, [evidence]

    if not is_all_clients(client):
        narrowed, candidates = narrow_to_one_entity(results, "partner_id", client)
        if candidates:
            text = ambiguity_text("clients", client, candidates)
            return text, []
        if not narrowed:
            text = f"Aucune vente trouvée pour calculer la moyenne pour '{client}'."
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim=f"No sale.order found for client={client}",
                source=source,
                value=None, scope=scope,
            )
            return text, [evidence]
        results = narrowed

    averages = averages_by_currency(results, "amount_total")
    if not averages:
        raise ValueError("Odoo read_group returned no record counts; average cannot be computed safely.")
    average_text = format_totals([(currency, average) for currency, average, _ in averages])
    count = sum(count for _, _, count in averages)

    if is_all_clients(client):
        label = "Moyenne des ventes"
    else:
        client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
        label = f"Moyenne des ventes pour {client_name}"

    text = (
        f"{label}\n"
        f"Scope : {scope_label}\n"
        f"Nombre : {count}\n"
        f"Moyenne : {average_text}\n"
        f"[Source: Odoo ERP - Module Ventes (sale.order)]"
    )
    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=(
                f"Average sale amount for currency={currency or 'unspecified'}, "
                f"client={client or 'all'}, period={periode or 'all'}, statut={statut}"
            ),
            source=source,
            value={"currency": currency, "average": average, "count": currency_count},
            scope=scope,
        )
        for currency, average, currency_count in averages
    ]
    return text, evidences


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
    fields = ["name", "partner_id", "date_order", "amount_total", "currency_id", "state", "order_line"]
    order_source = "sale.order:search_read(name,state,partner_id,amount_total,currency_id)"

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

    totals = totals_by_currency(records, "amount_total")
    total_fmt = format_totals(totals)
    result_lines = [
        f"Détails des commandes / devis pour {client or 'tous les clients'} (Total: {total_fmt}, {len(records)} commande(s)) :"
    ]
    evidences = []
    for r in records:
        client_name = r["partner_id"][1] if r.get("partner_id") else "Inconnu"
        amount = r.get("amount_total", 0.0)
        currency = currency_code(r)
        amount_fmt = format_amount(amount, currency, grouped=True)
        state_raw = r.get("state", "inconnu")
        state_fr = _STATE_LABELS.get(state_raw, state_raw)
        name = r.get("name", "inconnu")

        evidences.append(make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Order details for name={name}",
            source=used_source,
            value={"state": state_raw, "partner": client_name, "amount": amount, "currency": currency},
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
        result_lines.append(f"- Commande {name} ({state_fr}) pour {client_name} : {amount_fmt}. Produits : {prod_str}")

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


_TOP_PRODUCTS_SOURCE = (
    "sale.order.line:read_group(product_uom_qty:sum,price_subtotal:sum, "
    "groupby=product_id,currency_id)"
)


def get_top_selling_products_raw(
    periode: str = "", statut: str = "toutes", metrique: str = "quantite", limite: int = 5,
) -> Tuple[str, List[Evidence]]:
    states, scope_label = resolve_statut(statut)
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    effective_limit = limite if limite and limite > 0 else 5

    domain = [("order_id.state", "in", states)]
    date_range = parse_period(periode) if periode else None
    if date_range:
        domain.append(("order_id.date_order", ">=", date_range[0]))
        end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
        domain.append(("order_id.date_order", "<=", end_str))

    results = connector.read_group(
        uid=uid, model="sale.order.line", domain=domain,
        fields=["product_uom_qty:sum", "price_subtotal:sum"],
        groupby=["product_id", "currency_id"],
        lazy=False,
    )

    rows = {}
    for result in results:
        product = result.get("product_id")
        if not product:
            continue
        product_id, name = product
        currency = currency_code(result)
        aggregate = rows.setdefault(
            product_id,
            {"name": name, "quantity": 0.0, "revenue": {}},
        )
        aggregate["quantity"] += float(result.get("product_uom_qty") or 0.0)
        aggregate["revenue"][currency] = (
            aggregate["revenue"].get(currency, 0.0)
            + float(result.get("price_subtotal") or 0.0)
        )

    period_label = periode or "toute la période"

    if not rows:
        text = (
            f"Aucune ligne de vente trouvée.\n"
            f"Scope : {scope_label}, période : {period_label}."
        )
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order.line matches statut={statut}, period={periode or 'all'}",
            source=_TOP_PRODUCTS_SOURCE, value=None, scope=scope,
        )
        return text, [evidence]

    rank_by_amount = metrique.lower().strip() in ("montant", "chiffre d'affaires", "ca", "revenu")
    metric_label = "chiffre d'affaires" if rank_by_amount else "quantité vendue"
    lines = [f"Top produits par {metric_label} ({scope_label}, période : {period_label}) :"]
    evidences = []
    if rank_by_amount:
        currencies = sorted({
            currency
            for values in rows.values()
            for currency in values["revenue"]
        })
        for currency in currencies:
            ranked = sorted(
                (
                    item for item in rows.items()
                    if currency in item[1]["revenue"]
                ),
                key=lambda item: item[1]["revenue"].get(currency, 0.0),
                reverse=True,
            )[:effective_limit]
            lines.append(f"Devise {currency or 'non précisée'} :")
            for rank, (_, values) in enumerate(ranked, start=1):
                name = values["name"]
                amount = values["revenue"].get(currency, 0.0)
                amount_fmt = format_amount(amount, currency, grouped=True)
                lines.append(f"{rank}. {name} -- {amount_fmt}")
                evidences.append(make_evidence(
                    source_type=EvidenceSourceType.ORM,
                    claim=f"Product {name} revenue in currency={currency or 'unspecified'}, statut={statut}, period={periode or 'all'}",
                    source=_TOP_PRODUCTS_SOURCE,
                    value={"currency": currency, "revenue": amount},
                    scope=scope,
                ))
    else:
        ranked = sorted(
            rows.items(),
            key=lambda item: item[1]["quantity"],
            reverse=True,
        )[:effective_limit]
        for rank, (_, values) in enumerate(ranked, start=1):
            name = values["name"]
            qty_fmt = f"{values['quantity']:,.2f}".replace(",", " ")
            revenue_text = format_totals(sorted(values["revenue"].items()), grouped=True)
            lines.append(f"{rank}. {name} -- {qty_fmt} unité(s) vendue(s), {revenue_text}")
            for currency, amount in sorted(values["revenue"].items()):
                evidences.append(make_evidence(
                    source_type=EvidenceSourceType.ORM,
                    claim=f"Product {name}: quantity_sold={values['quantity']}, revenue in currency={currency or 'unspecified'}, statut={statut}, period={periode or 'all'}",
                    source=_TOP_PRODUCTS_SOURCE,
                    value={"quantity": values["quantity"], "currency": currency, "revenue": amount},
                    scope=scope,
                ))
    lines.append("[Source: Odoo ERP - Module Ventes (sale.order.line)]")
    return "\n".join(lines), evidences


@tool
def get_top_selling_products(
    periode: str = "", statut: str = "toutes", metrique: str = "quantite", limite: int = 5,
) -> str:
    """Get the top N best-selling products, ranked by quantity sold or revenue.

    Use this tool for any question asking for a ranking/ranked list of
    products (e.g. "top 5 produits les plus vendus", "quel produit se vend
    le mieux ce mois-ci"). Do NOT approximate this with get_sale_details,
    which only lists raw orders and cannot rank or aggregate by product.

    Args:
        periode: Time period filter (e.g. 'ce mois', '2025', 'Q1 2026'). Leave empty for all time.
        statut: Order status filter ('confirmees', 'brouillon', 'toutes'). Default: 'toutes'.
        metrique: Ranking metric -- 'quantite' (units sold, default) or 'montant' (revenue).
        limite: Number of top products to return. Default: 5.
    """
    try:
        text, evidence = get_top_selling_products_raw(periode, statut, metrique, limite)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors du calcul des produits les plus vendus : {str(e)}"
