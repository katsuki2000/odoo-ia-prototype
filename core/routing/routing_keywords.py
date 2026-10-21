"""Routing keywords, accent-folding helpers, and route priority definitions."""

import unicodedata
from core.schemas import QueryRoute

ERP_TYPES = {"sale", "ticket"}

# Inter-branch conflict policy: code intelligence takes priority for security/governance.
ROUTING_CONFLICT_PRIORITY = (
    QueryRoute.CODE_INTELLIGENCE.value,
    QueryRoute.ERP_DATA.value,
    QueryRoute.HYBRID.value,
    QueryRoute.DOCUMENTARY.value,
)

ERP_KEYWORDS = [
    "combien de", "montant total", "total des", "chiffre d'affaires",
    "statut de la", "statut commande", "factures impayées", "factures payées",
    "quantité disponible", "produit en rupture", "le plus récent",
    "tickets résolus", "tickets en cours", "tickets de support", "tickets", "ticket", "rechercher client", "coordonnées",
    "toutes périodes confondues", "ce mois", "cette année", "moyenne",
    "stock", "quel produit", "montant moyen",
]

CODE_INTEL_KEYWORDS = [
    "qui a accès", "qui a acces", "permission d'accès", "permission d acces", "droits d'accès",
    "permission de lecture", "permission d'écriture", "permission de modification", "permission de suppression",
    "quel groupe a accès", "quels groupes ont accès", "qui a le permission",
    "règle d'enregistrement", "regle d'enregistrement", "ir.rule", "règle de sécurité", "regle de securite",
    "action serveur", "action automati", "base.automation", "ir.actions.server", "sudo", "logique cachée",
    "verrou", "validateurs exceptionnels", "validationerror", "usererror", "dispatch dynamique", "getattr",
    "impact de la modification", "impact de modification", "si je modifie le champ",
    "changement du champ", "impact du champ", "champs calculés dépendants",
    "chemin d'exécution", "chemin execution", "bouton", "quand je clique sur",
    "action du bouton", "que fait le bouton", "modèle odoo", "modele odoo",
    "approuver", "approbation", "qui peut valider", "peut-il voir",
    "règles d'approbation", "regles d'approbation", "mêmes règles",
    "seuil d'approbation", "conditions pour valider", "processus d'approbation",
    "peut-il accéder", "peut-elle voir", "peut-il modifier",
    "peut-il consulter", "peut-elle consulter", "consulter",
]

QUANTITATIVE_TERMS = [
    "combien", "montant", "total", "résolu", "en cours", "moyenne",
    "chiffre", "quel est le stock",
]

DOC_KEYWORDS = [
    "comment", "procédure", "qui peut", "qui doit", "quel fichier",
    "quelle classe", "quel est le rôle", "quels sont les modèles",
    "dans quel fichier", "procédure de validation", "politique interne",
    "selon le wiki",
]

DATA_TERMS = [
    "combien", "montant", "ticket", "vente", "statut", "liste", "résolu",
    "en cours", "stock", "facture", "commande", "client", "chiffre",
]

DOC_ANCHORS = [
    "selon le wiki", "selon la politique interne", "où est documenté",
    "dans le wiki", "wiki interne",
]

THRESHOLD_QUERY_TERMS = [
    "seuil d'approbation", "plafond", "dépasse-t-il", "depasse-t-il",
]

CONDITIONAL_AMOUNT_TERMS = [
    "quel que soit", "quelle que soit",
]


def _fold_accents(text: str) -> str:
    """Strip diacritics for accent-insensitive keyword matching."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def _fold_keywords(keywords: list) -> list:
    """Pre-fold a keyword list once at import time, not once per request."""
    return [_fold_accents(kw) for kw in keywords]


ERP_KEYWORDS_FOLDED = _fold_keywords(ERP_KEYWORDS)
CODE_INTEL_KEYWORDS_FOLDED = _fold_keywords(CODE_INTEL_KEYWORDS)
QUANTITATIVE_TERMS_FOLDED = _fold_keywords(QUANTITATIVE_TERMS)
DOC_KEYWORDS_FOLDED = _fold_keywords(DOC_KEYWORDS)
DATA_TERMS_FOLDED = _fold_keywords(DATA_TERMS)
DOC_ANCHORS_FOLDED = _fold_keywords(DOC_ANCHORS)
THRESHOLD_QUERY_TERMS_FOLDED = _fold_keywords(THRESHOLD_QUERY_TERMS)
CONDITIONAL_AMOUNT_TERMS_FOLDED = _fold_keywords(CONDITIONAL_AMOUNT_TERMS)
