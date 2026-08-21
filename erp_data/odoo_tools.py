"""
miro-rag/tools/odoo_tools.py

LangChain @tool definitions for Odoo XML-RPC operations.
These tools are exposed to the AI for function calling.
Refactored to English function signatures per project rules.
"""

from typing import Optional, Dict, Any, List
import logging
from langchain_core.tools import tool
from erp_data.odoo_connector import OdooConnector
from tools.date_utils import parse_period
import contextvars

logger = logging.getLogger(__name__)

# Instantiate the connector.
connector = OdooConnector()

odoo_uid_ctx = contextvars.ContextVar('odoo_uid', default=None)
odoo_api_key_ctx = contextvars.ContextVar('odoo_api_key', default=None)

_cached_uid = None

def _get_current_uid() -> int:
    """
    Return the requester's real Odoo uid, propagated via odoo_uid_ctx from
    query_graph()'s `uid` param (itself taken from the trusted JWT on every
    real API request -- see api/main.py::ask_question_v1). That contextvar
    is always set on the real request path, so this admin fallback should
    only ever be hit from tests, scripts, or other out-of-request usage --
    never silently, hence the loud warning: a silent admin fallback is
    exactly the kind of mock that made every ERP query run with admin
    rights regardless of who actually asked.
    """
    uid = odoo_uid_ctx.get()
    if uid is not None:
        return uid

    global _cached_uid
    if _cached_uid is None:
        logger.warning(
            "_get_current_uid(): no requester uid in context -- falling back "
            "to the admin uid. This is expected in tests/scripts, but must "
            "never happen on a real API request (it would mean the JWT uid "
            "was not propagated)."
        )
        _cached_uid = connector.authenticate("admin")
    return _cached_uid

def _normalize_client_name(client: str) -> str:
    if not client:
        return ""
    trans = str.maketrans({
        'é': '_', 'è': '_', 'ê': '_', 'ë': '_',
        'É': '_', 'È': '_', 'Ê': '_', 'Ë': '_',
        'à': '_', 'â': '_', 'À': '_', 'Â': '_',
        'î': '_', 'ï': '_', 'Î': '_', 'Ï': '_',
        'ô': '_', 'ö': '_', 'Ô': '_', 'Ö': '_',
        'ù': '_', 'û': '_', 'ü': '_', 'Ù': '_', 'Û': '_', 'Ü': '_',
        'ç': '_', 'Ç': '_'
    })
    return client.translate(trans)

@tool
def get_total_sales(client: str = "", periode: str = "", statut: str = "toutes") -> str:
    """
    Get the total sales amount filtered by client, period, and status.

    Args:
        client: Client name. Leave empty ("") or "tous" for all clients.
        periode: Optional time period filter (e.g. 'ce mois', '2025'). Leave empty string ("") for all time unless a specific period is explicitly mentioned in the user query.
        statut: Order status filter ('confirmees', 'brouillon', 'toutes'). Default: 'toutes'.
    """
    statut_normalized = statut.lower().strip()

    if statut_normalized in ("confirmees", "confirmée", "confirmées", "confirmee"):
        states = ["sale", "done"]
    elif statut_normalized in ("brouillon", "en cours", "draft"):
        states = ["draft", "sent"]
    else:
        states = ["draft", "sent", "sale", "done"]

    domain = [("state", "in", states)]

    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))

    date_range = parse_period(periode) if periode else None
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
        domain.append(("date_order", "<=", end_str))

    uid = _get_current_uid()
    results = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=[],
    )

    if not results or not results[0].get("amount_total"):
        client_label = f" pour {client}" if client and client.lower() not in ["tous les clients", "tous", ""] else ""
        return f"Aucune vente trouvée{client_label} (statut: {statut})."

    total = results[0]["amount_total"]
    client_label = f" pour {client}" if client and client.lower() not in ["tous les clients", "tous", ""] else ""
    return f"Le total des ventes{client_label} (statut: {statut}) est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"

