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

import contextvars
odoo_uid_ctx = contextvars.ContextVar('odoo_uid', default=None)
odoo_api_key_ctx = contextvars.ContextVar('odoo_api_key', default=None)

# Cache the authenticated uid for fallback when testing outside of LangGraph
_cached_uid = None

def _get_current_uid() -> int:
    # First, try to get the uid injected from the LangGraph request context
    uid = odoo_uid_ctx.get()
    if uid is not None:
        return uid
        
    # Fallback to admin for legacy tests
    global _cached_uid
    if _cached_uid is None:
        _cached_uid = connector.authenticate("admin")
    return _cached_uid

@tool
def obtenir_total_ventes(client: str = "", periode: str = "toutes", statut: str = "confirmé") -> str:
    """
    Utilisez cet outil pour obtenir le montant total des ventes (devis, commandes, etc.).
    NE L'UTILISEZ PAS pour demander le chiffre d'affaires (utilisez obtenir_ca_periode).
    
    Args:
        client: Le nom du client (Optionnel, laisser vide ou 'tous' pour tous les clients).
        periode: La période (ex: 'ce mois', '2024'). Optionnel.
        statut: Le statut des ventes ('confirmé', 'brouillon', 'en cours', 'toutes'). Défaut: 'confirmé'. Pour "en cours", utilisez "en cours".
    """
    uid = _get_current_uid()
    
    if statut.lower() in ["brouillon", "en cours", "draft", "sent"]:
        domain = [("state", "in", ["draft", "sent"])]
    elif statut.lower() == "toutes":
        domain = []
    else:
        domain = [("state", "in", ["sale", "done"])]
    
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", client))
    
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
            return f"Aucune vente trouvée pour {client or 'tous les clients'} sur la période demandée."
            
        is_global = not client or client.lower() in ["tous les clients", "tous", ""]
        if not is_global and len(results) > 1:
            names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
            
        if is_global:
            total = sum(r.get("amount_total", 0.0) for r in results)
            return f"Le total des ventes est de {total:.2f} Ar."
        else:
            total = results[0].get("amount_total", 0.0)
            client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
            return f"Le total des ventes pour {client_name} est de {total:.2f} Ar."
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
def obtenir_total_factures(client: str = "", statut: str = "toutes") -> str:
    """
    Utilisez cet outil pour obtenir le montant total des factures (payées, impayées, brouillon).
    NE L'UTILISEZ PAS pour les ventes (utilisez obtenir_total_ventes).
    
    Args:
        client: Le nom du client (Optionnel).
        statut: Le statut de la facture ('payé', 'impayé', 'brouillon', 'toutes'). Défaut: 'toutes'.
    """
    uid = _get_current_uid()
    
    # Map friendly status to Odoo technical fields
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
        domain.append(("partner_id.name", "ilike", client))
    
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
            return f"Aucune facture ({statut}) trouvée pour {client or 'tous les clients'}."
            
        is_global = not client or client.lower() in ["tous les clients", "tous", ""]
        if not is_global and len(results) > 1:
            names = [r.get("partner_id")[1] for r in results if r.get("partner_id")]
            return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(names)}."
            
        if is_global:
            total = sum(r.get("amount_total", 0.0) for r in results)
            return f"Le total des factures ({statut}) est de {total:.2f} Ar."
        else:
            total = results[0].get("amount_total", 0.0)
            client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
            return f"Le total des factures ({statut}) pour {client_name} s'élève à {total:.2f} Ar."
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
def obtenir_tickets_recents(client: str = "", limite: int = 5, statut: Optional[str] = None) -> str:
    """
    Obtenir les tickets de support ou tâches de projet récents pour un client.
    
    Args:
        client: Le nom du client. (Optionnel, laisser vide ou utiliser 'tous' pour tous les clients).
        limite: Le nombre maximum de tickets à lister (défaut: 5).
        statut: Le statut du ticket (ex: 'résolu', 'en cours'). Optionnel.
    """
    uid = _get_current_uid()
    domain = []
    
    is_global = not client or client.lower() in ["tous les clients", "tous", ""]
    if not is_global:
        domain.append(("partner_id.name", "ilike", client))
        
    if statut:
        # Simple mapping for common states
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
            fields=["name", "state", "create_date", "partner_id"]
        )
        if not records:
            return f"Aucun ticket trouvé pour {client or 'tous les clients'} avec le statut '{statut or 'tous'}'."
            
        if not is_global:
            # Check for ambiguity by looking at unique partner_ids in the results
            unique_partners = set()
            for r in records:
                if r.get("partner_id"):
                    unique_partners.add(r.get("partner_id")[1])
                    
            if len(unique_partners) > 1:
                return f"AMBIGUÏTÉ : Plusieurs clients correspondent à '{client}'. Veuillez préciser lequel parmi : {', '.join(unique_partners)}."
            
        # Sort by latest manually
        records.sort(key=lambda x: x.get("create_date", ""), reverse=True)
        
        total_count = len(records)
        display_limit = limite if limite > 0 else 5
        
        result_lines = [
            f"Total de tickets trouvés : {total_count}",
            f"Derniers tickets pour {client or 'tous les clients'} :"
        ]
        for r in records[:display_limit]:
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
    Utilisez cet outil UNIQUEMENT pour obtenir le chiffre d'affaires (factures payées) global sur une période.
    NE L'UTILISEZ PAS pour demander le montant total des ventes ou commandes.
    
    Args:
        periode: La période (ex: 'ce mois', '2024', 'toutes').
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

