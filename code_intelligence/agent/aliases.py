"""
code_intelligence/business_aliases.py

Static business alias definitions and normalization for Odoo models and concepts.
"""

import re
import unicodedata
from typing import Dict, List

BUSINESS_ALIASES: Dict[str, List[str]] = {
    # Comptabilité / avoirs
    "avoir": ["account.move"],
    "avoirs": ["account.move"],
    "credit note": ["account.move"],
    "facture": ["account.move"],
    "factures": ["account.move"],
    "facturation": ["account.move", "sale.order"],
    "ecriture": ["account.move"],
    "écriture": ["account.move"],
    "ecritures": ["account.move"],
    "écritures": ["account.move"],
    "ecriture comptable": ["account.move"],
    "écriture comptable": ["account.move"],
    "ecritures comptables": ["account.move"],
    "écritures comptables": ["account.move"],
    "journal entry": ["account.move"],
    "journal entries": ["account.move"],
    "piece comptable": ["account.move"],
    "pièce comptable": ["account.move"],
    "ligne d'ecriture": ["account.move.line"],
    "ligne d'écriture": ["account.move.line"],
    "lignes d'ecriture": ["account.move.line"],
    "lignes d'écriture": ["account.move.line"],
    "demande d'achat": ["purchase.request", "custom.purchase.request"],
    "demande d'achats": ["purchase.request", "custom.purchase.request"],
    "ligne de demande d'achat": ["purchase.request.line"],
    "lignes de demande d'achat": ["purchase.request.line"],
    "commande d'achat": ["purchase.order"],
    "commandes d'achat": ["purchase.order"],
    "ligne de commande d'achat": ["purchase.order.line"],
    "lignes de commande d'achat": ["purchase.order.line"],
    # Prêt matériel
    "mise a disposition": ["custom.asset.loan"],
    "mise à disposition": ["custom.asset.loan"],
    "pret de materiel": ["custom.asset.loan"],
    "prêt de matériel": ["custom.asset.loan"],
    "prets de materiel": ["custom.asset.loan"],
    "prêts de matériel": ["custom.asset.loan"],
    # Congés
    "conge": ["hr.leave"],
    "congé": ["hr.leave"],
    "conges": ["hr.leave"],
    "congés": ["hr.leave"],
    "demande de conge": ["hr.leave"],
    "demande de congé": ["hr.leave"],
    "remboursement": ["custom.reimbursement.request", "hr.expense"],
    "remboursement de frais": ["custom.reimbursement.request", "hr.expense"],
    "note de frais": ["custom.reimbursement.request", "hr.expense"],
    # Automatismes Odoo
    "action automatique": ["base.automation"],
    "serveur action": ["ir.actions.server"],
    "server action": ["ir.actions.server"],
    # Deep inheritance security
    "document deep": ["custom.deep.document"],
    "deep document": ["custom.deep.document"],
    "documents deep": ["custom.deep.document"],
    "deep documents": ["custom.deep.document"],
    # Animal
    "animaux": ["animal"],
    "espece": ["animal.species"],
    "especes": ["animal.species"],
    "espèce": ["animal.species"],
    "espèces": ["animal.species"],
    "race": ["animal.breed"],
    "races": ["animal.breed"],
    # Tier validation
    "validation par paliers": ["tier.validation"],
    "approbation par paliers": ["tier.validation"],
    "tier validation": ["tier.validation"],
    "champs non exemptes": ["tier.validation"],
    "champs non exemptés": ["tier.validation"],
    "en cours de validation": ["tier.validation"],
    # Stock inventory
    "inventaire": ["stock.inventory"],
    "inventaires": ["stock.inventory"],
    "ajustement d'inventaire": ["stock.inventory"],
    "ajustements d'inventaire": ["stock.inventory"],
    # Sale order type
    "type de commande": ["sale.order", "sale.order.type"],
    "types de commande": ["sale.order", "sale.order.type"],
    "type d'une commande": ["sale.order", "sale.order.type"],
    "type de commande de vente": ["sale.order", "sale.order.type"],
    "types de commande de vente": ["sale.order", "sale.order.type"],
    "commande confirmee": ["sale.order"],
    "commande confirmée": ["sale.order"],
    "commandes confirmees": ["sale.order"],
    "commandes confirmées": ["sale.order"],
    "commande": ["sale.order"],
    "commandes": ["sale.order"],
    "commande de vente": ["sale.order"],
    "commandes de vente": ["sale.order"],
    "generation de facture": ["sale.order", "account.move"],
    "génération de facture": ["sale.order", "account.move"],
    "section de facture": ["account.move"],
    "sections de facture": ["account.move"],
    "ligne de section": ["sale.order", "account.move.line"],
    "lignes de section": ["sale.order", "account.move.line"],
    # Partenaires / Contacts
    "partenaire": ["res.partner"],
    "partenaires": ["res.partner"],
    "fiche partenaire": ["res.partner"],
    "fiche d'un partenaire": ["res.partner"],
    "contact": ["res.partner"],
    "contacts": ["res.partner"],
    # Sociétés
    "societe": ["res.company"],
    "société": ["res.company"],
    "societes": ["res.company"],
    "sociétés": ["res.company"],
    "entreprise": ["res.company"],
    "entreprises": ["res.company"],
    "compagnie": ["res.company"],
    "compagnies": ["res.company"],
    # Database cleanup
    "database cleanup": ["cleanup.purge.wizard"],
    "nettoyage de base": ["cleanup.purge.wizard"],
    "nettoyage de base de donnees": ["cleanup.purge.wizard"],
    "nettoyage de base de données": ["cleanup.purge.wizard"],
    "purge": ["cleanup.purge.wizard"],
    "purges": ["cleanup.purge.wizard"],
    "proposer a la purge": ["cleanup.purge.wizard.model"],
    "proposer à la purge": ["cleanup.purge.wizard.model"],
    "purge de modeles": ["cleanup.purge.wizard.model"],
    "purge de modèles": ["cleanup.purge.wizard.model"],
    "purge de modeles orphelins": ["cleanup.purge.wizard.model"],
    "purge de modèles orphelins": ["cleanup.purge.wizard.model"],
    "modeles orphelins": ["cleanup.purge.wizard.model"],
    "modèles orphelins": ["cleanup.purge.wizard.model"],
    "purge de colonnes": ["cleanup.purge.wizard.column"],
    "colonnes orphelines": ["cleanup.purge.wizard.column"],
    "colonnes sensibles": ["cleanup.purge.wizard.column"],
    "suppression de colonnes": ["cleanup.purge.wizard.column"],
    "purge de champs": ["cleanup.purge.wizard.field"],
    "champs orphelins": ["cleanup.purge.wizard.field"],
    "purge de tables": ["cleanup.purge.wizard.table"],
    "tables orphelines": ["cleanup.purge.wizard.table"],
    # Stock archive constraint
    "stock archive constraint": ["product.product", "stock.location"],
    "stock_archive_constraint": ["product.product", "stock.location"],
    "archiver un produit": ["product.product"],
    "archiver un emplacement": ["stock.location"],
    "archiver des produits": ["product.product"],
    "archiver des emplacements": ["stock.location"],
    "archivage de produit": ["product.product"],
    "archivage d'emplacement": ["stock.location"],
    "archivage d'un produit": ["product.product"],
    "archivage d'un emplacement": ["stock.location"],
    "archivage produit": ["product.product"],
    "archivage emplacement": ["stock.location"],
    "emplacements de stock": ["stock.location"],
    "emplacement de stock": ["stock.location"],
    "transfert de stock": ["stock.picking"],
    "transferts de stock": ["stock.picking"],
    "transfert": ["stock.picking"],
    "transferts": ["stock.picking"],
    "numero de serie": ["stock.lot"],
    "numéro de série": ["stock.lot"],
    "numeros de serie": ["stock.lot"],
    "numéros de série": ["stock.lot"],
    "numero de lot": ["stock.lot"],
    "numéro de lot": ["stock.lot"],
    "numeros de lot": ["stock.lot"],
    "numéros de lot": ["stock.lot"],
    # Auditlog
    "auditlog": ["auditlog.rule", "auditlog.log"],
    "regle d'audit": ["auditlog.rule"],
    "règle d'audit": ["auditlog.rule"],
    "regles d'audit": ["auditlog.rule"],
    "règles d'audit": ["auditlog.rule"],
    "regle audit": ["auditlog.rule"],
    "règle audit": ["auditlog.rule"],
    "regles audit": ["auditlog.rule"],
    "règles audit": ["auditlog.rule"],
    "audit rule": ["auditlog.rule"],
    "audit rules": ["auditlog.rule"],
    "modele audite": ["auditlog.rule"],
    "modèle audité": ["auditlog.rule"],
    "modeles audites": ["auditlog.rule"],
    "modèles audités": ["auditlog.rule"],
    "journalisation": ["auditlog.log"],
    "journal d'audit": ["auditlog.log"],
    "journaux d'audit": ["auditlog.log"],
    "logs d'audit": ["auditlog.log"],
    "log d'audit": ["auditlog.log"],
    # KPI
    "kpi": ["kpi"],
    "kpi.kpi": ["kpi"],
    "indicateur": ["kpi"],
    "indicateurs": ["kpi"],
    "kpis": ["kpi"],
    "valeur d'un kpi": ["kpi"],
    "calculer un kpi": ["kpi"],
    # Maintenance (Bloc N1) -- jamais ajoute lors de l'introduction du module (todo/contexte.txt section 748/767), gap distinct du bug d'accents deja corrige ailleurs (section 765)
    "equipement": ["maintenance.equipment"],
    "équipement": ["maintenance.equipment"],
    "equipements": ["maintenance.equipment"],
    "équipements": ["maintenance.equipment"],
    "fiche equipement": ["maintenance.equipment"],
    "fiche d'un equipement": ["maintenance.equipment"],
    "fiche d'équipement": ["maintenance.equipment"],
    "categorie d'equipement": ["maintenance.equipment.category"],
    "catégorie d'équipement": ["maintenance.equipment.category"],
    "categories d'equipement": ["maintenance.equipment.category"],
    "catégories d'équipement": ["maintenance.equipment.category"],
    "demande de maintenance": ["maintenance.request"],
    "demandes de maintenance": ["maintenance.request"],
    "demande de maintenance preventive": ["maintenance.request"],
    "demande de maintenance préventive": ["maintenance.request"],
    "demande recurrente": ["maintenance.request"],
    "demande récurrente": ["maintenance.request"],
    "demandes recurrentes": ["maintenance.request"],
    "demandes récurrentes": ["maintenance.request"],
}

