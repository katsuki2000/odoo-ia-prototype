# Bloc 6 — Politique de résolution de conflit inter-branches

## Périmètre

Le routeur arbitre entre quatre branches :

1. `code_intelligence`
2. `donnees_erp`
3. `hybride`
4. `documentaire`

La question à trancher est la frontière entre RAG documentaire, Function Calling ERP et Code Intelligence.

## Politique

### Code > wiki pour les questions de gouvernance

Quand la question porte sur qui peut approuver, valider, accéder, voir ou modifier un élément Odoo, la branche `code_intelligence` prime. Le code Python, les `ir.rule`, les actions serveur et les verrous `UserError` sont la source effectivement exécutée. Le wiki peut décrire une politique cible, mais il peut être incomplet ou obsolète.

### Données ERP > code pour les questions quantitatives

Quand la question demande un nombre, une somme, une moyenne, un statut d'enregistrement ou une liste d'enregistrements, la branche `donnees_erp` prime. Les concepts de gouvernance mentionnés dans la phrase sont alors traités comme contexte d'audit, pas comme demande d'analyse statique du code.

### Ancrage explicite au wiki

Quand la question contient un ancrage documentaire explicite, par exemple "selon le wiki", "où est documenté", "dans le wiki" ou "selon la politique interne", la branche `documentaire` prime. Si la même question contient aussi une demande de données chiffrées distincte, la branche `hybride` est utilisée.

### Hybride uniquement pour deux sous-questions

`hybride` est réservé aux questions qui demandent réellement deux réponses complémentaires, par exemple une procédure documentaire et un chiffre ERP. Une simple mention d'un montant dans une question de droit d'approbation ne suffit pas à rendre la question hybride.

## Jeux d'exemples validés

Les exemples few-shot sont dans `tests/few_shot_routing_examples.py`. Chaque cas contient :

- la question utilisateur ;
- la branche attendue ;
- la justification métier ;
- la note de conflit expliquant quelle branche aurait pu être choisie et pourquoi elle ne l'est pas.

La non-régression est couverte par `tests/test_j18_routing_fewshot.py`.