@tool
def obtenir_moyenne_ventes(client: str = "", periode: str = "toutes") -> str:
    """
    Obtenir le montant moyen d'une vente (panier moyen) pour un client ou au global.
    
    Args:
        client: Le nom du client (Optionnel).
        periode: La période (Optionnel).
    """
    uid = _get_current_uid()
    domain = [("state", "in", ["sale", "done"])]
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", client))
    
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
            # Odoo without groupby might just return one record with the global average
            moyenne = results[0].get("amount_total", 0.0)
            return f"Le montant moyen d'une vente est de {moyenne:.2f} Ar."
        else:
            moyenne = results[0].get("amount_total", 0.0)
            client_name = results[0].get("partner_id")[1] if results[0].get("partner_id") else client
            return f"Le montant moyen d'une vente pour {client_name} est de {moyenne:.2f} Ar."
    except Exception as e:
        return f"Erreur lors du calcul de la moyenne : {str(e)}"

@tool
def obtenir_details_ventes(client: str = "", statut: str = "toutes", limite: int = 5) -> str:
    """
    Utilisez cet outil UNIQUEMENT pour obtenir les détails d'une vente (produits vendus, montants, date) pour un client.
    Utile pour répondre à "Quel produit a été vendu à X".
    
    Args:
        client: Le nom du client.
        statut: Le statut ('confirmé', 'en cours', 'toutes'). Défaut: 'toutes'.
        limite: Le nombre maximum de ventes à retourner.
    """
    uid = _get_current_uid()
    if statut.lower() in ["brouillon", "en cours"]:
        domain = [("state", "in", ["draft", "sent"])]
    elif statut.lower() == "confirmé":
        domain = [("state", "in", ["sale", "done"])]
    else:
        domain = []
        
    if client and client.lower() not in ["tous les clients", "tous", ""]:
        domain.append(("partner_id.name", "ilike", client))
        
    try:
        records = connector.search_read(
            uid=uid,
            model="sale.order",
            domain=domain,
            fields=["name", "partner_id", "date_order", "amount_total", "state", "order_line"],
            limit=limite
        )
        if not records:
            return f"Aucune vente trouvée pour {client or 'tous les clients'}."
            
        result_lines = []
        for r in records:
            client_name = r.get("partner_id")[1] if r.get("partner_id") else "Inconnu"
            amount = r.get("amount_total", 0.0)
            state = r.get("state", "inconnu")
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
            result_lines.append(f"- Commande {name} ({state}) pour {client_name} : {amount} Ar. Produits : {prod_str}")
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur lors de la récupération des détails : {str(e)}"