# French synonyms for native Odoo models feeding the Step 2 fuzzy index.
NATIVE_MODEL_SYNONYMS: Dict[str, List[str]] = {
    "sale.order": ["commande de vente", "devis", "vente"],
    "purchase.order": ["commande d'achat"],
    "stock.picking": ["livraison"],
    "stock.move": ["mouvement de stock"],
    "maintenance.equipment": ["equipement", "équipement"],
    "maintenance.request": ["demande de maintenance"],
}


def _nfc(s: str) -> str:
    """Normalize string using Unicode NFC."""
    return unicodedata.normalize("NFC", s)


BUSINESS_ALIASES_NFC: Dict[str, List[str]] = {_nfc(k): v for k, v in BUSINESS_ALIASES.items()}

_ALIAS_PATTERNS: Dict[str, re.Pattern] = {
    alias: re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)")
    for alias in BUSINESS_ALIASES_NFC
}

# Section 877: le singulier "avoir" est aussi l'infinitif du verbe ("une
# commande ne peut pas avoir de date" -> SAL-Q5 resolvait account.move a tort,
# dump de 43 798 car.). Le pluriel "avoirs" n'a pas de forme verbale : inchange.
# Garde POSITIVE sur le singulier : le nom n'est retenu que precede d'un
# determinant/possessif ("un avoir", "l'avoir", "cet avoir"...) ou en debut de
# requete ("avoir" seul, "Avoir client : ..."). Limite connue : "l'avoir" en
# pronom+verbe ("peut-il l'avoir ?") matche encore ; "valider avoir" sans
# article ne matche plus.
_AVOIR_NOUN_PATTERN = re.compile(
    r"(?:(?<!\w)(?:un|le|cet|ce|cette|mon|ton|son|notre|votre|leur|chaque|nouvel|seul)\s+"
    r"|(?<!\w)l['\u2019]\s*)avoir(?!\w)"
    r"|^\s*avoir(?!\w)"
)
if "avoir" in _ALIAS_PATTERNS:
    _ALIAS_PATTERNS["avoir"] = _AVOIR_NOUN_PATTERN
