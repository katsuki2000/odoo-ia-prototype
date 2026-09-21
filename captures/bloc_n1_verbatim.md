# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-21 16:44:49

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `11.36s` |
| p90 latence effective | `11.36s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `11.36s` |
| Max | `11.36s` |

---

## [SAL-Q5] sale -- constraints (medium)
**Question :** Quelle contrainte empeche une commande confirmee de ne pas avoir de date de confirmation, et quelle contrainte distincte s'applique sur le pourcentage d'acompte demande (prepayment_percent) ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts : (1) sur sale.order, _sql_constraints porte date_order_conditional_required -- contrainte SQL CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale'), bloquant au niveau base de donnees toute commande a l'etat 'sale' sans date_order renseignee. (2) _check_prepayment_percent (@api.constrains('prepayment_percent')) leve une ValidationError Python si require_payment est actif et que prepayment_percent n'est pas strictement compris entre 0 (exclu) et 1.0 (inclus) -- verifiee a l'ecriture ORM, pas au niveau SQL. Independamment, sale.order.line porte ses propres contraintes SQL structurelles (accountable_required_fields/non_accountable_null_fields) sur le meme modele que purchase.order.line (PUR-Q5), meme logique display_type NULL/non-NULL.

**A verifier dans le code :** `models/sale_order.py : _sql_constraints (date_order_conditional_required), _check_prepayment_percent (@api.constrains) ; models/sale_order_line.py : _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 11.36s | Effectif: 11.361s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Contraintes de validation sur les commandes

| Type de contrainte | Description | Source |
|--------------------|-------------|--------|
| **SQL : `date_order_conditional_required`** | Empêche qu’une commande confirmée (`state = 'sale'`) n’ait pas de date de confirmation (`date_order`). | [sale_order.py:L37-L41](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L37-L41) |
| **Python : `_check_prepayment_percent`** | Vérifie que, lorsqu’une commande exige un paiement (`require_payment`), le pourcentage d’acompte (`prepayment_percent`) est compris strictement entre 0 % et 100 % (0 < `prepayment_percent` ≤ 1.0). | [sale_order.py:L722-L726](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L722-L726) |

**En résumé**

- La **contrainte SQL** `date_order_conditional_required` garantit qu’une commande confirmée possède toujours une date de confirmation.
- La **contrainte Python** `_check_prepayment_percent` impose une plage valide au pourcentage d’acompte demandé, distincte de la contrainte de date.

[Source: Graphe de Connaissances Code Intelligence]
```

---