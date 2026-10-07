"""ORM tools for invoice and revenue queries."""

from typing import List, Tuple

from langchain_core.tools import tool

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import record_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
    normalize_client_name, is_all_clients, parse_period,
    narrow_to_one_entity, ambiguity_text,
)
from erp_data.monetary import format_totals, totals_by_currency


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

    am_source = "account.move:read_group(amount_total:sum, groupby=partner_id,currency_id)"
    client_label = client or "tous les clients"

    results = connector.read_group(
        uid=uid, model="account.move", domain=domain,
        fields=["amount_total:sum"], groupby=["partner_id", "currency_id"],
        lazy=False,
    )

    if not results:
        text = f"Aucune facture ({statut}) trouvée pour {client_label}."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice amount found for client={client_label}, statut={statut}",
            source=f"{am_source} [empty]",
            value=None, scope=scope,
        )
        return text, [evidence]

    if not is_all_clients(client):
        results, candidates = narrow_to_one_entity(results, "partner_id", client)
        if candidates:
            return ambiguity_text("clients", client, candidates), []
        if not results:
            text = f"Aucune facture trouvée pour '{client}'."
            evidence = make_evidence(
                source_type=EvidenceSourceType.ORM,
                claim=f"No matching invoice found for client={client}, statut={statut}",
                source=f"{am_source} [empty after client resolution]",
                value=None, scope=scope,
            )
            return text, [evidence]

    totals = totals_by_currency(results, "amount_total")
    total_text = format_totals(totals)
    target = client or "tous les clients"
    text = (
        f"Le total des factures ({statut}) pour {target} est de {total_text}.\n"
        "[Source: Odoo ERP - Module Comptabilité (account.move)]"
    )
    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Total invoices amount for currency={currency or 'unspecified'}, client={client_label}, statut={statut}",
            source=am_source,
            value={"currency": currency, "amount": amount},
            scope=scope,
        )
        for currency, amount in totals
    ]
    return text, evidences


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

    am_source = "account.move:read_group(amount_total:sum, groupby=currency_id)"
    results = connector.read_group(
        uid=uid, model="account.move", domain=domain,
        fields=["amount_total:sum"], groupby=["currency_id"],
    )

    if not results:
        text = f"Aucun chiffre d'affaires trouvé pour la période '{periode}'."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No matching invoice revenue found for period={periode}",
            source=f"{am_source} [empty]",
            value=None, scope=scope,
        )
        return text, [evidence]

    totals = totals_by_currency(results, "amount_total")
    total_text = format_totals(totals)
    text = (
        f"Le chiffre d'affaires total pour la période '{periode}' "
        f"est de {total_text}.\n"
        f"[Source: Odoo ERP - Module Comptabilité (account.move)]"
    )
    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Total revenue for currency={currency or 'unspecified'} (paid invoices), period={periode}",
            source=am_source,
            value={"currency": currency, "amount": amount},
            scope=scope,
        )
        for currency, amount in totals
    ]
    return text, evidences


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