@tool
def get_product_stock(produit: str) -> str:
    """
    Check the available stock quantity for a specific product.
    
    Args:
        produit: The name of the product to check.
    """
    uid = _get_current_uid()
    domain = [("product_id.name", "ilike", produit)]
    
    try:
        results = connector.read_group(
            uid=uid,
            model="stock.quant",
            domain=domain,
            fields=["quantity:sum", "reserved_quantity:sum"],
            groupby=["product_id"]
        )
        if not results:
            return f"Le produit '{produit}' n'a pas été trouvé en stock."
            
        qty = results[0].get("quantity", 0.0)
        reserved = results[0].get("reserved_quantity", 0.0)
        available = qty - reserved
        
        return f"Il y a {available} unités de '{produit}' disponibles en stock (Total: {qty}, Réservé: {reserved}).\n[Source: Odoo ERP - Module Stock (stock.quant)]"
    except Exception as e:
        return f"Erreur lors de la vérification du stock : {str(e)}"

@tool
def get_order_status(reference: str) -> str:
    """
    Get the status of a specific sales order (e.g. S00042).
    
    Args:
        reference: Sales order reference code.
    """
    uid = _get_current_uid()
    domain = [("name", "=", reference)]
    
    try:
        records = connector.search_read(
            uid=uid,
            model="sale.order",
            domain=domain,
            fields=["state", "amount_total", "partner_id"]
        )
        if not records:
            return f"La commande {reference} n'existe pas."
            
        order = records[0]
        state_mapping = {
            "draft": "Devis",
            "sent": "Devis envoyé",
            "sale": "Bon de commande (Confirmé)",
            "done": "Verrouillé",
            "cancel": "Annulé"
        }
        state_fr = state_mapping.get(order.get("state"), order.get("state"))
        partner = order.get("partner_id", [0, "Inconnu"])[1]
        
        return f"La commande {reference} pour {partner} est au statut '{state_fr}'."
    except Exception as e:
        return f"Erreur lors de la récupération de la commande : {str(e)}"

@tool
def get_total_invoices(client: str = "", statut: str = "toutes") -> str:
    """
    Get the total amount of invoices (paid, unpaid, draft).
    
    Args:
        client: Client name (Optional).
        statut: Invoice status ('payé', 'impayé', 'brouillon', 'toutes'). Default: 'toutes'.
    """
    uid = _get_current_uid()
    
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
        
    domain = [
        ("move_type", "=", "out_invoice")
    ]
    if state:
        domain.append(("state", "=", state))
    
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
    
    if state == "posted" and payment_state:
        domain.append(("payment_state", "in", ["paid", "in_payment"] if payment_state == "paid" else ["not_paid", "partial"]))
        
    try:
        results = connector.read_group(
            uid=uid,
            model="account.move",
            domain=domain,
            fields=["amount_total:sum"],
            groupby=["partner_id"]
        )
        if not results:
            fallback_res = connector.read_group(
                uid=uid,
                model="sale.order",
                domain=[("state", "in", ["sale", "done"])],
                fields=["amount_total:sum"],
                groupby=[]
            )
            if fallback_res and fallback_res[0].get("amount_total"):
                tot = fallback_res[0]["amount_total"]
                return f"Le montant total des ventes confirmées/facturées à ce jour est de {tot:.2f} Ar."
            return f"Aucune facture ({statut}) trouvée pour {client or 'tous les clients'}."
            
        is_global = not client or client.lower() in ["tous les clients", "tous", ""]
        if not is_global and len(results) > 1:
            names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
            
        if is_global:
            total = sum(r.get("amount_total", 0.0) for r in results)
            return f"Le total des factures ({statut}) est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
        else:
            total = results[0].get("amount_total", 0.0)
            client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
            return f"Le total des factures ({statut}) pour {client_name} s'élève à {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
    except Exception as e:
        return f"Erreur lors de la récupération des factures : {str(e)}"

