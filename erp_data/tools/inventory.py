"""ORM tools for stock and order status queries."""

from typing import List, Tuple

from langchain_core.tools import tool

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from erp_data._odoo_helpers import (
    connector, get_current_uid, orm_evidence_scope,
)


def get_product_stock_raw(produit: str) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    domain = [("product_id.name", "ilike", produit)]

    results = connector.read_group(
        uid=uid, model="stock.quant", domain=domain,
        fields=["quantity:sum", "reserved_quantity:sum"],
        groupby=["product_id"],
    )

    if not results:
        text = f"Le produit '{produit}' n'a pas été trouvé en stock."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No stock.quant matches product={produit}",
            source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
            value=None, scope=scope,
        )
        return text, [evidence]

    qty = results[0].get("quantity", 0.0)
    reserved = results[0].get("reserved_quantity", 0.0)
    available = qty - reserved
    text = (
        f"Il y a {available} unités de '{produit}' disponibles en stock "
        f"(Total: {qty}, Réservé: {reserved}).\n"
        f"[Source: Odoo ERP - Module Stock (stock.quant)]"
    )
    evidence_qty = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Total quantity in stock for product={produit}",
        source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
        value=qty, scope=scope,
    )
    evidence_reserved = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Reserved quantity in stock for product={produit}",
        source="stock.quant:read_group(quantity:sum,reserved_quantity:sum)",
        value=reserved, scope=scope,
    )
    return text, [evidence_qty, evidence_reserved]


@tool
def get_product_stock(produit: str) -> str:
    """Check available stock quantity for a specific product.

    Args:
        produit: The name of the product to check.
    """
    try:
        text, _evidence = get_product_stock_raw(produit)
        return text
    except Exception as e:
        return f"Erreur lors de la vérification du stock : {str(e)}"


_ORDER_STATUS_MAPPING = {
    "draft": "Devis", "sent": "Devis envoyé",
    "sale": "Bon de commande (Confirmé)",
    "done": "Verrouillé", "cancel": "Annulé",
}


def get_order_status_raw(reference: str) -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)
    domain = [("name", "=", reference)]

    records = connector.search_read(
        uid=uid, model="sale.order", domain=domain,
        fields=["state", "amount_total", "partner_id"],
    )

    if not records:
        text = f"La commande {reference} n'existe pas."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"No sale.order matches name={reference}",
            source="sale.order:search_read(state,partner_id)",
            value=None, scope=scope,
        )
        return text, [evidence]

    order = records[0]
    state_raw = order.get("state")
    state_fr = _ORDER_STATUS_MAPPING.get(state_raw, state_raw)
    partner = order.get("partner_id", [0, "Inconnu"])[1]

    text = f"La commande {reference} pour {partner} est au statut '{state_fr}'."
    evidence_state = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Order state for name={reference}",
        source="sale.order:search_read(state,partner_id)",
        value=state_raw, scope=scope,
    )
    evidence_partner = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=f"Partner assigned to order name={reference}",
        source="sale.order:search_read(state,partner_id)",
        value=partner, scope=scope,
    )
    return text, [evidence_state, evidence_partner]


@tool
def get_order_status(reference: str) -> str:
    """Get the status of a specific sales order (e.g. S00042).

    Args:
        reference: Sales order reference code.
    """
    try:
        text, _evidence = get_order_status_raw(reference)
        return text
    except Exception as e:
        return f"Erreur lors de la récupération de la commande : {str(e)}"


def list_out_of_stock_products_raw() -> Tuple[str, List[Evidence]]:
    uid = get_current_uid()
    scope = orm_evidence_scope(uid)

    results = connector.read_group(
        uid=uid, model="stock.quant", domain=[],
        fields=["quantity:sum"], groupby=["product_id"],
    )

    rupture = [
        (r["product_id"][1], r.get("quantity", 0.0))
        for r in results
        if r.get("quantity", 0.0) <= 0.0 and r.get("product_id")
    ]

    if not rupture:
        text = "Aucun produit n'est actuellement en rupture de stock."
        evidence = make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim="No stock.quant product has quantity<=0",
            source="stock.quant:read_group(quantity:sum)",
            value=0, scope=scope,
        )
        return text, [evidence]

    displayed = rupture[:10]
    names = "\n- ".join(name for name, _qty in displayed)
    suffix = "\n..." if len(rupture) > 10 else ""
    text = f"{len(rupture)} produit(s) en rupture de stock :\n- {names}{suffix}"

    evidences = [
        make_evidence(
            source_type=EvidenceSourceType.ORM,
            claim=f"Product {name} is out of stock (quantity<=0)",
            source="stock.quant:read_group(quantity:sum)",
            value=qty, scope=scope,
        )
        for name, qty in displayed
    ]
    return text, evidences


@tool
def list_out_of_stock_products() -> str:
    """List products with zero or negative available stock."""
    try:
        text, _evidence = list_out_of_stock_products_raw()
        return text
    except Exception as e:
        return f"Erreur lors de la récupération des stocks : {str(e)}"
