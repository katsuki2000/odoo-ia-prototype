"""
miro-rag/tools/odoo_tools.py

LangChain @tool definitions for Odoo XML-RPC operations.
These tools are exposed to the AI for function calling.
"""

from typing import Optional, Dict, Any, List
from langchain_core.tools import tool
from tools.odoo_connector import OdooConnector
from tools.date_utils import parse_period

# Instantiate the connector. In production, this would be injected or configured per-request.
# The user's UID must be provided to each tool when called by the agent.
connector = OdooConnector()

# Cache the authenticated uid to avoid re-authenticating on every tool call.
# In Step 7, this will be replaced by per-request UID injection from LangGraph state.
_cached_uid = None

def _get_current_uid() -> int:
    global _cached_uid
    if _cached_uid is None:
        _cached_uid = connector.authenticate("admin")
    return _cached_uid

@tool
def obtenir_total_ventes(client: str, periode: str) -> str:
    """
    Obtenir le montant total des ventes confirmées pour un client donné sur une période.
    
    Args:
        client: Le nom du client.
        periode: La période (ex: 'ce mois', '2024'). À parser ultérieurement.
    """
    uid = _get_current_uid()
    domain = [
        ("partner_id.name", "ilike", client),
        ("state", "in", ["sale", "done"])
    ]
    
    date_range = parse_period(periode)
    if date_range:
        domain.append(("date_order", ">=", date_range[0]))
        domain.append(("date_order", "<=", date_range[1]))
    
    try:
        results = connector.read_group(
            uid=uid,
            model="sale.order",
            domain=domain,
            fields=["amount_total:sum"],
            groupby=["partner_id"]
        )
        if not results:
            return f"Aucune vente trouvée pour {client} sur la période demandée."
            
        if len(results) > 1:
            names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
            
        total = results[0].get("amount_total", 0.0)
        return f"Le total des ventes pour {client} est de {total:.2f} Ar."
    except Exception as e:
        return f"Erreur lors de la récupération des ventes : {str(e)}"

@tool
def obtenir_stock_produit(produit: str) -> str:
    """
    Vérifier la quantité en stock disponible pour un produit spécifique.
    
    Args:
        produit: Le nom du produit à vérifier.
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
        
        return f"Il y a {available} unités de '{produit}' disponibles en stock (Total: {qty}, Réservé: {reserved})."
    except Exception as e:
        return f"Erreur lors de la vérification du stock : {str(e)}"

@tool
def obtenir_statut_commande(reference: str) -> str:
    """
    Obtenir le statut d'une commande de vente spécifique (ex: S00042).
    
    Args:
        reference: La référence de la commande de vente.
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
def obtenir_total_factures(client: str, statut: str) -> str:
    """
    Obtenir le montant total des factures d'un client selon leur statut.
    
    Args:
        client: Le nom du client.
        statut: Le statut de la facture ('payé', 'impayé', 'brouillon').
    """
    uid = _get_current_uid()
    
    # Map friendly status to Odoo technical fields
    payment_state = "not_paid"
    state = "posted"
    if "pay" in statut.lower() and "impay" not in statut.lower():
        payment_state = "paid"
    elif "brouillon" in statut.lower():
        state = "draft"
        payment_state = "not_paid"
        
    domain = [
        ("partner_id.name", "ilike", client),
        ("move_type", "=", "out_invoice"),
        ("state", "=", state)
    ]
    
    if state == "posted":
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
            return f"Aucune facture ({statut}) trouvée pour {client}."
            
        if len(results) > 1:
            names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
            
        total = results[0].get("amount_total", 0.0)
        return f"Le total des factures ({statut}) pour {client} s'élève à {total:.2f} Ar."
    except Exception as e:
        return f"Erreur lors de la récupération des factures : {str(e)}"

@tool
def rechercher_client(nom: str) -> str:
    """
    Rechercher un client ou partenaire par son nom pour obtenir ses coordonnées.
    
    Args:
        nom: Le nom (ou une partie du nom) du client à rechercher.
    """
    uid = _get_current_uid()
    domain = [("name", "ilike", nom)]
    
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
        for r in records[:5]: # limit output to top 5
            email = r.get("email") or "N/A"
            phone = r.get("phone") or "N/A"
            city = r.get("city") or "N/A"
            result_lines.append(f"- {r.get('name')} (Email: {email}, Tél: {phone}, Ville: {city})")
        
        if len(records) > 5:
            result_lines.append("... (résultats tronqués, précisez la recherche)")
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la recherche du client : {str(e)}"

@tool
def obtenir_tickets_recents(client: str, limite: int = 5) -> str:
    """
    Obtenir les tickets de support ou tâches de projet récents pour un client.
    
    Args:
        client: Le nom du client.
        limite: Le nombre maximum de tickets à récupérer (défaut: 5).
    """
    uid = _get_current_uid()
    domain = [("partner_id.name", "ilike", client)]
    
    try:
        # We use project.task as our mock helpdesk ticket per Step 1 populate script
        records = connector.search_read(
            uid=uid,
            model="project.task",
            domain=domain,
            fields=["name", "state", "create_date"]
        )
        if not records:
            return f"Aucun ticket récent trouvé pour {client}."
            
        # Check for ambiguity by looking at unique partner_ids in the results
        unique_partners = set()
        for r in records:
            if r.get("partner_id"):
                unique_partners.add(r.get("partner_id")[1])
                
        if len(unique_partners) > 1:
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(unique_partners)}."
            
        # Sort by latest manually
        records.sort(key=lambda x: x.get("create_date", ""), reverse=True)
        
        result_lines = [f"Derniers tickets pour {client} :"]
        for r in records[:limite]:
            state = r.get("state") or "N/A"
            date_str = r.get("create_date") or "N/A"
            if date_str != "N/A":
                date_str = date_str[:10]
            result_lines.append(f"- [{state}] {r.get('name')} (Créé le: {date_str})")
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la récupération des tickets : {str(e)}"

@tool
def lister_produits_en_rupture() -> str:
    """
    Lister les produits dont la quantité en stock est inférieure ou égale à zéro.
    """
    uid = _get_current_uid()
    # Read group across all quants to aggregate by product
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
def obtenir_ca_periode(periode: str) -> str:
    """
    Obtenir le chiffre d'affaires (factures payées) global sur une période donnée.
    
    Args:
        periode: La période (ex: 'ce mois', '2024').
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
        # To get the total without grouping by a specific field, we group by company_id 
        # (or any common field) to aggregate the total.
        results = connector.read_group(
            uid=uid,
            model="account.move",
            domain=domain,
            fields=["amount_total:sum"],
            groupby=["company_id"]
        )
        if not results:
            return f"Aucun chiffre d'affaires trouvé pour la période '{periode}'."
            
        # Sum across all companies in the result
        total = sum(r.get("amount_total", 0.0) for r in results)
        return f"Le chiffre d'affaires total pour la période '{periode}' est de {total:.2f} Ar."
    except Exception as e:
        return f"Erreur lors du calcul du CA : {str(e)}"