@tool
def search_partner(nom: str) -> str:
    """
    Search for a client or partner by name to get contact details.
    
    Args:
        nom: Client name or partial name to search.
    """
    uid = _get_current_uid()
    domain = [("name", "ilike", _normalize_client_name(nom))]
    
    try:
        records = connector.search_read(
            uid=uid,
            model="res.partner",
            domain=domain,
            fields=["name", "email", "phone", "city"]
        )
        if not records:
            return f"Aucun client trouvé avec le nom '{nom}'."
            
        result_lines = [f"{len(records)} client(s) trouvé(s) :"]
        for r in records[:5]:
            email = r.get("email") or "N/A"
            phone = r.get("phone") or "N/A"
            city = r.get("city") or "N/A"
            result_lines.append(f"- {r.get('name')} (Email: {email}, Tél: {phone}, Ville: {city})")
        
        if len(records) > 5:
            result_lines.append("... (résultats tronqués, précisez la recherche)")
            
        result_lines.append("[Source: Odoo ERP - Contacts (res.partner)]")
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la recherche du client : {str(e)}"

@tool
def get_recent_tickets(client: str = "", limite: int = 0, statut: Optional[str] = None) -> str:
    """
    Get support tickets or project tasks from Odoo ERP.
    
    Args:
        client: Optional client name. Leave empty ("") for all clients.
        limite: Max number of tickets to return (0 for all matching tickets).
        statut: Optional status filter (e.g. 'résolu', 'en cours'). Leave None unless the user explicitly requests a specific ticket status.
    """
    uid = _get_current_uid()
    domain = []
    
    is_global = not client or client.lower() in ["tous les clients", "tous", ""]
    if not is_global:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
        
    if statut:
        statut_lower = statut.lower()
        if "résolu" in statut_lower or "fini" in statut_lower or "done" in statut_lower:
            domain.append(("state", "=", "1_done"))
        elif "en cours" in statut_lower or "progress" in statut_lower:
            domain.append(("state", "=", "01_in_progress"))
        elif "nouveau" in statut_lower or "ouvert" in statut_lower:
            domain.append(("state", "=", "01_in_progress"))
            
    try:
        records = connector.search_read(
            uid=uid,
            model="project.task",
            domain=domain,
            fields=["name", "state", "create_date", "date_deadline", "partner_id"],
            order="date_deadline desc, id desc"
        )
        if not records:
            return f"Aucun ticket trouvé pour {client or 'tous les clients'} avec le statut '{statut or 'tous'}'.\n[Source: Odoo ERP - Module Projet (project.task)]"
            
        if not is_global:
            unique_partners = set()
            for r in records:
                if r.get("partner_id"):
                    unique_partners.add(r.get("partner_id")[1])
                    
            if len(unique_partners) > 1:
                return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(unique_partners)}."
            
        records.sort(key=lambda x: (x.get("date_deadline") or x.get("create_date") or "", x.get("id", 0)), reverse=True)
        
        total_count = len(records)
        display_limit = limite if limite > 0 else total_count
        
        result_lines = [
            f"Total de tickets trouvés : {total_count}",
            f"Liste des tickets pour {client or 'tous les clients'} :"
        ]
        for r in records[:display_limit]:
            state = r.get("state") or "N/A"
            date_str = r.get("create_date") or "N/A"
            if date_str != "N/A":
                date_str = date_str[:10]
            partner_name = r.get("partner_id")[1] if r.get("partner_id") else "N/A"
            result_lines.append(f"- [{state}] Client: {partner_name} | {r.get('name')} (Créé le: {date_str})")
            
        result_lines.append("[Source: Odoo ERP - Module Projet (project.task)]")
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la récupération des tickets : {str(e)}"

