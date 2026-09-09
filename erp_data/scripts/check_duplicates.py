"""
Script de vérification des doublons dans les données Odoo injectées.
Utilise l'authentification bas-niveau pour reproduire exactement le
contexte de l'agent (Charlie CRM / Manager, UID attendu : 6).

Usage:
    python miro-rag/scripts/check_duplicates.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from erp_data.odoo_connector import OdooConnector
from erp_data.odoo_context import odoo_uid_ctx, odoo_api_key_ctx

MANAGER_LOGIN = "manager@miro.com"
import os
MANAGER_PASSWORD = os.environ.get("ODOO_MANAGER_PASSWORD")
if not MANAGER_PASSWORD:
    raise ValueError("ODOO_MANAGER_PASSWORD environment variable is required")


def authenticate_manager(connector: OdooConnector) -> int:
    """Authentifie Charlie CRM et injecte le contexte, comme le fait test_erp_accuracy.py."""
    uid = connector.common.authenticate(
        connector.db,
        MANAGER_LOGIN,
        MANAGER_PASSWORD,
        {},
    )
    if not uid:
        raise RuntimeError(f"Échec d'authentification pour {MANAGER_LOGIN}")

    odoo_uid_ctx.set(uid)
    odoo_api_key_ctx.set(MANAGER_PASSWORD)
    print(f" Authentifié en tant que {MANAGER_LOGIN} — UID: {uid}\n")
    return uid


def check_sale_orders(connector, uid):
    print("=" * 60)
    print("VÉRIFICATION : sale.order")
    print("=" * 60)

    orders = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=[],
        fields=["name", "client_order_ref", "amount_total", "partner_id", "state", "company_id"],
    )
    print(f"Total sale.order visibles (UID={uid}) : {len(orders)}")

    refs = [o["client_order_ref"] for o in orders if o.get("client_order_ref")]
    counts = Counter(refs)
    duplicates = {ref: count for ref, count in counts.items() if count > 1}

    if duplicates:
        print(f"  Références en double trouvées : {len(duplicates)}")
        for ref, count in sorted(duplicates.items()):
            print(f"    {ref} : {count} occurrences")
    else:
        print(" Aucun doublon de référence trouvé")

    total_all = sum(o["amount_total"] for o in orders)
    print(f"\nMontant total (toutes commandes visibles) : {total_all:,.0f} Ar")

    states = Counter(o["state"] for o in orders)
    print(f"Répartition par état : {dict(states)}")

    # Total pour Société Dupont spécifiquement (comparaison directe avec ERP-01/ERP-10)
    dupont_orders = [o for o in orders if o.get("partner_id") and "Dupont" in o["partner_id"][1]]
    dupont_total = sum(o["amount_total"] for o in dupont_orders)
    print(f"\nCommandes 'Dupont' trouvées : {len(dupont_orders)}")
    print(f"Montant total Dupont : {dupont_total:,.0f} Ar")
    for o in dupont_orders:
        print(f"    {o['name']} ({o.get('client_order_ref', '—')}) : {o['amount_total']:,.0f} Ar — état: {o['state']}")

    return orders, duplicates


def check_invoices(connector, uid):
    print("\n" + "=" * 60)
    print("VÉRIFICATION : account.move (factures)")
    print("=" * 60)

    invoices = connector.search_read(
        uid=uid,
        model="account.move",
        domain=[("move_type", "=", "out_invoice")],
        fields=["name", "invoice_origin", "amount_total", "partner_id", "state", "payment_state", "company_id"],
    )
    print(f"Total factures visibles (UID={uid}) : {len(invoices)}")

    refs = [i["invoice_origin"] for i in invoices if i.get("invoice_origin")]
    counts = Counter(refs)
    duplicates = {ref: count for ref, count in counts.items() if count > 1}

    if duplicates:
        print(f"  Origines en double trouvées : {len(duplicates)}")
        for ref, count in sorted(duplicates.items()):
            print(f"    {ref} : {count} occurrences")
    else:
        print(" Aucun doublon de facture trouvé")

    payment_states = Counter(i["payment_state"] for i in invoices)
    print(f"Répartition par statut de paiement : {dict(payment_states)}")

    total_all = sum(i["amount_total"] for i in invoices)
    print(f"Montant total toutes factures : {total_all:,.0f} Ar")

    return invoices, duplicates


def check_company_scope(connector, uid):
    print("\n" + "=" * 60)
    print("VÉRIFICATION : périmètre société (company_id)")
    print("=" * 60)

    orders = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=[],
        fields=["name", "company_id"],
    )
    companies = Counter(
        o["company_id"][1] if o.get("company_id") else "Aucune"
        for o in orders
    )
    print("Répartition des commandes par société :")
    for company, count in companies.items():
        print(f"    {company} : {count} commandes")


def check_partner_dupes(connector, uid):
    print("\n" + "=" * 60)
    print("VÉRIFICATION : res.partner (clients en double)")
    print("=" * 60)

    partners = connector.search_read(
        uid=uid,
        model="res.partner",
        domain=[("customer_rank", ">", 0)],
        fields=["name"],
    )
    names = Counter(p["name"] for p in partners)
    duplicates = {name: count for name, count in names.items() if count > 1}
    if duplicates:
        print(f"  Clients en double : {duplicates}")
    else:
        print(f" {len(partners)} clients, aucun doublon de nom")


if __name__ == "__main__":
    connector = OdooConnector()
    uid = authenticate_manager(connector)

    orders, order_dups = check_sale_orders(connector, uid)
    invoices, invoice_dups = check_invoices(connector, uid)
    check_company_scope(connector, uid)
    check_partner_dupes(connector, uid)

    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    if not order_dups and not invoice_dups:
        print(" Aucun doublon de référence détecté — le facteur ~5.7× observé "
              "vient d'ailleurs (logique des outils, agrégation, ou périmètre société).")
        print("   Comparez le 'Montant total Dupont' ci-dessus à la valeur attendue "
              "(12 260 000 Ar) pour voir si le total brut de la base est déjà faux, "
              "ou si le problème est dans l'outil get_total_sales.")
    else:
        print("  Doublons confirmés — nettoyage de la base recommandé.")