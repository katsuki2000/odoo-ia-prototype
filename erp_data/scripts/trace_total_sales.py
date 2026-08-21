"""
Script de traçage : obtenir_total_ventes et obtenir_ca_periode en conditions réelles.

Compare :
1. Ce que l'outil retourne réellement (via .invoke(), comme le fait l'agent)
2. Une requête read_group manuelle équivalente, pour vérifier le calcul brut

Usage:
    python scripts/trace_total_ventes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.odoo_connector import OdooConnector
from erp_data.odoo_tools import odoo_uid_ctx, odoo_api_key_ctx, obtenir_total_ventes, obtenir_ca_periode

MANAGER_LOGIN = "manager@miro.com"
MANAGER_PASSWORD = "password123"


def authenticate_manager(connector: OdooConnector) -> int:
    uid = connector.common.authenticate(connector.db, MANAGER_LOGIN, MANAGER_PASSWORD, {})
    if not uid:
        raise RuntimeError(f"Échec d'authentification pour {MANAGER_LOGIN}")
    odoo_uid_ctx.set(uid)
    odoo_api_key_ctx.set(MANAGER_PASSWORD)
    print(f"✅ Authentifié en tant que {MANAGER_LOGIN} — UID: {uid}\n")
    return uid


def trace_tool_call():
    print("=" * 60)
    print("1. APPEL RÉEL DE L'OUTIL obtenir_total_ventes")
    print("=" * 60)

    # Appel global, sans client (comme pour ERP-08)
    result_global = obtenir_total_ventes.invoke({"client": "", "periode": ""})
    print(f"obtenir_total_ventes(client='', periode='') →\n{result_global}\n")

    # Appel pour Dupont spécifiquement (comme pour ERP-01/ERP-10)
    result_dupont = obtenir_total_ventes.invoke({"client": "Dupont", "periode": ""})
    print(f"obtenir_total_ventes(client='Dupont', periode='') →\n{result_dupont}\n")


def trace_raw_read_group(connector, uid):
    print("=" * 60)
    print("2. REQUÊTE BRUTE read_group (reproduction manuelle)")
    print("=" * 60)

    domain = [("state", "in", ["sale", "done"])]
    results = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=["company_id"],
    )
    print(f"read_group domain={domain}, groupby=['company_id'] →")
    for r in results:
        print(f"    {r}")

    # Même chose sans groupby, pour voir si le groupby cause la multiplication
    print("\nMême requête SANS groupby (une seule somme globale) :")
    results_no_group = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=[],
    )
    print(f"    {results_no_group}")

    # Comparaison directe avec search_read (somme manuelle en Python)
    print("\nComparaison avec search_read + somme Python (référence sûre) :")
    orders = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total"],
    )
    manual_sum = sum(o["amount_total"] for o in orders)
    print(f"    {len(orders)} commandes, somme manuelle = {manual_sum:,.0f} Ar")


def trace_dupont_domain(connector, uid):
    print("\n" + "=" * 60)
    print("3. DOMAINE DUPONT — reproduction du filtre client")
    print("=" * 60)

    # Domaine typique utilisé dans obtenir_total_ventes pour filtrer par client
    domain = [
        ("state", "in", ["sale", "done"]),
        ("partner_id.name", "ilike", "Dupont"),
    ]
    orders = connector.search_read(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["name", "amount_total", "partner_id"],
    )
    print(f"Domaine: {domain}")
    print(f"{len(orders)} commandes trouvées :")
    for o in orders:
        print(f"    {o['name']} : {o['amount_total']:,.0f} Ar — partner: {o['partner_id']}")
    print(f"Somme manuelle : {sum(o['amount_total'] for o in orders):,.0f} Ar")

    # read_group équivalent, pour voir si le bug apparaît ici spécifiquement
    print("\nread_group équivalent :")
    results = connector.read_group(
        uid=uid,
        model="sale.order",
        domain=domain,
        fields=["amount_total:sum"],
        groupby=["company_id"],
    )
    for r in results:
        print(f"    {r}")


if __name__ == "__main__":
    connector = OdooConnector()
    uid = authenticate_manager(connector)

    trace_raw_read_group(connector, uid)
    trace_dupont_domain(connector, uid)
    trace_tool_call()

    print("\n" + "=" * 60)
    print("RÉFÉRENCE ATTENDUE")
    print("=" * 60)
    print("Total global (état sale/done, toutes sociétés) : à comparer avec 62 120 000 Ar")
    print("Total Dupont : 12 260 000 Ar (confirmé par check_duplicates.py)")