@tool
def list_out_of_stock_products() -> str:
    """
    List products with zero or negative available stock.
    """
    uid = _get_current_uid()
    domain = []
    
    try:
        results = connector.read_group(
            uid=uid,
            model="stock.quant",
            domain=domain,
            fields=["quantity:sum"],
            groupby=["product_id"]
        )
        
        rupture_products = []
        for r in results:
            if r.get("quantity", 0.0) <= 0.0:
                prod = r.get("product_id")
                if prod:
                    rupture_products.append(prod[1])
                    
        if not rupture_products:
            return "Aucun produit n'est actuellement en rupture de stock."
            
        return f"{len(rupture_products)} produit(s) en rupture de stock :\n- " + "\n- ".join(rupture_products[:10]) + ("\n..." if len(rupture_products) > 10 else "")
    except Exception as e:
        return f"Erreur lors de la récupération des stocks : {str(e)}"

@tool
def get_period_revenue(periode: str) -> str:
    """
    Get global revenue (paid invoices) over a period.
    
    Args:
        periode: Time period (e.g. 'ce mois', '2025', 'toutes').
    """
    uid = _get_current_uid()
    domain = [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("payment_state", "in", ["paid", "in_payment"])
    ]
    
    date_range = parse_period(periode)
    if date_range:
        domain.append(("invoice_date", ">=", date_range[0]))
        domain.append(("invoice_date", "<=", date_range[1]))
    
    try:
        results = connector.read_group(
            uid=uid,
            model="account.move",
            domain=domain,
            fields=["amount_total:sum"],
            groupby=["company_id"]
        )
        if not results:
            fb_domain = [("state", "in", ["sale", "done"])]
            if date_range:
                fb_domain.append(("date_order", ">=", date_range[0]))
                end_str = date_range[1] if " " in date_range[1] else date_range[1] + " 23:59:59"
                fb_domain.append(("date_order", "<=", end_str))

            fallback_res = connector.read_group(
                uid=uid,
                model="sale.order",
                domain=fb_domain,
                fields=["amount_total:sum"],
                groupby=[]
            )
            if fallback_res and fallback_res[0].get("amount_total"):
                tot = fallback_res[0]["amount_total"]
                return f"Le montant total des ventes confirmées/facturées pour la période '{periode}' est de {tot:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
            return f"Aucun chiffre d'affaires trouvé pour la période '{periode}'."
            
        total = sum(r.get("amount_total", 0.0) for r in results)
        return f"Le chiffre d'affaires total pour la période '{periode}' est de {total:.2f} Ar.\n[Source: Odoo ERP - Module Comptabilité (account.move)]"
    except Exception as e:
        return f"Erreur lors du calcul du CA : {str(e)}"

@tool
def get_average_sales(client: str = "", periode: str = "toutes") -> str:
    """
    Get average sale amount for a client or overall.
    
    Args:
        client: Client name (Optional).
        periode: Time period (Optional).
    """
    uid = _get_current_uid()
    domain = [("state", "in", ["sale", "done"])]
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
    
    date_range = parse_period(periode)
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        domain.append(("date_order", "<=", date_range[1]))
        
    try:
        results = connector.read_group(
            uid=uid,
            model="sale.order",
            domain=domain,
            fields=["amount_total:avg"],
            groupby=["partner_id"] if client and client.lower() not in ["tous", ""] else []
        )
        if not results:
            return f"Aucune vente trouvée pour calculer la moyenne."
            
        if not client or client.lower() in ["tous", ""]:
            moyenne = results[0].get("amount_total", 0.0)
            return f"Le montant moyen d'une vente est de {moyenne:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"
        else:
            moyenne = results[0].get("amount_total", 0.0)
            client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
            return f"Le montant moyen d'une vente pour {client_name} est de {moyenne:.2f} Ar.\n[Source: Odoo ERP - Module Ventes (sale.order)]"
    except Exception as e:
        return f"Erreur lors du calcul de la moyenne : {str(e)}"

