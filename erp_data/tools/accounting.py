"""ORM tools for invoice and revenue queries."""

from typing import List, Tuple

from langchain_core.tools import tool

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence_collector import record_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
    normalize_client_name, is_all_clients, parse_period,
)


def get_total_invoices_raw(client: str = "", statut: str = "toutes") -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)

    payment_state = None
    state = None
    statut_lower = statut.lower()
    if "pay" in statut_lower and "impay" not in statut_lower:
        payment_state = "paid"
        state = "posted"
    elif "impay" in statut_lower:
        payment_state = "not_paid"
        state = "posted"
    elif "brouillon" in statut_lower:
        state = "draft"
        payment_state = "not_paid"

    domain = [("move_type", "=", "out_invoice")]
    if state:
        domain.append(("state", "=", state))
    if not is_all_clients(client):
        domain.append(("partner_id.name", "ilike", normalize_client_name(client)))
    if state == "posted" and payment_state:
        paid_states = ["paid", "in_payment"] if payment_state == "paid" else ["not_paid", "partial"]
        domain.append(("payment_state", "in", paid_states))

    am_source = "account.move:read_group(amount_total:sum, groupby=partner_id)"
    client_label = client or "tous les clients"

    results = connector.read_group(
        uid=uid, model="account.move", domain=domain,
        fields=["amount_total:sum"], groupby=["partner_id"],
    )

    if not results:
        so_source = "sale.order:read_group(amount_total:sum)"
        fallback_res = connector.read_group(
            uid=uid, model="sale.order",
            domain=[("state", "in", ["sale", "done"])],
            fields=["amount_total:sum"], groupby=[],
        )
        if fallback_res and fallback_res[0].get("amount_total"):
            tot = fallback_res[0]["amount_total"]
            text = f"Le montant total des ventes confirmées/facturées à ce jour est de {tot:.2f} Ar."
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim="Total confirmed/invoiced sale.order amount to date (fallback: account.move had no matching rows)",
                source=so_source, value=tot, scope=scope,
            )
            return text, [evidence]
        text = f"Aucune facture ({statut}) trouvée pour {client_label}."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice/sale amount found for client={client_label}, statut={statut}",
            source=f"{am_source} [empty] ; {so_source} [empty]",
            value=None, scope=scope,
        )
        return text, [evidence]

    is_global = is_all_clients(client)
    if not is_global and len(results) > 1:
        names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
        text = f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
        return text, []

    if is_global:
        total = sum(r.get("amount_total", 0.0) for r in results)
        text = f"Le total des factures ({statut}) est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
    else:
        total = results[0].get("amount_total", 0.0)
        client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
        text = f"Le total des factures ({statut}) pour {client_name} s'élève à {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"

    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total invoices amount for client={client_label}, statut={statut}",
        source=am_source, value=total, scope=scope,
    )
    return text, [evidence]


@tool
def get_total_invoices(client: str = "", statut: str = "toutes") -> str:
    """Get total amount of invoices (paid, unpaid, draft).

    Args:
        client: Client name (Optional).
        statut: Invoice status ('payé', 'impayé', 'brouillon', 'toutes'). Default: 'toutes'.
    """
    try:
        text, evidence = get_total_invoices_raw(client, statut)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des factures : {str(e)}"


def get_period_revenue_raw(periode: str) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    domain = [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("payment_state", "in", ["paid", "in_payment"]),
    ]

    date_range = parse_period(periode)
    if date_range:
        domain.append(("invoice_date", ">=", date_range[0]))
        domain.append(("invoice_date", "<=", date_range[1]))

    am_source = "account.move:read_group(amount_total:sum, groupby=company_id)"
    results = connector.read_group(
        uid=uid, model="account.move", domain=domain,
        fields=["amount_total:sum"], groupby=["company_id"],
    )

    if not results:
        fb_domain = [("state", "in", ["sale", "done"])]
        if date_range:
            fb_domain.append(("date_order", ">=", date_range[0]))
            end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
            fb_domain.append(("date_order", "<=", end_str))
        so_source = "sale.order:read_group(amount_total:sum)"
        fallback_res = connector.read_group(
            uid=uid, model="sale.order", domain=fb_domain,
            fields=["amount_total:sum"], groupby=[],
        )
        if fallback_res and fallback_res[0].get("amount_total"):
            tot = fallback_res[0]["amount_total"]
            text = (
                f"Le montant total des ventes confirmées/facturées pour la "
                f"période '{periode}' est de {tot:.2f} Ar.\n"
                f"[Source: Odoo ERP - Module Comptabilité (account.move)]"
            )
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim=f"Total confirmed/invoiced sale.order amount for period={periode} (fallback: account.move had no matching rows)",
                source=so_source, value=tot, scope=scope,
            )
            return text, [evidence]
        text = f"Aucun chiffre d'affaires trouvé pour la période '{periode}'."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice/sale revenue found for period={periode}",
            source=f"{am_source} [empty] ; {so_source} [empty]",
            value=None, scope=scope,
        )
        return text, [evidence]

    total = sum(r.get("amount_total", 0.0) for r in results)
    text = (
        f"Le chiffre d'affaires total pour la période '{periode}' "
        f"est de {total:.2f} Ar.\n"
        f"[Source: Odoo ERP - Module Comptabilité (account.move)]"
    )
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total revenue (paid invoices) for period={periode}",
        source=am_source, value=total, scope=scope,
    )
    return text, [evidence]


@tool
def get_period_revenue(periode: str) -> str:
    """Get global revenue (paid invoices) over a period.

    Args:
        periode: Time period (e.g. 'ce mois', '2025', 'toutes').
    """
    try:
        text, evidence = get_period_revenue_raw(periode)
        record_evidence(evidence)
        return text
    except Exception as e:
        return f"Erreur lors du calcul du CA : {str(e)}"