@tool
def get_sale_details(client: str = "", statut: str = "toutes", limite: int = 0) -> str:
    """
    Get sale order line details (products sold, amounts, dates) for a client.
    
    Args:
        client: Client name.
        statut: Optional order status filter ('confirmé', 'brouillon', 'toutes'). Default: 'toutes'. Leave 'toutes' unless a specific status is explicitly requested.
        limite: Max sales orders to return (0 for all matching sales orders). Default: 0. Leave 0 unless a specific limit is explicitly requested.
    """
    uid = _get_current_uid()
    # Always fetch all sales orders for the client to provide complete totals and itemized products
    effective_limit = 0 if limite <= 1 else limite

    if statut.lower() in ["brouillon", "en cours"]:
        domain = [("state", "in", ["draft", "sent"])]
    elif statut.lower() in ["confirmé", "confirmees", "confirmées"]:
        domain = [("state", "in", ["sale", "done"])]
    elif statut.lower() in ["annulé", "annule", "cancel"]:
        domain = [("state", "=", "cancel")]
    else:
        domain = [("state", "!=", "cancel")]
        
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
        
    try:
        records = connector.search_read(
            uid=uid,
            model="sale.order",
            domain=domain,
            fields=["name", "partner_id", "date_order", "amount_total", "state", "order_line"],
            limit=effective_limit
        )
        if not records and statut.lower() not in ["toutes"]:
            fallback_domain = [("state", "!=", "cancel")]
            if client and client.lower() not in ["tous les clients", "tous", ""]:
                fallback_domain.append(("partner_id.name", "ilike", _normalize_client_name(client)))
            records = connector.search_read(
                uid=uid,
                model="sale.order",
                domain=fallback_domain,
                fields=["name", "partner_id", "date_order", "amount_total", "state", "order_line"],
                limit=effective_limit
            )

        if not records:
            return f"Aucune vente trouvée pour {client or 'tous les clients'}."
            
        total_sum = sum(r.get("amount_total", 0.0) for r in records)
        state_labels = {
            "draft": "Devis en cours",
            "sent": "Devis envoyé",
            "sale": "Vente confirmée",
            "done": "Vente confirmée",
            "cancel": "Commande annulée"
        }
        total_fmt = f"{total_sum:,.2f}".replace(",", " ")
        result_lines = [
            f"Détails des commandes / devis pour {client or 'tous les clients'} (Total: {total_fmt} Ar, {len(records)} commande(s)) :"
        ]
        for r in records:
            client_name = r.get("partner_id")[1] if r.get("partner_id") else "Inconnu"
            amount = r.get("amount_total", 0.0)
            amount_fmt = f"{amount:,.2f}".replace(",", " ")
            state_raw = r.get("state", "inconnu")
            state_fr = state_labels.get(state_raw, state_raw)
            name = r.get("name", "inconnu")
            
            line_ids = r.get("order_line", [])
            produits = []
            if line_ids:
                lines = connector.search_read(
                    uid=uid,
                    model="sale.order.line",
                    domain=[("id", "in", line_ids)],
                    fields=["product_id"]
                )
                for line in lines:
                    if line.get("product_id"):
                        produits.append(line.get("product_id")[1])
            
            prod_str = ", ".join(produits) if produits else "Aucun produit"
            result_lines.append(f"- Commande {name} ({state_fr}) pour {client_name} : {amount_fmt} Ar. Produits : {prod_str}")
            
        result_lines.append("[Source: Odoo ERP - Module Ventes (sale.order)]")
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la récupération des détails : {str(e)}"

# --- Backward compatibility aliases ---
obtenir_total_ventes = get_total_sales
obtenir_stock_produit = get_product_stock
obtenir_statut_commande = get_order_status
obtenir_total_factures = get_total_invoices
rechercher_client = search_partner
obtenir_tickets_recents = get_recent_tickets
lister_produits_en_rupture = list_out_of_stock_products
obtenir_ca_periode = get_period_revenue
obtenir_moyenne_ventes = get_average_sales
obtenir_details_ventes = get_sale_details
